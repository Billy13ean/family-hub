"""Runs the hub's commands end to end against the in-memory FakeStore."""

import sys
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest
from fake_apple import FakeStore

import home_manager.__main__ as cli

TZ = ZoneInfo("America/New_York")


def at(text):
    return datetime.fromisoformat(text).replace(tzinfo=TZ)


@pytest.fixture
def run(tmp_path, monkeypatch, capsys):
    (tmp_path / "config.toml").write_text(
        'timezone = "America/New_York"\n[calendars.labels]\n"Home" = "Nick"\n[digest]\nto = ["+15551234567"]\n'
    )
    monkeypatch.setenv("HOME_MANAGER_CONFIG_DIR", str(tmp_path))
    store = FakeStore(TZ)
    monkeypatch.setattr(cli, "backend", lambda config: store)
    monkeypatch.setattr(cli, "_today", lambda config: date(2026, 9, 28))

    def run(*argv, fails=False):
        monkeypatch.setattr(sys, "argv", ["hm", *argv])
        if fails:
            with pytest.raises(SystemExit) as exit_info:
                cli.main()
            return str(exit_info.value)
        cli.main()
        return capsys.readouterr().out

    run.store = store
    return run


def test_add_reports_overlaps_then_update_and_delete(run):
    run.store.seed_event("Home", "Dentist", at("2026-10-03 14:30"), at("2026-10-03 15:30"))

    out = run("cal", "add", "Soccer", "game", "--start", "2026-10-03 14:00", "--location", "Field 4")
    assert "Added: Sat Oct 3, 2:00 PM–3:00 PM  Soccer game  @ Field 4  (id e2)" in out
    assert "Heads up, overlap on Sat Oct 3: 2:30 PM–3:00 PM  Household's Soccer game overlaps Nick's Dentist" in out

    out = run("cal", "list", "--date", "2026-10-03")
    assert "Soccer game  [Household]  (id e2)" in out and "Dentist  [Nick]" in out and "CONFLICTS" in out
    assert "(id e1)" not in out  # personal events don't get ids: the hub can't change them

    out = run("cal", "update", "e2", "--start", "2026-10-03 16:00")
    assert "4:00 PM–5:00 PM" in out and "No overlaps" in out

    assert "Soccer game" in run("cal", "find", "soccer")
    assert "Deleted: " in run("cal", "delete", "e2")
    assert [e.title for e in run.store.events_list] == ["Dentist"]


def test_personal_events_cannot_be_changed(run):
    run.store.seed_event("Home", "Dentist", at("2026-10-03 14:30"), at("2026-10-03 15:30"))
    assert "which the hub doesn't change" in run("cal", "delete", "e1", fails=True)
    assert "which the hub doesn't change" in run("cal", "update", "e1", "--title", "x", fails=True)


def test_repeating_and_all_day_events(run):
    out = run("cal", "add", "Piano", "--start", "2026-10-06 16:30", "--minutes", "45", "--repeat", "weekly", "--until", "2026-12-15")
    assert "4:30 PM–5:15 PM" in out
    assert run.store.last_repeat.frequency == "weekly" and run.store.last_repeat.until == date(2026, 12, 15)
    run("cal", "update", "e1", "--start", "2026-10-06 17:00", "--future")
    assert run.store.last_future is True

    out = run("cal", "add", "Beach", "trip", "--date", "2026-10-09", "--through", "2026-10-11")
    assert "Fri Oct 9 – Sun Oct 11, all day  Beach trip" in out


def test_grocery_list(run):
    out = run("list", "add", "Grocery", "milk", "eggs", "rye bread", "Milk")
    assert out.count("Added to Grocery") == 3 and "Already on Grocery: Milk." in out
    run("list", "done", "Grocery", "eggs")
    run("list", "remove", "Grocery", "rye")
    out = run("list", "show", "Grocery")
    assert out.startswith("GROCERY (1)\n  milk #")
    assert "eggs" in run("list", "show", "Grocery", "--done")
    run("list", "undo", "Grocery", "eggs")
    assert "Ticked off 2 items on Grocery." in run("list", "clear", "Grocery")
    assert "more than one" not in run("list", "names")
    assert "No open item on Grocery matching 'cheese'" in run("list", "done", "Grocery", "cheese", fails=True)


def test_bills_move_to_next_due_date_when_paid(run):
    run("list", "add", "Bills", "Electric", "--due", "2026-10-01", "--repeat", "monthly", "--notes", "about $120")
    run("list", "add", "Bills", "Car registration", "--due", "2026-10-15")
    assert "Next due Sun Nov 1." in run("list", "done", "Bills", "electric")
    assert "Done: Car registration." in run("list", "done", "Bills", "car")
    [electric] = run.store.open_reminders()
    assert electric.due == date(2026, 11, 1) and not electric.completed
    assert "--at needs --due" in run("list", "add", "To-Do", "Call", "--at", "09:00", fails=True)
    assert "Left 1 repeating item" in run("list", "clear", "Bills")


def test_list_edit(run):
    run("list", "add", "To-Do", "Call plumber")
    out = run("list", "edit", "To-Do", "plumber", "--due", "2026-09-30", "--at", "09:30", "--title", "Call", "plumber", "(Nick)")
    assert out.strip() == "Updated: Call plumber (Nick) (due Wed Sep 30 9:30 AM, in 2 days)"
    assert "(due" not in run("list", "edit", "To-Do", "plumber", "--no-due")


def test_summary_and_due(run):
    run.store.seed_event("Household", "Soccer", at("2026-09-28 09:00"), at("2026-09-28 10:00"))
    run("list", "add", "Bills", "Water", "--due", "2026-09-29")
    run("list", "add", "To-Do", "Return library books", "--due", "2026-09-28")
    out = run("summary")
    assert out.startswith("Today Mon Sep 28: no conflicts")
    assert "BILLS DUE\n  Water (due tomorrow)" in out
    assert "DUE TODAY\n  To-Do: Return library books (due today)" in out
    assert "HOUSEHOLD\n  9:00 AM–10:00 AM    Soccer" in out
    assert "Bills: Water (due tomorrow)" in run("list", "due", "--days", "2")


def test_setup_reports_whats_missing(run):
    out = run("setup")
    assert "Calendars: access granted" in out
    assert "Household / iCloud / can edit  <- the hub changes this one" in out
    assert "Everything the hub needs is in place." in out
    run.store.list_names.remove("Bills")
    assert "No Reminders list named 'Bills'" in run("setup")
