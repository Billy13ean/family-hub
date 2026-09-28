from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from home_manager.events import Event
from home_manager.household import InputError, Repeat, describe, make_repeat, parse_clock, resolve_times

TZ = ZoneInfo("America/New_York")


def at(text):
    return datetime.fromisoformat(text).replace(tzinfo=TZ)


def test_timed_event_defaults_to_one_hour():
    times = resolve_times(TZ, start="2026-10-03 14:00")
    assert (times.start, times.end, times.all_day) == (at("2026-10-03 14:00"), at("2026-10-03 15:00"), False)


def test_end_can_be_just_a_clock_time_and_minutes_work():
    assert resolve_times(TZ, start="2026-10-03 14:00", end="15:30").end == at("2026-10-03 15:30")
    assert resolve_times(TZ, start="2026-10-03T09:00", minutes=90).end == at("2026-10-03 10:30")


def test_bad_input():
    with pytest.raises(InputError):
        resolve_times(TZ, start="2026-10-03 14:00", end="13:00")
    with pytest.raises(InputError):
        resolve_times(TZ, start="next friday")
    with pytest.raises(InputError):
        resolve_times(TZ, start="2026-10-03 14:00", day="2026-10-03")
    with pytest.raises(InputError):
        resolve_times(TZ, end="15:00")
    with pytest.raises(InputError):
        parse_clock("25:00")


def test_all_day_ends_at_midnight_after_last_day():
    times = resolve_times(TZ, day="2026-10-09", through="2026-10-11")
    assert (times.start, times.end, times.all_day) == (at("2026-10-09 00:00"), at("2026-10-12 00:00"), True)


def test_no_time_options_means_no_time_change():
    assert resolve_times(TZ) is None


def test_moving_an_event_keeps_its_length():
    current = Event(("Household",), "Soccer", at("2026-10-03 14:00"), at("2026-10-03 15:30"), False, True, "u")
    assert resolve_times(TZ, start="2026-10-04 10:00", current=current).end == at("2026-10-04 11:30")
    only_end = resolve_times(TZ, end="16:00", current=current)
    assert (only_end.start, only_end.end) == (at("2026-10-03 14:00"), at("2026-10-03 16:00"))


def test_make_repeat():
    assert make_repeat(None, None, None) is None
    assert make_repeat("weekly", "2026-12-15", None) == Repeat("weekly", date(2026, 12, 15))
    assert make_repeat("monthly", None, 6) == Repeat("monthly", None, 6)
    for bad in [(None, "2026-12-15", None), ("weekly", "2026-12-15", 3), ("hourly", None, None), ("daily", None, 0)]:
        with pytest.raises(InputError):
            make_repeat(*bad)


def test_describe():
    event = Event(("Household",), "Soccer game", at("2026-10-03 14:00"), at("2026-10-03 15:00"), False, True, "u",
                  event_id="abc123", location="Field 4")
    assert describe(event) == "Sat Oct 3, 2:00 PM–3:00 PM  Soccer game  @ Field 4  (id abc123)"
    trip = Event(("Household",), "Trip", at("2026-10-09 00:00"), at("2026-10-12 00:00"), True, True, "t",
                 event_id="t@20261009T0000", repeats=True)
    assert describe(trip) == "Fri Oct 9 – Sun Oct 11, all day  Trip  (repeats)  (id t@20261009T0000)"
