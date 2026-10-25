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
DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Paths:
    dir: Path

    @property
    def config(self) -> Path:
        return self.dir / "config.toml"

    @property
    def pending(self) -> Path:
        return self.dir / "pending.json"

    @property
    def job_profile(self) -> Path:
        return self.dir / "job-profile.md"

    @property
    def gmail(self) -> Path:
        return self.dir / "gmail.toml"

    @property
    def jobs_state(self) -> Path:
        return self.dir / "jobs-state.json"


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
    # Job matches by iMessage: to one person only, never the group chat.
    jobs_to: str = ""
    jobs_min_fit: int = 7
    # No job texts in these hours; what's found overnight goes out after quiet_end.
    jobs_quiet_start: time = time(21, 0)
    jobs_quiet_end: time = time(8, 0)
    # The weekly grading check: every job that scored below jobs_min_fit.
    jobs_weekly_day: int = 6  # Monday is 0
    jobs_weekly_time: time = time(9, 0)

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
    job = raw.get("jobs", {})
    day = str(job.get("weekly_day", "sunday")).lower()
    if day not in DAYS:
        raise ConfigError(f"[jobs] weekly_day must be a day like \"sunday\", not {day!r}.")
    jobs_to = job.get("to", "")
    if isinstance(jobs_to, list) and len(jobs_to) <= 1:
        jobs_to = jobs_to[0] if jobs_to else ""  # written like [digest] to
    if not isinstance(jobs_to, str):
        raise ConfigError('[jobs] to is one phone number or email, like to = "+15551234567": job texts go to one person only.')
    min_fit = job.get("min_fit", 7)
    if not isinstance(min_fit, int) or not 1 <= min_fit <= 10:
        raise ConfigError(f"[jobs] min_fit must be a whole number from 1 to 10, not {min_fit!r}.")
    return Config(
        timezone=tz,
        household_calendar=household.get("calendar", "Household"),
        calendars=tuple(calendars.get("read", [])),
        labels=dict(calendars.get("labels", {})),
        bill_list=bills.get("list", "Bills"),
        bill_days=int(bills.get("remind_days", 3)),
        digest_to=tuple(digest.get("to", [])),
        digest_time=_clock(digest.get("time", "07:00"), "[digest] time"),
        jobs_to=jobs_to.strip(),
        jobs_min_fit=min_fit,
        jobs_quiet_start=_clock(job.get("quiet_start", "21:00"), "[jobs] quiet_start"),
        jobs_quiet_end=_clock(job.get("quiet_end", "08:00"), "[jobs] quiet_end"),
        jobs_weekly_day=DAYS.index(day),
        jobs_weekly_time=_clock(job.get("weekly_time", "09:00"), "[jobs] weekly_time"),
    )
