from datetime import date, datetime
from zoneinfo import ZoneInfo

from home_manager.events import parse_event
from home_manager.summary import find_conflicts, format_summary, merge_shared

TZ = ZoneInfo("America/New_York")
DAY = date(2026, 9, 22)
LABELS = ["Nick", "Wife"]


def timed(owner, title, start, end, uid=None, **extra):
    item = {
        "id": uid or title,
        "iCalUID": uid or title,
        "summary": title,
        "start": {"dateTime": f"2026-09-22T{start}:00-04:00"},
        "end": {"dateTime": f"2026-09-22T{end}:00-04:00"},
        **extra,
    }
    return parse_event(item, owner, TZ)


def test_parse_skips_cancelled_and_declined():
    assert timed("Nick", "Gone", "09:00", "10:00", status="cancelled") is None
    declined = [{"self": True, "responseStatus": "declined"}]
    assert timed("Nick", "Nope", "09:00", "10:00", attendees=declined) is None


def test_parse_all_day_and_untitled():
    item = {"id": "x", "start": {"date": "2026-09-22"}, "end": {"date": "2026-09-23"}}
    event = parse_event(item, "Wife", TZ)
    assert event.all_day
    assert event.title == "(busy)"
    assert event.start == datetime(2026, 9, 22, tzinfo=TZ)


def test_cross_person_overlap_is_a_conflict():
    events = merge_shared(
        [timed("Nick", "Dentist", "09:00", "10:00"), timed("Wife", "School run", "09:30", "10:30")],
        LABELS,
    )
    [conflict] = find_conflicts(events)
    assert conflict.double_booked == ()
    assert (conflict.start.hour, conflict.start.minute) == (9, 30)
    assert conflict.end.hour == 10


def test_back_to_back_is_not_a_conflict():
    events = [timed("Nick", "A", "09:00", "10:00"), timed("Wife", "B", "10:00", "11:00")]
    assert find_conflicts(events) == []


def test_free_and_all_day_events_never_conflict():
    free = timed("Nick", "Maybe gym", "09:00", "10:00", transparency="transparent")
    all_day = parse_event(
        {"id": "trip", "start": {"date": "2026-09-22"}, "end": {"date": "2026-09-23"}}, "Wife", TZ
    )
    busy = timed("Wife", "Call", "09:00", "10:00")
    assert find_conflicts([free, all_day, busy]) == []


def test_shared_event_is_merged_not_a_conflict():
    events = merge_shared(
        [
            timed("Nick", "Dinner", "18:00", "20:00", uid="dinner-1"),
            timed("Wife", "Dinner", "18:00", "20:00", uid="dinner-1"),
        ],
        LABELS,
    )
    assert len(events) == 1
    assert events[0].owners == ("Nick", "Wife")
    assert find_conflicts(events) == []


def test_shared_event_overlapping_personal_event_is_double_booking():
    events = merge_shared(
        [
            timed("Nick", "Dinner", "18:00", "20:00", uid="dinner-1"),
            timed("Wife", "Dinner", "18:00", "20:00", uid="dinner-1"),
            timed("Nick", "Work call", "19:30", "20:30"),
        ],
        LABELS,
    )
    [conflict] = find_conflicts(events)
    assert conflict.double_booked == ("Nick",)


def test_format_summary():
    events = merge_shared(
        [
            timed("Nick", "Dentist", "09:00", "10:00"),
            timed("Wife", "School run", "09:30", "10:30"),
            timed("Nick", "Dinner", "18:00", "20:00", uid="d"),
            timed("Wife", "Dinner", "18:00", "20:00", uid="d"),
        ],
        LABELS,
    )
    subject, body = format_summary(DAY, LABELS, events, find_conflicts(events), [])
    assert subject == "Today Tue Sep 22: 1 conflict"
    assert "9:30 AM–10:00 AM  Nick's Dentist overlaps Wife's School run" in body
    assert "TOGETHER" in body and "Dinner" in body


def test_format_summary_empty_day_and_warning():
    subject, body = format_summary(DAY, LABELS, [], [], ["Couldn't read Wife's calendar (404): Not Found"])
    assert subject == "Today Tue Sep 22: no conflicts"
    assert "Nothing scheduled" in body
    assert "WARNINGS" in body
    assert "TOGETHER" not in body
