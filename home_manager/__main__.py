"""Command line entry point: `uv run python -m home_manager <command>` (or `hub/hm <command>`).

The family hub's Claude session drives these commands by text message, so the
output is short plain text meant to be read by Claude.
"""

import argparse
import sys
import time as systime
from datetime import date, datetime, time, timedelta

from . import household as hh
from . import messages
from . import reminders as rm
from .apple import AppleError, AppleStore
from .config import Config, ConfigError, get_paths, load_config
from .summary import conflict_line, find_conflicts, format_summary, merge_shared, when_on

# --- Shared helpers -----------------------------------------------------------


def backend(config: Config) -> AppleStore:
    """The Apple Calendar and Reminders store. Tests replace this with a fake."""
    return AppleStore(config.timezone)


def _config() -> Config:
    return load_config(get_paths())


def _today(config: Config) -> date:
    return datetime.now(config.timezone).date()


def _bounds(first: date, days: int, config: Config) -> tuple[datetime, datetime]:
    tz = config.timezone
    return datetime.combine(first, time(), tz), datetime.combine(first + timedelta(days=days), time(), tz)


def _read_calendars(store, config: Config, start: datetime, end: datetime):
    """Events from every calendar the hub reads, with labels applied and shared copies merged."""
    events = store.events(start, end, config.calendars, config.labels)
    labels = sorted({o for e in events for o in e.owners}, key=lambda l: (l != config.label(config.household_calendar), l))
    return merge_shared(events, labels), labels


def _is_household(event, config: Config) -> bool:
    return event.calendar.casefold() == config.household_calendar.casefold()


# --- Setup and the morning digest ---------------------------------------------


def cmd_now(args) -> None:
    config = _config()
    now = datetime.now(config.timezone)
    clock = f"{now:%I:%M %p}".lstrip("0")
    print(f"{now:%A, %B} {now.day}, {now.year}, {clock} {now:%Z} ({config.timezone.key})")


def cmd_setup(args) -> None:
    config = _config()
    store = backend(config)
    for what, granted in store.request_access().items():
        print(f"{what}: {'access granted' if granted else 'NO ACCESS - allow Terminal in System Settings > Privacy & Security > ' + what}")
    print()
    _print_calendars(store, config)
    print()
    problems = []
    cal_names = {c.name.casefold(): c for c in store.calendars()}
    household = cal_names.get(config.household_calendar.casefold())
    if not household:
        problems.append(f"No calendar named {config.household_calendar!r} yet. Share it with this Apple Account and accept the invitation.")
    elif not household.writable:
        problems.append(f"{config.household_calendar} is read-only. Share it again with editing allowed.")
    if config.bill_list.casefold() not in {l.name.casefold() for l in store.reminder_lists()}:
        problems.append(f"No Reminders list named {config.bill_list!r}. Bills won't appear in the digest until it's shared.")
    if not config.digest_to:
        problems.append("No [digest] to = [...] in config.toml, so the morning digest has nobody to go to.")
    print("\n".join(f"! {p}" for p in problems) or "Everything the hub needs is in place.")


def _print_calendars(store, config: Config) -> None:
    print("CALENDARS (name / account / access)")
    for c in store.calendars():
        role = "  <- the hub changes this one" if c.name.casefold() == config.household_calendar.casefold() else ""
        print(f"  {c.name} / {c.account} / {'can edit' if c.writable else 'read only'}{role}")
    print("REMINDERS LISTS")
    for l in store.reminder_lists():
        print(f"  {l.name} / {l.account} / {'can edit' if l.writable else 'read only'}")


def cmd_calendars(args) -> None:
    config = _config()
    _print_calendars(backend(config), config)


def cmd_chats(args) -> None:
    chats = messages.family_chats(messages.allowlist())
    if not chats:
        print("No chats with allowlisted family members yet.")
    for handle, guid in chats:
        print(f"{handle}\tchat_id {guid}")


def build_digest(config: Config, day: date) -> str:
    store = backend(config)
    start, end = _bounds(day, 1, config)
    events, labels = _read_calendars(store, config, start, end)
    warnings = []
    try:
        extra = rm.digest_lines(store.open_reminders(), day, config.bill_list, config.bill_days)
    except AppleError as e:
        extra, warnings = [], [f"Couldn't read Reminders: {e}"]
    headline, body = format_summary(day, labels, events, find_conflicts(events), warnings, extra)
    return f"{headline}\n\n{body}".rstrip()


