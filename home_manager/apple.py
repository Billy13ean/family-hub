"""Apple Calendar and Reminders through EventKit (macOS only, via PyObjC).

This is the only module that talks to Apple. Everything else goes through
`AppleStore`, and the tests swap in a fake with the same methods.

macOS grants Calendar and Reminders access to the app that runs the command,
which is Terminal for the family hub. `./hm setup` asks for it once.
"""

import threading
import time as systime
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from .events import Event
from .household import Repeat, Times
from .reminders import KEEP, Reminder

# EventKit constants, spelled out so the pure-Python parts don't need EventKit.
_ENTITY_EVENT, _ENTITY_REMINDER = 0, 1
_FULL_ACCESS = 3  # EKAuthorizationStatusFullAccess (the old "Authorized")
_SPAN_THIS, _SPAN_FUTURE = 0, 1
_AVAILABILITY_FREE = 1
_STATUS_CANCELED = 3
_PARTICIPANT_DECLINED = 3
_SKIPPED_CALENDAR_TYPES = {3, 4}  # subscribed calendars and Birthdays
_FREQUENCIES = {"daily": 0, "weekly": 1, "monthly": 2, "yearly": 3}
_FREQUENCY_NAMES = {v: k for k, v in _FREQUENCIES.items()}
_UNDEFINED = 0x7FFFFFFFFFFFFFFF  # NSDateComponentUndefined


class AppleError(Exception):
    pass


@dataclass(frozen=True)
class CalendarInfo:
    name: str
    account: str
    writable: bool


def _frameworks():
    try:
        import EventKit
        import Foundation
    except ImportError as e:
        raise AppleError(
            "EventKit isn't available. The calendar and list commands only run on macOS, "
            "where `uv sync` installs PyObjC."
        ) from e
    return EventKit, Foundation


