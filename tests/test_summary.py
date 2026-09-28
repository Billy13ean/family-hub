from datetime import date, datetime
from zoneinfo import ZoneInfo

from home_manager.events import Event
from home_manager.summary import find_conflicts, format_summary, merge_shared

TZ = ZoneInfo("America/New_York")
DAY = date(2026, 9, 22)
LABELS = ["Nick", "Wife"]


def timed(owner, title, start, end, uid=None, busy=True):
    at = lambda hhmm: datetime.fromisoformat(f"2026-09-22T{hhmm}").replace(tzinfo=TZ)
    return Event((owner,), title, at(start), at(end), False, busy, uid or title)


def all_day(owner, title):
    return Event((owner,), title, datetime(2026, 9, 22, tzinfo=TZ), datetime(2026, 9, 23, tzinfo=TZ), True, True, title)


def test_cross_person_overlap_is_a_conflict():
    events = merge_shared([timed("Nick", "Dentist", "09:00", "10:00"), timed("Wife", "School run", "09:30", "10:30")], LABELS)
    [conflict] = find_conflicts(events)
    assert conflict.double_booked == ()
    assert (conflict.start.hour, conflict.start.minute) == (9, 30)
    assert conflict.end.hour == 10


def test_back_to_back_is_not_a_conflict():
    assert find_conflicts([timed("Nick", "A", "09:00", "10:00"), timed("Wife", "B", "10:00", "11:00")]) == []


def test_free_and_all_day_events_never_conflict():
    free = timed("Nick", "Maybe gym", "09:00", "10:00", busy=False)
    busy = timed("Wife", "Call", "09:00", "10:00")
    assert find_conflicts([free, all_day("Wife", "Trip"), busy]) == []


def test_shared_event_is_merged_not_a_conflict():
    events = merge_shared(
        [timed("Nick", "Dinner", "18:00", "20:00", uid="dinner-1"), timed("Wife", "Dinner", "18:00", "20:00", uid="dinner-1")],
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
    subject, body = format_summary(DAY, LABELS, events, find_conflicts(events), [], ["BILLS DUE", "  Water", ""])
    assert subject == "Today Tue Sep 22: 1 conflict"
    assert "9:30 AM–10:00 AM  Nick's Dentist overlaps Wife's School run" in body
    assert "TOGETHER" in body and "Dinner" in body
    assert body.index("CONFLICTS") < body.index("BILLS DUE") < body.index("NICK")


def test_format_summary_empty_day_and_warning():
    subject, body = format_summary(DAY, LABELS, [], [], ["Couldn't read Reminders"])
    assert subject == "Today Tue Sep 22: no conflicts"
    assert "Nothing on the calendar." in body and "WARNINGS" in body
    assert "TOGETHER" not in body