def cmd_summary(args) -> None:
    config = _config()
    day = hh.parse_day(args.date) if args.date else _today(config)
    text = build_digest(config, day)
    if args.send:
        messages.send(text, list(config.digest_to))
        print(f"Sent the digest to {', '.join(config.digest_to)}.")
    else:
        print(text)


def cmd_digest_loop(args) -> None:
    """Send the digest every morning. start-hub.command runs this in the background."""
    while True:
        config = _config()  # re-read, so config changes apply without a restart
        now = datetime.now(config.timezone)
        target = datetime.combine(now.date(), config.digest_time, config.timezone)
        if target <= now:
            target += timedelta(days=1)
        print(f"{now:%Y-%m-%d %H:%M} next digest at {target:%a %H:%M}", flush=True)
        # Short sleeps, checked against the clock, survive the Mac sleeping in between.
        while datetime.now(config.timezone) < target:
            systime.sleep(min(60, max(1, (target - datetime.now(config.timezone)).total_seconds())))
        try:
            config = _config()
            messages.send(build_digest(config, target.date()), list(config.digest_to))
            print(f"{datetime.now(config.timezone):%Y-%m-%d %H:%M} digest sent", flush=True)
        except Exception as e:  # keep the loop alive; the next morning may work
            print(f"{datetime.now(config.timezone):%Y-%m-%d %H:%M} digest failed: {e}", flush=True)


# --- Calendar -----------------------------------------------------------------


def cmd_cal_list(args) -> None:
    config = _config()
    first = hh.parse_day(args.date) if args.date else _today(config)
    start, end = _bounds(first, args.days, config)
    events, _ = _read_calendars(backend(config), config, start, end)

    out = []
    conflicts = find_conflicts(events)
    if conflicts:
        out.append("CONFLICTS")
        out += [f"  ! {c.start:%a %b} {c.start.day}  {conflict_line(c)}" for c in conflicts]
        out.append("")

    for offset in range(args.days):
        day = first + timedelta(days=offset)
        day_start, day_end = _bounds(day, 1, config)
        todays = [e for e in events if e.start < day_end and e.end > day_start]
        out.append(f"{day:%a %b} {day.day}")
        if not todays:
            out.append("  Nothing scheduled")
        for e in todays:
            free = " (free)" if not e.busy else ""
            ident = f"  (id {e.event_id})" if _is_household(e, config) else ""
            out.append(f"  {when_on(e, day):<19} {e.title}{free}  [{' & '.join(e.owners)}]{ident}")
    print("\n".join(out))


def cmd_cal_find(args) -> None:
    config = _config()
    query = " ".join(args.query).casefold()
    now = datetime.now(config.timezone)
    events = backend(config).events(
        now - timedelta(days=args.past), now + timedelta(days=args.days), (config.household_calendar,), config.labels
    )
    found = [e for e in sorted(events, key=lambda e: e.start) if query in e.title.casefold()]
    if not found:
        print(f"No {config.household_calendar} events matching {query!r} from {args.past} days ago to {args.days} days ahead.")
    for e in found:
        print(hh.describe(e))


def _report_overlaps(store, config: Config, event) -> None:
    """After adding or moving an event, say what it overlaps (first occurrence only)."""
    if event.all_day:
        return  # all-day events never count as conflicts
    start, end = _bounds(event.start.date(), 1, config)
    events, _ = _read_calendars(store, config, start, max(end, event.end))
    clashes = [c for c in find_conflicts(events) if event.uid in (c.first.uid, c.second.uid)]
    for c in clashes:
        print(f"Heads up, overlap on {c.start:%a %b} {c.start.day}: {conflict_line(c)}")
    if not clashes:
        print("No overlaps with anyone's calendar" + (" on the first date." if event.repeats else "."))


