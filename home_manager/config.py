"""Loads settings from ~/.config/home-manager/config.toml, which lives outside the repo.

The file is optional: without it, home-manager uses the Mac's time zone, a
calendar named "Household" and a Reminders list named "Bills", and the morning
digest has nobody to send to.
"""

import os
import tomllib
from dataclasses import dataclass, field
from datetime import time
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_CONFIG_DIR = "~/.config/home-manager"


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Paths:
    dir: Path

    @property
    def config(self) -> Path:
        return self.dir / "config.toml"


@dataclass(frozen=True)
class Config:
    timezone: ZoneInfo
    # The only calendar home-manager changes.
    household_calendar: str = "Household"
    # Calendars to read, by name. Empty means every calendar except
    # subscribed ones (holidays, sports schedules) and Birthdays.
    calendars: tuple[str, ...] = ()
    # Friendlier names in summaries, for example {"Home": "Nick"}.
    labels: dict[str, str] = field(default_factory=dict)
    # Reminders list holding bills; they show up in the digest a few days early.
    bill_list: str = "Bills"
    bill_days: int = 3
    # Who gets the morning digest by iMessage, and when.
    digest_to: tuple[str, ...] = ()
    digest_time: time = time(7, 0)

    def label(self, calendar_name: str) -> str:
        return self.labels.get(calendar_name, calendar_name)


def get_paths() -> Paths:
    configured = os.environ.get("HOME_MANAGER_CONFIG_DIR", DEFAULT_CONFIG_DIR)
    return Paths(Path(configured).expanduser())


def system_timezone() -> ZoneInfo:
    """The Mac's own time zone, read from the /etc/localtime link."""
    try:
        target = os.path.realpath("/etc/localtime")
        if "zoneinfo/" in target:
            return ZoneInfo(target.split("zoneinfo/", 1)[1])
    except (OSError, ValueError, ZoneInfoNotFoundError):
        pass
    return ZoneInfo("UTC")


def _clock(text: str, key: str) -> time:
    try:
        hours, minutes = (int(part) for part in text.split(":"))
        return time(hours, minutes)
    except ValueError:
        raise ConfigError(f"{key} must look like \"07:00\", not {text!r}.") from None


def load_config(paths: Paths) -> Config:
    raw: dict = {}
    if paths.config.exists():
        with paths.config.open("rb") as f:
            try:
                raw = tomllib.load(f)
            except tomllib.TOMLDecodeError as e:
                raise ConfigError(f"{paths.config} isn't valid TOML: {e}") from None

    try:
        tz = ZoneInfo(raw["timezone"]) if "timezone" in raw else system_timezone()
    except ZoneInfoNotFoundError:
        raise ConfigError(f"Unknown timezone {raw['timezone']!r} in {paths.config}.") from None

    household = raw.get("household", {})
    calendars = raw.get("calendars", {})
    bills = raw.get("bills", {})
    digest = raw.get("digest", {})
    return Config(
        timezone=tz,
        household_calendar=household.get("calendar", "Household"),
        calendars=tuple(calendars.get("read", [])),
        labels=dict(calendars.get("labels", {})),
        bill_list=bills.get("list", "Bills"),
        bill_days=int(bills.get("remind_days", 3)),
        digest_to=tuple(digest.get("to", [])),
        digest_time=_clock(digest.get("time", "07:00"), "[digest] time"),
    )
