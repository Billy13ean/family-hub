from datetime import date, time

import pytest

from home_manager import reminders as rm
from home_manager.reminders import Reminder

TODAY = date(2026, 9, 28)


def item(title, rid, **kw):
    return Reminder(rid, title, kw.pop("list", "Grocery"), **kw)


def test_short_ids_grow_until_unique():
    items = [item("a", "ABCD1111-X"), item("b", "ABCD2222-Y"), item("c", "FFFF0000")]
    assert rm.short_ids(items) == {"ABCD1111-X": "abcd1", "ABCD2222-Y": "abcd2", "FFFF0000": "ffff0"}


def test_find_by_title_piece_or_id():
    items = [item("whole milk", "AAAA1"), item("oat milk", "BBBB2"), item("eggs", "CCCC3")]
    assert rm.find(items, "eggs", "item").id == "CCCC3"
    assert rm.find(items, "OAT", "item").id == "BBBB2"
    assert rm.find(items, "#bbbb", "item").id == "BBBB2"
    with pytest.raises(rm.ReminderError, match="more than one"):
        rm.find(items, "milk", "item")
    with pytest.raises(rm.ReminderError, match="No item"):
        rm.find(items, "cheese", "item")


def test_monthly_repeat_keeps_its_day():
    rent = item("Rent", "R", list="Bills", due=date(2027, 1, 31), repeat="monthly")
    feb = rm.next_due(rent)
    assert feb == date(2027, 2, 28)
    # Once it has slipped to the 28th, an anchor from the Reminders rule keeps it on the 31st.
    assert rm.next_due(item("Rent", "R", due=feb, repeat="monthly", anchor_day=31)) == date(2027, 3, 31)


def test_other_repeats_and_custom():
    assert rm.next_due(item("Trash", "T", due=TODAY, repeat="weekly", interval=2)) == date(2026, 10, 12)
    assert rm.next_due(item("Insurance", "I", due=TODAY, repeat="yearly")) == date(2027, 9, 28)
    assert rm.next_due(item("Odd", "O", due=TODAY, repeat="custom")) is None
    assert rm.next_due(item("Milk", "M")) is None


def test_describe_and_format_list():
    items = [
        item("milk", "AAAA1"),
        item("Call plumber (Nick)", "BBBB2", list="To-Do", due=date(2026, 9, 30), at=time(9, 30)),
        item("Electric", "CCCC3", list="Bills", due=date(2026, 9, 25), repeat="monthly", notes="$120, autopay off"),
    ]
    assert rm.describe(items[1], TODAY) == "Call plumber (Nick) (due Wed Sep 30 9:30 AM, in 2 days)"
    assert rm.describe(items[2], TODAY, "cccc") == "Electric (due OVERDUE since Fri Sep 25) [repeats monthly] - $120, autopay off #cccc"
    text = rm.format_list("Grocery", items, TODAY)
    assert text.splitlines()[0] == "GROCERY (3)"
    assert text.splitlines()[1].startswith("  Electric")  # dated items first
    assert rm.format_list("Grocery", [], TODAY) == "Grocery: nothing on the list."


def test_digest_lines():
    items = [
        item("Electric", "A", list="Bills", due=date(2026, 10, 1)),
        item("Insurance", "B", list="Bills", due=date(2026, 12, 1)),
        item("Return library books", "C", list="To-Do", due=TODAY),
        item("Paint fence", "D", list="To-Do", due=date(2026, 10, 5)),
    ]
    lines = rm.digest_lines(items, TODAY, "bills", 3)
    assert lines == [
        "BILLS DUE", "  Electric (due Thu Oct 1, in 3 days)", "",
        "DUE TODAY", "  To-Do: Return library books (due today)", "",
    ]
