# home-manager

Household helper for the family hub. It reads and changes our shared **Apple
Calendar** and **Reminders** through EventKit, and sends a morning digest by
iMessage: conflicts, the day's events, bills due soon and anything due today.

The **family hub** in [`hub/`](hub/README.md) lets us do all of this by
texting Claude. That README has the full setup: the hub's Apple Account, a macOS
VM or separate user, sharing the calendar and lists, and the iMessage plugin.

Planned later phases: diet, exercise.

## What it works with

| Thing | Where it lives | What home-manager does |
|---|---|---|
| Household calendar | iCloud, shared with us both and the hub | Reads, adds, changes, deletes |
| Personal calendars | iCloud, shared with the hub read-only | Reads, for clash checks |
| Grocery, To-Do, Bills | Shared Reminders lists | Reads, adds, ticks off, edits |
| Settings | `~/.config/home-manager/config.toml` (optional) | Calendar and list names, digest recipients and time |

Nothing personal is stored in the repo. Phone numbers and names live in
`~/.config/home-manager/config.toml` and `hub/CLAUDE.local.md`, both outside git.

## Requirements

macOS, signed into an Apple Account that can see the calendar and lists, with
Calendars and Reminders access granted to Terminal (`hm setup` asks). The tests
run anywhere, including Linux, because they use an in-memory fake instead of
EventKit.

## Commands

Run from this folder with `uv run python -m home_manager ...`, or from `hub/`
as `./hm ...`. `uv` installs Python 3.12+ and PyObjC on first use.

```sh
hm setup                 # ask for Calendars and Reminders access; check names and sharing
hm calendars             # calendars and Reminders lists this account can see
hm now                   # local date and time
hm summary [--date YYYY-MM-DD] [--send]     # the digest; --send texts it to [digest] to
hm digest-loop           # sends the digest every morning (start-hub.command runs it)
hm chats                 # iMessage chat ids of allowlisted family members
```

Calendar (reads every calendar, but only changes Household):

```sh
hm cal list [--date YYYY-MM-DD] [--days N]
hm cal find soccer
hm cal add Soccer game --start "2026-10-03 14:00" --end 15:00 --location "Field 4"
hm cal add Beach trip --date 2026-10-09 --through 2026-10-11
hm cal add Piano --start "2026-10-06 16:30" --minutes 45 --repeat weekly --until 2026-12-15
hm cal update <id> --start "2026-10-03 16:00"      # keeps the length
hm cal update <id> --start "2026-10-13 17:00" --future   # this and every later repeat
hm cal delete <id> [--future]
```

Reminders lists:

```sh
hm list names
hm list show Grocery [--done]
hm list add Grocery milk "rye bread"
hm list add Bills Electric --due 2026-10-01 --repeat monthly --notes "about \$120"
hm list add To-Do "Call plumber (Nick)" --due 2026-09-30 --at 09:30
hm list done Bills electric           # repeating items move to their next due date
hm list undo Grocery eggs | list remove Grocery 'rye bread' | list clear Grocery
hm list edit To-Do plumber --due 2026-10-02 [--no-due] [--repeat weekly] [--title ...]
hm list due [--days 7]                # anything due soon, on every list
```

Every command has `--help`. List items can be named by title, a unique piece of
the title, or the `#id` that `list show` prints.

## Tests

```sh
uv run pytest
uv run pytest tests/test_cli.py::test_grocery_list    # one test
```

## Code layout

- `home_manager/apple.py`: the only code that talks to Apple, through EventKit
- `home_manager/household.py`: turns command options into event times and repeats
- `home_manager/reminders.py`: list items: matching, due dates, repeats, formatting
- `home_manager/summary.py`: merges shared events, finds conflicts, formats the digest
- `home_manager/messages.py`: sends iMessages and looks up family chat ids
- `home_manager/config.py`: the optional config file
- `hub/`: the iMessage family hub (`hub-settings.json` locks the Claude session down; `start-hub.command` starts it; `README.md` is the setup guide)
- `tests/fake_apple.py`: an in-memory stand-in for `apple.py`, used by the tests

The first version (morning email from two Google Calendars through the Google
APIs) is in git history at commit `c837dd0`.
