"""Turns command-line options into Household calendar changes. No Apple calls here."""

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from .events import Event

REPEATS = ("daily", "weekly", "monthly", "yearly")
_CLOCK = re.compile(r"\d{1,2}:\d{2}")


class InputError(ValueError):
    """A command-line value that can't be turned into a change."""


@dataclass(frozen=True)
class Times:
    start: datetime
    end: datetime  # exclusive; all-day events end at midnight after the last day
    all_day: bool


@dataclass(frozen=True)
class Repeat:
    frequency: str  # one of REPEATS
    until: date | None = None
    count: int | None = None


def parse_when(text: str, tz: ZoneInfo, day: date | None = None) -> datetime:
    """'YYYY-MM-DD HH:MM' in local time. A bare 'HH:MM' is taken on `day`."""
    text = text.strip()
    if day and _CLOCK.fullmatch(text):
        return datetime.combine(day, parse_clock(text), tz)
    try:
        value = datetime.fromisoformat(text)
    except ValueError:
        raise InputError(f"Couldn't read the time {text!r}. Use YYYY-MM-DD HH:MM (24-hour).") from None
    return value.replace(tzinfo=tz) if value.tzinfo is None else value.astimezone(tz)


def parse_day(text: str) -> date:
    try:
        return date.fromisoformat(text.strip())
    except ValueError:
        raise InputError(f"Couldn't read the date {text!r}. Use YYYY-MM-DD.") from None


def parse_clock(text: str) -> time:
    if not _CLOCK.fullmatch(text.strip()):
        raise InputError(f"Couldn't read the time {text!r}. Use HH:MM (24-hour).")
    hours, minutes = map(int, text.strip().split(":"))
    try:
        return time(hours, minutes)
    except ValueError:
        raise InputError(f"{text!r} isn't a real time of day.") from None


def resolve_times(
    tz: ZoneInfo,
    *,
    start: str | None = None,
    end: str | None = None,
    minutes: int | None = None,
    day: str | None = None,
    through: str | None = None,
    current: Event | None = None,
) -> Times | None:
    """Start and end from command-line options, or None if no time option was given.

    `current` is the existing event when updating: moving a timed event keeps
    its length, and --end/--minutes alone keep its start.
    """
    if day or through:
        if start or end or minutes:
            raise InputError("Use --date/--through for all-day events or --start/--end for timed ones, not both.")
        if day:
            first = parse_day(day)
        elif current and current.all_day:
            first = current.start.date()
        else:
            raise InputError("--through needs --date.")
        last = parse_day(through) if through else first
        if last < first:
            raise InputError("--through is before --date.")
        return Times(
            datetime.combine(first, time(), tz),
            datetime.combine(last + timedelta(days=1), time(), tz),
            all_day=True,
        )

    if not (start or end or minutes):
        return None
    if end and minutes:
        raise InputError("Use --end or --minutes, not both.")

    timed_current = current if current and not current.all_day else None
    if start:
        begins = parse_when(start, tz)
    elif timed_current:
        begins = timed_current.start
    else:
        raise InputError("--end and --minutes need --start.")

    if end:
        ends = parse_when(end, tz, day=begins.date())
    elif minutes:
        ends = begins + timedelta(minutes=minutes)
    elif timed_current:
        ends = begins + (timed_current.end - timed_current.start)
    else:
        ends = begins + timedelta(hours=1)

    if ends <= begins:
        raise InputError("The event has to end after it starts.")
    return Times(begins, ends, all_day=False)


def make_repeat(frequency: str | None, until: str | None, count: int | None) -> Repeat | None:
    if not frequency:
        if until or count:
            raise InputError("--until and --count need --repeat.")
        return None
    if frequency not in REPEATS:
        raise InputError(f"--repeat must be one of: {', '.join(REPEATS)}.")
    if until and count:
        raise InputError("Use --until or --count, not both.")
    if count is not None and count < 1:
        raise InputError("--count must be at least 1.")
    return Repeat(frequency, parse_day(until) if until else None, count)


def describe(event: Event) -> str:
    """One line such as 'Sat Oct 3, 2:00 PM–3:00 PM  Soccer  @ Field 4  (id abc)'."""
    if event.all_day:
        first = event.start.date()
        last = (event.end - timedelta(days=1)).date()
        when = f"{first:%a %b} {first.day}, all day"
        if last > first:
            when = f"{first:%a %b} {first.day} – {last:%a %b} {last.day}, all day"
    else:
        s, e = event.start, event.end
        end_part = _clock(e) if e.date() == s.date() else f"{e:%a} {_clock(e)}"
        when = f"{s:%a %b} {s.day}, {_clock(s)}–{end_part}"
    where = f"  @ {event.location}" if event.location else ""
    repeat = "  (repeats)" if event.repeats else ""
    return f"{when}  {event.title}{where}{repeat}  (id {event.event_id})"


def _clock(t: datetime) -> str:
    return f"{t:%I:%M %p}".lstrip("0")
