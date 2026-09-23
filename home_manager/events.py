"""Reads events from Google Calendar (read-only) into a simple Event model."""

from dataclasses import dataclass
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from .config import CalendarSource


@dataclass(frozen=True)
class Event:
    owners: tuple[str, ...]  # calendar labels; more than one when the event is on both
    title: str
    start: datetime
    end: datetime
    all_day: bool
    busy: bool  # False when the event is marked "Free"
    uid: str  # iCalUID; the same meeting on two calendars shares it


def parse_event(item: dict, owner: str, tz: ZoneInfo) -> Event | None:
    """Convert one Calendar API event, or return None if it should be ignored."""
    if item.get("status") == "cancelled":
        return None
    for attendee in item.get("attendees", []):
        if attendee.get("self") and attendee.get("responseStatus") == "declined":
            return None

    all_day = "date" in item["start"]
    return Event(
        owners=(owner,),
        # Calendars shared as "free/busy only" come back without titles.
        title=item.get("summary") or "(busy)",
        start=_parse_time(item["start"], tz),
        end=_parse_time(item["end"], tz),
        all_day=all_day,
        busy=item.get("transparency") != "transparent",
        uid=item.get("iCalUID") or item["id"],
    )


def _parse_time(value: dict, tz: ZoneInfo) -> datetime:
    if "dateTime" in value:
        return datetime.fromisoformat(value["dateTime"]).astimezone(tz)
    return datetime.combine(date.fromisoformat(value["date"]), time(), tz)


def fetch_events(
    service, source: CalendarSource, start: datetime, end: datetime, tz: ZoneInfo
) -> list[Event]:
    """All events on `source` overlapping [start, end), recurring ones expanded."""
    events: list[Event] = []
    page_token = None
    while True:
        response = (
            service.events()
            .list(
                calendarId=source.id,
                timeMin=start.isoformat(),
                timeMax=end.isoformat(),
                singleEvents=True,
                orderBy="startTime",
                timeZone=tz.key,
                pageToken=page_token,
            )
            .execute()
        )
        for item in response.get("items", []):
            event = parse_event(item, source.label, tz)
            if event:
                events.append(event)
        page_token = response.get("nextPageToken")
        if not page_token:
            return events


def list_calendars(service) -> list[dict]:
    """Calendars the signed-in account can read, for finding shared calendar ids."""
    calendars: list[dict] = []
    page_token = None
    while True:
        response = service.calendarList().list(pageToken=page_token).execute()
        calendars.extend(response.get("items", []))
        page_token = response.get("nextPageToken")
        if not page_token:
            return calendars