class AppleStore:
    def __init__(self, tz: ZoneInfo):
        self.EK, self.F = _frameworks()
        self.tz = tz
        self.store = self.EK.EKEventStore.alloc().init()
        # macOS can keep reporting "not determined" for the rest of the process
        # after access is granted, so remember grants made in this run.
        self._granted: set[int] = set()

    # --- Access -----------------------------------------------------------------

    def request_access(self) -> dict[str, bool]:
        """Ask for Calendar and Reminders access (shows the macOS prompts the first time)."""
        return {
            "Calendars": self._request(_ENTITY_EVENT),
            "Reminders": self._request(_ENTITY_REMINDER),
        }

    def _request(self, entity: int) -> bool:
        if self.EK.EKEventStore.authorizationStatusForEntityType_(entity) == _FULL_ACCESS:
            self._granted.add(entity)
            return True
        done, result = threading.Event(), []

        def handler(granted, error):
            result.append(bool(granted))
            done.set()

        if entity == _ENTITY_EVENT:
            self.store.requestFullAccessToEventsWithCompletion_(handler)
        else:
            self.store.requestFullAccessToRemindersWithCompletion_(handler)
        self._wait(done, 300, "the access prompt")
        self.store = self.EK.EKEventStore.alloc().init()  # a fresh store sees the new permission
        if result[0]:
            self._granted.add(entity)
        return result[0]

    def _require(self, entity: int) -> None:
        if entity in self._granted:
            return
        if self.EK.EKEventStore.authorizationStatusForEntityType_(entity) != _FULL_ACCESS:
            what = "Calendars" if entity == _ENTITY_EVENT else "Reminders"
            raise AppleError(
                f"No access to {what}. Run `./hm setup` in Terminal and click Allow, or turn on "
                f"Terminal in System Settings > Privacy & Security > {what} (Full Access)."
            )

    def _wait(self, done: threading.Event, seconds: float, what: str) -> None:
        """Wait for an EventKit callback, running the run loop in case it's delivered there."""
        deadline = systime.monotonic() + seconds
        loop = self.F.NSRunLoop.currentRunLoop()
        while not done.is_set():
            if systime.monotonic() > deadline:
                raise AppleError(f"Gave up waiting for {what} after {int(seconds)} seconds.")
            loop.runUntilDate_(self.F.NSDate.dateWithTimeIntervalSinceNow_(0.05))

    # --- Dates --------------------------------------------------------------------

    def _ns(self, value: datetime):
        return self.F.NSDate.dateWithTimeIntervalSince1970_(value.timestamp())

    def _py(self, ns_date) -> datetime:
        return datetime.fromtimestamp(ns_date.timeIntervalSince1970(), self.tz)

    # --- Calendars ----------------------------------------------------------------

    def _event_calendars(self) -> list:
        self._require(_ENTITY_EVENT)
        return list(self.store.calendarsForEntityType_(_ENTITY_EVENT) or [])

    def _reminder_calendars(self) -> list:
        self._require(_ENTITY_REMINDER)
        return list(self.store.calendarsForEntityType_(_ENTITY_REMINDER) or [])

    @staticmethod
    def _info(cal) -> CalendarInfo:
        source = cal.source()
        return CalendarInfo(cal.title(), source.title() if source else "", bool(cal.allowsContentModifications()))

    def calendars(self) -> list[CalendarInfo]:
        return [self._info(c) for c in self._event_calendars()]

    def reminder_lists(self) -> list[CalendarInfo]:
        return [self._info(c) for c in self._reminder_calendars()]

    @staticmethod
    def _pick(cals: list, name: str, what: str):
        matches = [c for c in cals if c.title().casefold() == name.casefold()]
        if not matches:
            names = ", ".join(sorted({c.title() for c in cals})) or "none"
            raise AppleError(f"No {what} named {name!r}. This account has: {names}.")
        writable = [c for c in matches if c.allowsContentModifications()]
        return (writable or matches)[0]

    def _reading(self, names: tuple[str, ...]) -> list:
        cals = self._event_calendars()
        if names:
            return [self._pick(cals, n, "calendar") for n in names]
        return [c for c in cals if c.type() not in _SKIPPED_CALENDAR_TYPES]

    def _writable_calendar(self, name: str):
        cal = self._pick(self._event_calendars(), name, "calendar")
        if not cal.allowsContentModifications():
            raise AppleError(f"The {name} calendar is read-only here. Share it with the hub's Apple Account with editing allowed.")
        return cal

    # --- Events -------------------------------------------------------------------

    def events(self, start: datetime, end: datetime, calendars: tuple[str, ...] = (), labels: dict | None = None) -> list[Event]:
        cals = self._reading(calendars)
        if not cals:
            return []
        predicate = self.store.predicateForEventsWithStartDate_endDate_calendars_(self._ns(start), self._ns(end), cals)
        found = (self._to_event(ev, labels) for ev in self.store.eventsMatchingPredicate_(predicate) or [])
        return [e for e in found if e]

    def _to_event(self, ev, labels: dict | None = None) -> Event | None:
        if ev.status() == _STATUS_CANCELED:
            return None
        for attendee in ev.attendees() or []:
            if attendee.isCurrentUser() and attendee.participantStatus() == _PARTICIPANT_DECLINED:
                return None
        name = ev.calendar().title()
        start, end = self._py(ev.startDate()), self._py(ev.endDate())
        all_day = bool(ev.isAllDay())
        if all_day:
            # EventKit ends all-day events at 23:59:59 on the last day (or at the next
            # midnight); normalize to midnight after the last day.
            first = start.date()
            last = (end - timedelta(seconds=1)).date() if end.time() == time() else end.date()
            start = datetime.combine(first, time(), self.tz)
            end = datetime.combine(max(last, first) + timedelta(days=1), time(), self.tz)
        return Event(
            owners=((labels or {}).get(name, name),),
            title=ev.title() or "(busy)",
            start=start,
            end=end,
            all_day=all_day,
            busy=ev.availability() != _AVAILABILITY_FREE,
            uid=ev.calendarItemExternalIdentifier() or ev.eventIdentifier() or "",
            event_id=self._event_id(ev),
            calendar=name,
            location=ev.location() or None,
            notes=ev.notes() or None,
            repeats=bool(ev.hasRecurrenceRules()),
        )

    def _event_id(self, ev) -> str:
        """eventIdentifier names the whole series, so a repeat also carries its occurrence."""
        base = ev.eventIdentifier() or ""
        if ev.hasRecurrenceRules():
            occurrence = self._py(ev.occurrenceDate() or ev.startDate())
            return f"{base}@{occurrence:%Y%m%dT%H%M}"
        return base

    def _find_event(self, event_id: str):
        base, marker, occurrence = event_id.rpartition("@")
        if not marker or not (len(occurrence) == 13 and occurrence[8] == "T"):
            base, occurrence = event_id, ""
        ev = self.store.eventWithIdentifier_(base)
        if ev is None:
            raise AppleError(f"No event with id {event_id}. Get ids from `cal list` or `cal find`.")
        if not occurrence:
            return ev
        when = datetime.strptime(occurrence, "%Y%m%dT%H%M").replace(tzinfo=self.tz)
        predicate = self.store.predicateForEventsWithStartDate_endDate_calendars_(
            self._ns(when - timedelta(days=1)), self._ns(when + timedelta(days=2)), [ev.calendar()]
        )
        for candidate in self.store.eventsMatchingPredicate_(predicate) or []:
            if self._event_id(candidate) == event_id:
                return candidate
        raise AppleError(f"That repeating event has no occurrence on {when:%a %b} {when.day}. Run `cal list` for fresh ids.")

    def _check_calendar(self, ev, allowed: str) -> None:
        name = ev.calendar().title()
        if name.casefold() != allowed.casefold():
            raise AppleError(f"That event is on {name}, which the hub doesn't change. Only {allowed} events can be changed.")

    def get_event(self, event_id: str) -> Event:
        self._require(_ENTITY_EVENT)
        return self._to_event(self._find_event(event_id))

    def _set_times(self, ev, times: Times) -> None:
        ev.setAllDay_(times.all_day)
        ev.setStartDate_(self._ns(times.start))
        # All-day events end on their last day in EventKit.
        ev.setEndDate_(self._ns(times.end - timedelta(seconds=1) if times.all_day else times.end))

    def _rule(self, frequency: str, until: date | None = None, count: int | None = None):
        end = None
        if until:
            end = self.EK.EKRecurrenceEnd.recurrenceEndWithEndDate_(self._ns(datetime.combine(until, time(23, 59, 59), self.tz)))
        elif count:
            end = self.EK.EKRecurrenceEnd.recurrenceEndWithOccurrenceCount_(count)
        return self.EK.EKRecurrenceRule.alloc().initRecurrenceWithFrequency_interval_end_(_FREQUENCIES[frequency], 1, end)

    def _save_event(self, ev, span: int) -> None:
        ok, error = self.store.saveEvent_span_commit_error_(ev, span, True, None)
        if not ok:
            raise AppleError(f"Calendar refused the change: {error.localizedDescription() if error else 'unknown error'}")

    def add_event(self, calendar: str, title: str, times: Times, location: str | None = None,
                  notes: str | None = None, repeat: Repeat | None = None) -> Event:
        ev = self.EK.EKEvent.eventWithEventStore_(self.store)
        ev.setCalendar_(self._writable_calendar(calendar))
        ev.setTitle_(title)
        self._set_times(ev, times)
        if location:
            ev.setLocation_(location)
        if notes:
            ev.setNotes_(notes)
        if repeat:
            ev.addRecurrenceRule_(self._rule(repeat.frequency, repeat.until, repeat.count))
        self._save_event(ev, _SPAN_FUTURE if repeat else _SPAN_THIS)
        return self._to_event(ev)

    def update_event(self, event_id: str, calendar: str, *, title: str | None = None, times: Times | None = None,
                     location: str | None = None, notes: str | None = None, future: bool = False) -> Event:
        """Change one occurrence, or with `future` this and every later one."""
        self._require(_ENTITY_EVENT)
        ev = self._find_event(event_id)
        self._check_calendar(ev, calendar)
        if title:
            ev.setTitle_(title)
        if times:
            self._set_times(ev, times)
        if location is not None:
            ev.setLocation_(location or None)
        if notes is not None:
            ev.setNotes_(notes or None)
        self._save_event(ev, _SPAN_FUTURE if future and ev.hasRecurrenceRules() else _SPAN_THIS)
        return self._to_event(ev)

    def delete_event(self, event_id: str, calendar: str, future: bool = False) -> Event:
        self._require(_ENTITY_EVENT)
        ev = self._find_event(event_id)
        self._check_calendar(ev, calendar)
        gone = self._to_event(ev)
        span = _SPAN_FUTURE if future and ev.hasRecurrenceRules() else _SPAN_THIS
        ok, error = self.store.removeEvent_span_commit_error_(ev, span, True, None)
        if not ok:
            raise AppleError(f"Calendar refused the delete: {error.localizedDescription() if error else 'unknown error'}")
        return gone

    # --- Reminders ----------------------------------------------------------------

    def _list(self, name: str):
        return self._pick(self._reminder_calendars(), name, "Reminders list")

    def _fetch(self, predicate) -> list:
        done, box = threading.Event(), []

        def handler(items):
            box.append(list(items or []))
            done.set()

        self.store.fetchRemindersMatchingPredicate_completion_(predicate, handler)
        self._wait(done, 60, "Reminders")
        return box[0]

    def reminders(self, list_name: str, completed_days: int = 0) -> list[Reminder]:
        """Open items on one list, plus items completed in the last `completed_days` days."""
        cal = self._list(list_name)
        items = self._fetch(self.store.predicateForIncompleteRemindersWithDueDateStarting_ending_calendars_(None, None, [cal]))
        if completed_days:
            now = datetime.now(self.tz)
            items += self._fetch(self.store.predicateForCompletedRemindersWithCompletionDateStarting_ending_calendars_(
                self._ns(now - timedelta(days=completed_days)), self._ns(now + timedelta(minutes=1)), [cal]))
        return [self._to_reminder(r) for r in items]

    def open_reminders(self) -> list[Reminder]:
        """Open items on every list, for due-date checks."""
        cals = self._reminder_calendars()
        if not cals:
            return []
        items = self._fetch(self.store.predicateForIncompleteRemindersWithDueDateStarting_ending_calendars_(None, None, cals))
        return [self._to_reminder(r) for r in items]

    def _to_reminder(self, r) -> Reminder:
        due = at = None
        comps = r.dueDateComponents()
        if comps is not None and comps.year() not in (_UNDEFINED, 0) and comps.day() not in (_UNDEFINED, 0):
            due = date(comps.year(), comps.month(), comps.day())
            if comps.hour() != _UNDEFINED:
                at = time(comps.hour(), comps.minute() if comps.minute() != _UNDEFINED else 0)

        repeat, interval, anchor = None, 1, None
        rules = list(r.recurrenceRules() or [])
        if rules:
            rule = rules[0]
            days_of_month = [int(d) for d in (rule.daysOfTheMonth() or [])]
            simple = (
                len(rules) == 1
                and rule.frequency() in _FREQUENCY_NAMES
                and not rule.daysOfTheWeek()
                and not rule.monthsOfTheYear()
                and not rule.weeksOfTheYear()
                and not rule.daysOfTheYear()
                and not rule.setPositions()
                and len(days_of_month) <= 1
                and all(d > 0 for d in days_of_month)
            )
            repeat = _FREQUENCY_NAMES[rule.frequency()] if simple else "custom"
            interval = int(rule.interval() or 1)
            anchor = days_of_month[0] if days_of_month else None

        completed_on = None
        if r.isCompleted() and r.completionDate():
            completed_on = self._py(r.completionDate()).date()
        return Reminder(
            id=r.calendarItemIdentifier(),
            title=r.title() or "(untitled)",
            list=r.calendar().title(),
            due=due,
            at=at,
            notes=r.notes() or None,
            repeat=repeat,
            interval=interval,
            anchor_day=anchor,
            completed=bool(r.isCompleted()),
            completed_on=completed_on,
        )

    def _set_due(self, r, due: date | None, at: time | None) -> None:
        # Alarms go with the due time, so replace them whenever the due date changes.
        for alarm in list(r.alarms() or []):
            r.removeAlarm_(alarm)
        if due is None:
            r.setDueDateComponents_(None)
            return
        comps = self.F.NSDateComponents.alloc().init()
        comps.setYear_(due.year)
        comps.setMonth_(due.month)
        comps.setDay_(due.day)
        if at:
            comps.setHour_(at.hour)
            comps.setMinute_(at.minute)
            comps.setTimeZone_(self.F.NSTimeZone.timeZoneWithName_(self.tz.key))
            # Phones notify at the time. Date-only items use each phone's all-day reminder time.
            r.addAlarm_(self.EK.EKAlarm.alarmWithAbsoluteDate_(self._ns(datetime.combine(due, at, self.tz))))
        r.setDueDateComponents_(comps)

    def _save_reminder(self, r) -> None:
        ok, error = self.store.saveReminder_commit_error_(r, True, None)
        if not ok:
            raise AppleError(f"Reminders refused the change: {error.localizedDescription() if error else 'unknown error'}")

    def _find_reminder(self, rem_id: str):
        self._require(_ENTITY_REMINDER)
        r = self.store.calendarItemWithIdentifier_(rem_id)
        if r is None or not r.isKindOfClass_(self.EK.EKReminder):
            raise AppleError("That item is gone. Run `list show` for fresh ids.")
        return r

    def add_reminder(self, list_name: str, title: str, due: date | None = None, at: time | None = None,
                     notes: str | None = None, repeat: str | None = None) -> Reminder:
        cal = self._list(list_name)
        if not cal.allowsContentModifications():
            raise AppleError(f"The {cal.title()} list is read-only here. Share it with the hub's Apple Account.")
        r = self.EK.EKReminder.reminderWithEventStore_(self.store)
        r.setCalendar_(cal)
        r.setTitle_(title)
        if notes:
            r.setNotes_(notes)
        self._set_due(r, due, at)
        if repeat:
            r.addRecurrenceRule_(self._rule(repeat))
        self._save_reminder(r)
        return self._to_reminder(r)

    def update_reminder(self, rem_id: str, *, title: str | None = None, due=KEEP, at=KEEP, notes: str | None = None,
                        repeat=KEEP, completed: bool | None = None) -> Reminder:
        r = self._find_reminder(rem_id)
        if title:
            r.setTitle_(title)
        if notes is not None:
            r.setNotes_(notes or None)
        if due is not KEEP or at is not KEEP:
            current = self._to_reminder(r)
            new_due = current.due if due is KEEP else due
            new_at = current.at if at is KEEP else at
            self._set_due(r, new_due, new_at if new_due else None)
        if repeat is not KEEP:
            for rule in list(r.recurrenceRules() or []):
                r.removeRecurrenceRule_(rule)
            if repeat:
                r.addRecurrenceRule_(self._rule(repeat))
        if completed is not None:
            r.setCompleted_(completed)
        self._save_reminder(r)
        return self._to_reminder(r)

    def delete_reminder(self, rem_id: str) -> None:
        r = self._find_reminder(rem_id)
        ok, error = self.store.removeReminder_commit_error_(r, True, None)
        if not ok:
            raise AppleError(f"Reminders refused the delete: {error.localizedDescription() if error else 'unknown error'}")