def cmd_cal_add(args) -> None:
    config = _config()
    tz = config.timezone
    times = hh.resolve_times(tz, start=args.start, end=args.end, minutes=args.minutes, day=args.date, through=args.through)
    if not times:
        raise hh.InputError("Give --start for a timed event or --date for an all-day one.")
    repeat = hh.make_repeat(args.repeat, args.until, args.count)
    store = backend(config)
    event = store.add_event(config.household_calendar, " ".join(args.title), times,
                            location=args.location, notes=args.notes, repeat=repeat)
    print("Added: " + hh.describe(event))
    _report_overlaps(store, config, event)


def cmd_cal_update(args) -> None:
    config = _config()
    store = backend(config)
    current = store.get_event(args.event_id)
    times = hh.resolve_times(config.timezone, start=args.start, end=args.end, minutes=args.minutes,
                             day=args.date, through=args.through, current=current)
    title = " ".join(args.title) if args.title else None
    if not (title or times or args.location is not None or args.notes is not None):
        raise hh.InputError("Nothing to change. Give --title, --start, --end, --minutes, --date, --location or --notes.")
    event = store.update_event(args.event_id, config.household_calendar, title=title, times=times,
                               location=args.location, notes=args.notes, future=args.future)
    scope = " (this and later ones)" if args.future and event.repeats else ""
    print(f"Updated{scope}: " + hh.describe(event))
    if times:
        _report_overlaps(store, config, event)


def cmd_cal_delete(args) -> None:
    config = _config()
    event = backend(config).delete_event(args.event_id, config.household_calendar, future=args.future)
    scope = " this and every later one" if args.future and event.repeats else ""
    print(f"Deleted{scope}: " + hh.describe(event))


# --- Reminders lists ----------------------------------------------------------


def _due_options(args) -> tuple:
    due = hh.parse_day(args.due) if getattr(args, "due", None) else None
    at = hh.parse_clock(args.at) if getattr(args, "at", None) else None
    if at and not due:
        raise hh.InputError("--at needs --due.")
    return due, at


def cmd_list_names(args) -> None:
    config = _config()
    store = backend(config)
    for l in store.reminder_lists():
        count = len(store.reminders(l.name))
        print(f"{l.name} ({count} open){'' if l.writable else ' read only'}")


def cmd_list_show(args) -> None:
    config = _config()
    items = backend(config).reminders(args.name, completed_days=7 if args.done else 0)
    print(rm.format_list(args.name, items, _today(config)))


def cmd_list_add(args) -> None:
    config = _config()
    due, at = _due_options(args)
    if args.repeat and not due:
        raise hh.InputError("--repeat needs --due.")
    store = backend(config)
    existing = {r.title.casefold() for r in store.reminders(args.name)}
    added, already = [], []
    for raw in args.items:
        title = rm.clean(raw)
        if not title:
            continue
        if title.casefold() in existing:
            already.append(title)
            continue
        added.append(store.add_reminder(args.name, title, due=due, at=at, notes=args.notes, repeat=args.repeat))
        existing.add(title.casefold())
    today = _today(config)
    for r in added:
        print(f"Added to {r.list}: {rm.describe(r, today)}")
    if already:
        print(f"Already on {args.name}: {', '.join(already)}.")


def cmd_list_done(args) -> None:
    config = _config()
    store = backend(config)
    items = store.reminders(args.name)
    today = _today(config)
    for ref in args.items:
        r = rm.find(items, ref, f"open item on {args.name}")
        upcoming = rm.next_due(r)
        if upcoming:
            # Repeating items (bills) move on to their next due date.
            store.update_reminder(r.id, due=upcoming)
            print(f"Done: {r.title}. Next due {rm.due_label(upcoming, today, r.at)}.")
        else:
            store.update_reminder(r.id, completed=True)
            print(f"Done: {r.title}.")
        items = [i for i in items if i.id != r.id]


def cmd_list_undo(args) -> None:
    config = _config()
    store = backend(config)
    done = [r for r in store.reminders(args.name, completed_days=30) if r.completed]
    for ref in args.items:
        r = rm.find(done, ref, f"recently finished item on {args.name}")
        store.update_reminder(r.id, completed=False)
        print(f"Back on {args.name}: {r.title}.")


