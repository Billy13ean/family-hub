"""The calendar event model shared by the Apple backend, summaries and the CLI."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Event:
    owners: tuple[str, ...]  # calendar labels; more than one when the same event is on several calendars
    title: str
    start: datetime
    end: datetime  # exclusive; an all-day event ends at midnight after its last day
    all_day: bool
    busy: bool  # False when the event is marked "Free"
    uid: str  # shared by copies of one event on different calendars, and by every repeat
    event_id: str = ""  # handle for changing or deleting it (a repeat's id names one occurrence)
    calendar: str = ""  # the calendar's own name, before labels are applied
    location: str | None = None
    notes: str | None = None
    repeats: bool = False
