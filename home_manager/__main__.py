"""Command line entry point: `uv run python -m home_manager <command>`."""

import argparse
import sys
from datetime import date, datetime, time, timedelta

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from .config import ConfigError, get_paths, load_config
from .delivery import send_email
from .events import fetch_events, list_calendars
from .google_auth import AuthError, load_credentials
from .summary import find_conflicts, format_summary, merge_shared


def cmd_auth(args) -> None:
    paths = get_paths()
    load_credentials(paths, interactive=True)
    print(f"Signed in. Token saved to {paths.token}")


def cmd_calendars(args) -> None:
    creds = load_credentials(get_paths())
    service = build("calendar", "v3", credentials=creds, cache_discovery=False)
    for cal in list_calendars(service):
        print(f"{cal['id']}\t{cal.get('summary', '')}\t(access: {cal.get('accessRole')})")


def cmd_summary(args) -> None:
    paths = get_paths()
    config = load_config(paths)
    tz = config.timezone
    day = date.fromisoformat(args.date) if args.date else datetime.now(tz).date()
    start = datetime.combine(day, time(), tz)
    end = datetime.combine(day + timedelta(days=1), time(), tz)

    creds = load_credentials(paths)
    service = build("calendar", "v3", credentials=creds, cache_discovery=False)

    events, warnings = [], []
    for source in config.calendars:
        try:
            events += fetch_events(service, source, start, end, tz)
        except HttpError as e:
            # One unreadable calendar shouldn't stop the whole summary.
            warnings.append(f"Couldn't read {source.label}'s calendar ({e.status_code}): {e.reason}")

    labels = [c.label for c in config.calendars]
    events = merge_shared(events, labels)
    subject, body = format_summary(day, labels, events, find_conflicts(events), warnings)

    if args.send:
        if not config.email_to:
            raise ConfigError("Set [email] to = [...] in config.toml to use --send.")
        send_email(creds, config.email_to, subject, body)
        print(f"Sent \"{subject}\" to {', '.join(config.email_to)}")
    else:
        print(subject, body, sep="\n\n")


def main() -> None:
    parser = argparse.ArgumentParser(prog="home_manager")
    commands = parser.add_subparsers(required=True)

    commands.add_parser("auth", help="sign in to Google (opens a browser)").set_defaults(func=cmd_auth)
    commands.add_parser("calendars", help="list calendar ids you can read").set_defaults(func=cmd_calendars)

    summary = commands.add_parser("summary", help="build today's summary (prints unless --send)")
    summary.add_argument("--date", help="YYYY-MM-DD instead of today")
    summary.add_argument("--send", action="store_true", help="email it instead of printing")
    summary.set_defaults(func=cmd_summary)

    args = parser.parse_args()
    try:
        args.func(args)
    except (AuthError, ConfigError) as e:
        sys.exit(f"error: {e}")


if __name__ == "__main__":
    main()
