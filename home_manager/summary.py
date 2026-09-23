"""Merges shared events, finds conflicts, and formats the morning summary."""

from dataclasses import dataclass, replace
from datetime import date, datetime

from .events import Event


@dataclass(frozen=True)
class Conflict:
    first: Event
    second: Event
    start: datetime
    end: datetime

    @property
    def double_booked(self) -> tuple[str, ...]:
        """People who are in both events. Empty means the two people overlap."""
        return tuple(o for o in self.first.owners if o in self.second.owners)


def merge_shared(events: list[Event], labels: list[str]) -> list[Event]:
    """Collapse the same event appearing on several calendars into one.

    Matched by iCalUID plus start time, since every instance of a recurring
    event shares one iCalUID.
    """
    merged: dict[tuple[str, datetime], Event] = {}
    for event in events:
        key = (event.uid, event.start)
        if key in merged:
            owners = set(merged[key].owners) | set(event.owners)
            merged[key] = replace(
                merged[key], owners=tuple(l for l in labels if l in owners)
            )
        else:
            merged[key] = event
    return sorted(merged.values(), key=lambda e: (not e.all_day, e.start, e.title))


def find_conflicts(events: list[Event]) -> list[Conflict]:
    """Every pair of busy, timed events whose times overlap."""
    timed = sorted((e for e in events if e.busy and not e.all_day), key=lambda e: e.start)
    conflicts = []
    for i, a in enumerate(timed):
        for b in timed[i + 1 :]:
            if b.start >= a.end:
                break
            conflicts.append(Conflict(a, b, b.start, min(a.end, b.end)))
    return conflicts


def format_summary(
    day: date,
    labels: list[str],
    events: list[Event],
    conflicts: list[Conflict],
    warnings: list[str],
) -> tuple[str, str]:
    """Return (subject, plain-text body)."""
    if conflicts:
        count = f"{len(conflicts)} conflict{'s' if len(conflicts) != 1 else ''}"
    else:
        count = "no conflicts"
    subject = f"Today {day:%a %b} {day.day}: {count}"

    lines = [f"{day:%A, %B} {day.day}", ""]

    if warnings:
        lines += ["WARNINGS"] + [f"  ! {w}" for w in warnings] + [""]

    if conflicts:
        lines.append("CONFLICTS")
        for c in conflicts:
            when = _time_range(c.start, c.end)
            if c.double_booked:
                who = " & ".join(c.double_booked)
                lines.append(f"  ! {when}  {who} double-booked: {c.first.title} / {c.second.title}")
            else:
                lines.append(f"  ! {when}  {_describe(c.first)} overlaps {_describe(c.second)}")
        lines.append("")

    sections = [(label, [e for e in events if e.owners == (label,)]) for label in labels]
    sections.append(("Together", [e for e in events if len(e.owners) > 1]))
    for heading, section_events in sections:
        if heading == "Together" and not section_events:
            continue
        lines.append(heading.upper())
        if not section_events:
            lines.append("  Nothing scheduled")
        for e in section_events:
            together = f"  ({' & '.join(e.owners)})" if heading == "Together" and len(e.owners) < len(labels) else ""
            lines.append(f"  {_when(e, day):<19} {e.title}{together}")
        lines.append("")

    return subject, "\n".join(lines).rstrip() + "\n"


def _describe(event: Event) -> str:
    return f"{' & '.join(event.owners)}'s {event.title}"


def _when(event: Event, day: date) -> str:
    if event.all_day:
        return "All day"
    start = _clock(event.start) if event.start.date() == day else f"{event.start:%a} {_clock(event.start)}"
    end = _clock(event.end) if event.end.date() == day else f"{event.end:%a} {_clock(event.end)}"
    return f"{start}–{end}"


def _time_range(start: datetime, end: datetime) -> str:
    return f"{_clock(start)}–{_clock(end)}"


def _clock(t: datetime) -> str:
    return f"{t:%I:%M %p}".lstrip("0")