def cmd_list_remove(args) -> None:
    config = _config()
    store = backend(config)
    items = store.reminders(args.name, completed_days=7)
    for ref in args.items:
        r = rm.find(items, ref, f"item on {args.name}")
        store.delete_reminder(r.id)
        items = [i for i in items if i.id != r.id]
        print(f"Removed from {args.name}: {r.title}.")


def cmd_list_edit(args) -> None:
    config = _config()
    store = backend(config)
    r = rm.find(store.reminders(args.name), args.item, f"open item on {args.name}")
    changes: dict = {}
    if args.title:
        changes["title"] = rm.clean(" ".join(args.title))
    if args.notes is not None:
        changes["notes"] = args.notes
    if args.no_due:
        changes.update(due=None, at=None)
    elif args.due or args.at:
        due = hh.parse_day(args.due) if args.due else r.due
        if not due:
            raise hh.InputError("--at needs --due.")
        changes.update(due=due, at=hh.parse_clock(args.at) if args.at else rm.KEEP)
    if args.no_repeat:
        changes["repeat"] = None
    elif args.repeat:
        if not (changes.get("due") or r.due):
            raise hh.InputError("--repeat needs a due date.")
        changes["repeat"] = args.repeat
    if not changes:
        raise hh.InputError("Nothing to change. Give --title, --due, --at, --no-due, --notes, --repeat or --no-repeat.")
    updated = store.update_reminder(r.id, **changes)
    print("Updated: " + rm.describe(updated, _today(config)))


def cmd_list_clear(args) -> None:
    """Tick off everything on a list, like after a shopping trip. Repeating items are left alone."""
    config = _config()
    store = backend(config)
    items = store.reminders(args.name)
    cleared = [r for r in items if not r.repeat]
    for r in cleared:
        store.update_reminder(r.id, completed=True)
    kept = len(items) - len(cleared)
    note = f" Left {kept} repeating item{'s' if kept != 1 else ''}." if kept else ""
    print(f"Ticked off {len(cleared)} item{'s' if len(cleared) != 1 else ''} on {args.name}.{note}")


def cmd_list_due(args) -> None:
    config = _config()
    today = _today(config)
    soon = rm.due_soon(backend(config).open_reminders(), today, args.days)
    if not soon:
        print(f"Nothing due in the next {args.days} days.")
    for r in soon:
        print(f"{r.list}: {rm.describe(r, today)}")


# --- Argument parsing ---------------------------------------------------------


