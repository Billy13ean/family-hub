"""Reminders lists (grocery, to-dos, bills): matching, formatting and due dates. No Apple calls here."""

import calendar
import re
from dataclasses import dataclass
from datetime import date, time, timedelta

# Passed to update_reminder for "leave this field as it is".
KEEP = object()
SIMPLE_REPEATS = ("daily", "weekly", "monthly", "yearly")


class ReminderError(ValueError):
    """A request about a list that can't be carried out, such as an unknown item."""


@dataclass(frozen=True)
class Reminder:
    id: str
    title: str
    list: str
    due: date | None = None
    at: time | None = None  # due time, if it has one
    notes: str | None = None
    # daily/weekly/monthly/yearly, or "custom" for rules made in the Reminders
    # app that this tool doesn't try to advance (every 2nd Tuesday, and so on).
    repeat: str | None = None
    interval: int = 1
    anchor_day: int | None = None  # day of month a monthly repeat sticks to
    completed: bool = False
    completed_on: date | None = None


def clean(text: str) -> str:
    return " ".join(text.split())


def short_ids(items: list[Reminder]) -> dict[str, str]:
    """Short handles like 'a1f3', long enough to be unique within `items`."""
    keys = {r.id: re.sub(r"[^0-9a-z]", "", r.id.lower()) or r.id for r in items}
    for length in range(4, 41):
        short = {rid: key[:length] for rid, key in keys.items()}
        if len(set(short.values())) == len(short):
            return short
    return keys


def find(items: list[Reminder], ref: str, what: str) -> Reminder:
    """Match '#a1f3' by short id, then exact title, then a unique piece of a title."""
    ref = clean(ref)
    if ref.startswith("#"):
        wanted = ref[1:].lower()
        matches = [r for r, short in _with_short(items) if short.startswith(wanted) or r.id.lower() == wanted]
        if len(matches) == 1:
            return matches[0]
        raise ReminderError(f"No {what} with id {ref}.")
    lowered = ref.lower()
    exact = [r for r in items if r.title.lower() == lowered]
    if len(exact) == 1:
        return exact[0]
    partial = [r for r in items if lowered in r.title.lower()]
    if len(partial) == 1:
        return partial[0]
    if not partial and not exact:
        raise ReminderError(f"No {what} matching {ref!r}.")
    choices = ", ".join(f"{r.title} #{short}" for r, short in _with_short(exact or partial))
    raise ReminderError(f"{ref!r} matches more than one {what}: {choices}. Use the #id.")


def _with_short(items: list[Reminder]) -> list[tuple[Reminder, str]]:
    short = short_ids(items)
    return [(r, short[r.id]) for r in items]


def due_label(due: date, today: date, at: time | None = None) -> str:
    days = (due - today).days
    clock = f" {at.strftime('%I:%M %p').lstrip('0')}" if at else ""
    if days < 0:
        return f"OVERDUE since {due:%a %b} {due.day}"
    if days == 0:
        return f"today{clock}"
    if days == 1:
        return f"tomorrow{clock}"
    if days < 7:
        return f"{due:%a %b} {due.day}{clock}, in {days} days"
    return f"{due:%a %b} {due.day}{clock}"


def describe(r: Reminder, today: date, short: str | None = None) -> str:
    parts = [r.title]
    if r.completed:
        parts.append(f"(done {r.completed_on:%a %b} {r.completed_on.day})" if r.completed_on else "(done)")
    elif r.due:
        parts.append(f"(due {due_label(r.due, today, r.at)})")
    if r.repeat:
        every = r.repeat if r.interval == 1 else f"every {r.interval} {_UNITS[r.repeat]}"
        parts.append(f"[repeats {every}]" if r.repeat != "custom" else "[repeats]")
    if r.notes:
        parts.append(f"- {clean(r.notes)}")
    if short:
        parts.append(f"#{short}")
    return " ".join(parts)


_UNITS = {"daily": "days", "weekly": "weeks", "monthly": "months", "yearly": "years", "custom": ""}


def ordered(items: list[Reminder]) -> list[Reminder]:
    """Dated items first, soonest first; then the rest in their original order."""
    indexed = list(enumerate(items))
    indexed.sort(key=lambda pair: (pair[1].due is None, pair[1].due or date.min, pair[1].at or time(), pair[0]))
    return [r for _, r in indexed]


def format_list(name: str, items: list[Reminder], today: date) -> str:
    open_items = [r for r in items if not r.completed]
    done = [r for r in items if r.completed]
    if not items:
        return f"{name}: nothing on the list."
    short = short_ids(items)
    lines = [f"{name.upper()} ({len(open_items)})"]
    lines += [f"  {describe(r, today, short[r.id])}" for r in ordered(open_items)]
    if done:
        lines.append("  Recently done:")
        lines += [f"    {describe(r, today, short[r.id])}" for r in sorted(done, key=lambda r: r.completed_on or date.min, reverse=True)]
    return "\n".join(lines)


def add_months(day: date, months: int, anchor_day: int) -> date:
    """Move by whole months, keeping the anchor day where the month allows (Jan 31 -> Feb 28 -> Mar 31)."""
    index = day.month - 1 + months
    year, month = day.year + index // 12, index % 12 + 1
    return date(year, month, min(anchor_day, calendar.monthrange(year, month)[1]))


def next_due(r: Reminder) -> date | None:
    """The following due date of a simple repeating reminder, or None if this tool shouldn't advance it."""
    if not r.due or r.repeat not in SIMPLE_REPEATS:
        return None
    step = max(r.interval, 1)
    if r.repeat == "daily":
        return r.due + timedelta(days=step)
    if r.repeat == "weekly":
        return r.due + timedelta(weeks=step)
    months = step if r.repeat == "monthly" else 12 * step
    anchor = r.anchor_day if r.anchor_day and r.anchor_day > 0 else r.due.day
    return add_months(r.due, months, anchor)


def due_soon(items: list[Reminder], today: date, days: int) -> list[Reminder]:
    """Open items due within `days` days, plus overdue ones, soonest first."""
    horizon = today + timedelta(days=days)
    return ordered([r for r in items if not r.completed and r.due and r.due <= horizon])


def digest_lines(items: list[Reminder], today: date, bill_list: str, bill_days: int) -> list[str]:
    """Morning digest sections: bills due in the next few days, other things due today or overdue."""
    lines: list[str] = []
    bills = [r for r in items if r.list.lower() == bill_list.lower()]
    others = [r for r in items if r.list.lower() != bill_list.lower()]
    soon = due_soon(bills, today, bill_days)
    if soon:
        lines += ["BILLS DUE"] + [f"  {describe(r, today)}" for r in soon] + [""]
    today_items = due_soon(others, today, 0)
    if today_items:
        lines += ["DUE TODAY"] + [f"  {r.list}: {describe(r, today)}" for r in today_items] + [""]
    return lines
