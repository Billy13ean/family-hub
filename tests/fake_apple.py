"""An in-memory stand-in for AppleStore, with the same methods, so tests run anywhere."""

import hashlib
from dataclasses import replace

from home_manager.apple import AppleError, CalendarInfo
from home_manager.events import Event
from home_manager.reminders import KEEP, Reminder


class FakeStore:
    def __init__(self, tz):
        self.tz = tz
        self.calendar_access = {"Household": True, "Home": False, "Sarah": False}
        self.list_names = ["Grocery", "To-Do", "Bills"]
        self.events_list: list[Event] = []
        self.items: list[Reminder] = []
        self.count = 0

    # Access and names
    def request_access(self):
        return {"Calendars": True, "Reminders": True}

    def calendars(self):
        return [CalendarInfo(n, "iCloud", w) for n, w in self.calendar_access.items()]

    def reminder_lists(self):
        return [CalendarInfo(n, "iCloud", True) for n in self.list_names]

    # Events
    def seed_event(self, calendar, title, start, end, uid=None, **extra):
        self.count += 1
        event = Event((calendar,), title, start, end, False, True, uid or f"u{self.count}",
                      event_id=f"e{self.count}", calendar=calendar, **extra)
        self.events_list.append(event)
        return event

    def events(self, start, end, calendars=(), labels=None):
        names = calendars or tuple(self.calendar_access)
        return [
            replace(e, owners=((labels or {}).get(e.calendar, e.calendar),))
            for e in self.events_list
            if e.calendar in names and e.start < end and e.end > start
        ]

    def _find(self, event_id):
        for e in self.events_list:
            if e.event_id == event_id:
                return e
        raise AppleError(f"No event with id {event_id}.")

    def get_event(self, event_id):
        return self._find(event_id)

    def add_event(self, calendar, title, times, location=None, notes=None, repeat=None):
        if not self.calendar_access.get(calendar):
            raise AppleError(f"The {calendar} calendar is read-only here.")
        self.last_repeat = repeat
        event = self.seed_event(calendar, title, times.start, times.end, location=location, notes=notes,
                                repeats=bool(repeat))
        event = replace(event, all_day=times.all_day)
        self.events_list[-1] = event
        return event

    def update_event(self, event_id, calendar, *, title=None, times=None, location=None, notes=None, future=False):
        event = self._find(event_id)
        if event.calendar != calendar:
            raise AppleError(f"That event is on {event.calendar}, which the hub doesn't change.")
        changes = {}
        if title:
            changes["title"] = title
        if times:
            changes.update(start=times.start, end=times.end, all_day=times.all_day)
        if location is not None:
            changes["location"] = location or None
        if notes is not None:
            changes["notes"] = notes or None
        updated = replace(event, **changes)
        self.events_list[self.events_list.index(event)] = updated
        self.last_future = future
        return updated

    def delete_event(self, event_id, calendar, future=False):
        event = self._find(event_id)
        if event.calendar != calendar:
            raise AppleError(f"That event is on {event.calendar}, which the hub doesn't change.")
        self.events_list.remove(event)
        return event

    # Reminders
    def reminders(self, list_name, completed_days=0):
        self._check_list(list_name)
        return [r for r in self.items if r.list.lower() == list_name.lower() and (completed_days or not r.completed)]

    def open_reminders(self):
        return [r for r in self.items if not r.completed]

    def _check_list(self, name):
        if name.lower() not in {n.lower() for n in self.list_names}:
            raise AppleError(f"No Reminders list named {name!r}.")

    def add_reminder(self, list_name, title, due=None, at=None, notes=None, repeat=None):
        self._check_list(list_name)
        rid = hashlib.md5(f"{list_name}/{title}".encode()).hexdigest().upper()
        r = Reminder(rid, title, list_name, due=due, at=at, notes=notes, repeat=repeat)
        self.items.append(r)
        return r

    def update_reminder(self, rem_id, *, title=None, due=KEEP, at=KEEP, notes=None, repeat=KEEP, completed=None):
        r = next(i for i in self.items if i.id == rem_id)
        changes = {}
        if title:
            changes["title"] = title
        if notes is not None:
            changes["notes"] = notes or None
        if due is not KEEP:
            changes["due"] = due
        if at is not KEEP:
            changes["at"] = at
        if repeat is not KEEP:
            changes["repeat"] = repeat
        if completed is not None:
            changes["completed"] = completed
        updated = replace(r, **changes)
        self.items[self.items.index(r)] = updated
        return updated

    def delete_reminder(self, rem_id):
        self.items = [i for i in self.items if i.id != rem_id]