def _add_time_options(p, for_update: bool = False) -> None:
    p.add_argument("--start", help="YYYY-MM-DD HH:MM, local time (24-hour)")
    p.add_argument("--end", help="YYYY-MM-DD HH:MM, or just HH:MM on the start day")
    p.add_argument("--minutes", type=int, help="length instead of --end" + ("" if for_update else " (default 60)"))
    p.add_argument("--date", help="YYYY-MM-DD for an all-day event")
    p.add_argument("--through", help="YYYY-MM-DD last day of a multi-day all-day event")
    p.add_argument("--location", help="'' to clear" if for_update else None)
    p.add_argument("--notes", help="'' to clear" if for_update else "shown on the event")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hm", description="Household calendar and Reminders lists.")
    commands = parser.add_subparsers(required=True, metavar="command")

    commands.add_parser("now", help="current local date and time").set_defaults(func=cmd_now)
    commands.add_parser("setup", help="ask for Calendar and Reminders access and check the setup").set_defaults(func=cmd_setup)
    commands.add_parser("calendars", help="calendars and Reminders lists this account can see").set_defaults(func=cmd_calendars)
    commands.add_parser("chats", help="iMessage chat ids of allowlisted family members").set_defaults(func=cmd_chats)

    p = commands.add_parser("summary", help="a day at a glance: conflicts, events, bills and things due")
    p.add_argument("--date", help="YYYY-MM-DD instead of today")
    p.add_argument("--send", action="store_true", help="send it by iMessage to [digest] to")
    p.set_defaults(func=cmd_summary)
    commands.add_parser("digest-loop", help="send the digest every morning (started by start-hub.command)").set_defaults(func=cmd_digest_loop)

    # Calendar
    cal = commands.add_parser("cal", help="read calendars, change the Household one").add_subparsers(required=True, metavar="action")
    p = cal.add_parser("list", help="events on every calendar, with conflicts")
    p.add_argument("--date", help="first day, YYYY-MM-DD (default today)")
    p.add_argument("--days", type=int, default=1)
    p.set_defaults(func=cmd_cal_list)

    p = cal.add_parser("find", help="search Household events by title, to get their ids")
    p.add_argument("query", nargs="+")
    p.add_argument("--days", type=int, default=90, help="days ahead to search (default 90)")
    p.add_argument("--past", type=int, default=7, help="days back to search (default 7)")
    p.set_defaults(func=cmd_cal_find)

    p = cal.add_parser("add", help="add an event to the Household calendar")
    p.add_argument("title", nargs="+")
    _add_time_options(p)
    p.add_argument("--repeat", choices=hh.REPEATS)
    p.add_argument("--until", help="YYYY-MM-DD last date of a repeating event")
    p.add_argument("--count", type=int, help="number of times a repeating event happens")
    p.set_defaults(func=cmd_cal_add)

    p = cal.add_parser("update", help="change a Household event")
    p.add_argument("event_id")
    p.add_argument("--title", nargs="+")
    _add_time_options(p, for_update=True)
    p.add_argument("--future", action="store_true", help="also change every later event in the repeating series")
    p.set_defaults(func=cmd_cal_update)

    p = cal.add_parser("delete", help="delete a Household event")
    p.add_argument("event_id")
    p.add_argument("--future", action="store_true", help="also delete every later event in the repeating series")
    p.set_defaults(func=cmd_cal_delete)

    # Reminders lists
    lists = commands.add_parser("list", help="Reminders lists: grocery, to-dos, bills").add_subparsers(required=True, metavar="action")
    lists.add_parser("names", help="every list and how many open items it has").set_defaults(func=cmd_list_names)

    p = lists.add_parser("show")
    p.add_argument("name")
    p.add_argument("--done", action="store_true", help="also show items finished in the last 7 days")
    p.set_defaults(func=cmd_list_show)

    p = lists.add_parser("add", help="add items: list add Grocery milk 'rye bread'")
    p.add_argument("name")
    p.add_argument("items", nargs="+")
    p.add_argument("--due", help="YYYY-MM-DD")
    p.add_argument("--at", help="HH:MM due time (phones alert then)")
    p.add_argument("--repeat", choices=rm.SIMPLE_REPEATS, help="needs --due")
    p.add_argument("--notes")
    p.set_defaults(func=cmd_list_add)

    p = lists.add_parser("done", help="tick off items (repeating ones move to their next due date)")
    p.add_argument("name")
    p.add_argument("items", nargs="+", help="title, piece of a title, or #id")
    p.set_defaults(func=cmd_list_done)

    p = lists.add_parser("undo", help="put recently ticked-off items back")
    p.add_argument("name")
    p.add_argument("items", nargs="+")
    p.set_defaults(func=cmd_list_undo)

    p = lists.add_parser("remove", help="delete items outright")
    p.add_argument("name")
    p.add_argument("items", nargs="+")
    p.set_defaults(func=cmd_list_remove)

    p = lists.add_parser("edit")
    p.add_argument("name")
    p.add_argument("item")
    p.add_argument("--title", nargs="+")
    p.add_argument("--due", help="YYYY-MM-DD")
    p.add_argument("--at", help="HH:MM")
    p.add_argument("--no-due", action="store_true")
    p.add_argument("--notes", help="'' to clear")
    p.add_argument("--repeat", choices=rm.SIMPLE_REPEATS)
    p.add_argument("--no-repeat", action="store_true")
    p.set_defaults(func=cmd_list_edit)

    p = lists.add_parser("clear", help="tick off everything on a list (not repeating items)")
    p.add_argument("name")
    p.set_defaults(func=cmd_list_clear)

    p = lists.add_parser("due", help="open items on every list due soon or overdue")
    p.add_argument("--days", type=int, default=7)
    p.set_defaults(func=cmd_list_due)

    return parser


def main() -> None:
    args = build_parser().parse_args()
    try:
        args.func(args)
    except (AppleError, ConfigError, hh.InputError, rm.ReminderError, messages.MessagesError) as e:
        sys.exit(f"error: {e}")


if __name__ == "__main__":
    main()
