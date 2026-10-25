"""The texts `hm jobs loop` sends about jobs: new matches, and the weekly grading check.

They go to one person (`[jobs] to`), never the group chat. The hub's Claude
session can read its chat history, so a text carries only short, checked
fields: the title line from the LinkedIn alert, the checked link, pay, remote,
and the scorer's one-line reason. Never the description from the web page.
"""

from datetime import date, datetime, time, timedelta

from .pending import NEW, Item

MAX_WEEKLY = 15  # jobs listed in the weekly check; the rest are counted


def quiet(now: time, start: time, end: time) -> bool:
    """True inside quiet hours, which may run past midnight (21:00 to 08:00)."""
    if start <= end:
        return start <= now < end
    return now >= start or now < end


def fit(item: Item) -> int | None:
    return (item.data.get("fit") or {}).get("score")


def matches(items: list[Item], min_fit: int) -> list[Item]:
    """Waiting jobs that scored at least min_fit and haven't been texted yet."""
    return [
        i for i in items
        if i.kind == "job" and i.status == NEW and (fit(i) or 0) >= min_fit and "texted" not in i.data
    ]  # fmt: skip


def _facts(item: Item) -> str:
    posting = item.data.get("posting") or {}
    remote = posting.get("remote", "unknown")
    parts = [remote.capitalize() if remote != "unknown" else "", posting.get("pay", ""), f"fit {fit(item)}/10"]
    return " · ".join(p for p in parts if p)


def match_text(items: list[Item]) -> str:
    lines = ["New job match:" if len(items) == 1 else f"{len(items)} new job matches:"]
    for item in items:
        lines.append("")
        lines.append(f"#{item.number} {item.title}")
        lines.append(_facts(item))
        if item.data["fit"].get("reason"):
            lines.append(item.data["fit"]["reason"])
        if (item.data.get("posting") or {}).get("closed"):
            lines.append("The posting may be closed.")
        lines.append(item.data["link"])
    first = items[0].number
    lines += ["", f'Reply "tailor {first}" or "pass {first}" (a reason after pass helps tune the scores).']
    return "\n".join(lines)


def weekly_due(now: datetime, day: int, at: time, last_sent: str) -> bool:
    """True from `at` on `day` until it's been sent that day."""
    return now.weekday() == day and now.time() >= at and last_sent != now.date().isoformat()


def weekly_text(items: list[Item], min_fit: int, today: date) -> str:
    """Every job scored in the last 7 days below min_fit, best first, so misjudged ones stand out."""
    since = (today - timedelta(days=7)).isoformat()
    week = [i for i in items if i.kind == "job" and i.added > since and fit(i) is not None]
    low = sorted((i for i in week if fit(i) < min_fit), key=lambda i: (-fit(i), i.number))
    texted = sum(1 for i in week if fit(i) >= min_fit)
    lines = [
        f"Weekly job grading check: {len(week)} jobs scored this week, "
        f"{texted} at {min_fit}+ (texted), {len(low)} below {min_fit}."
    ]
    if not low:
        return lines[0]
    lines += ["", "Below the bar, best first. Any that should have scored higher?"]
    for item in low[:MAX_WEEKLY]:
        reason = item.data["fit"].get("reason", "")
        lines.append(f"#{item.number} {fit(item)}/10 {item.title}" + (f": {reason}" if reason else ""))
    if len(low) > MAX_WEEKLY:
        lines.append(f"...and {len(low) - MAX_WEEKLY} more, scored lower.")
    lines += ["", 'Reply "tailor N" for any you want after all.']
    return "\n".join(lines)
