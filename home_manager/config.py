"""Loads settings and locates secrets. Everything here lives outside the repo."""

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

DEFAULT_CONFIG_DIR = "~/.config/home-manager"


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Paths:
    dir: Path

    @property
    def config(self) -> Path:
        return self.dir / "config.toml"

    @property
    def client_secret(self) -> Path:
        return self.dir / "client_secret.json"

    @property
    def token(self) -> Path:
        return self.dir / "token.json"


@dataclass(frozen=True)
class CalendarSource:
    label: str
    id: str


@dataclass(frozen=True)
class Config:
    calendars: list[CalendarSource]
    timezone: ZoneInfo
    email_to: list[str]


def get_paths() -> Paths:
    configured = os.environ.get("HOME_MANAGER_CONFIG_DIR", DEFAULT_CONFIG_DIR)
    return Paths(Path(configured).expanduser())


def load_config(paths: Paths) -> Config:
    if not paths.config.exists():
        raise ConfigError(
            f"No config at {paths.config}. Copy config.example.toml there and edit it."
        )
    with paths.config.open("rb") as f:
        raw = tomllib.load(f)

    calendars = [CalendarSource(c["label"], c["id"]) for c in raw.get("calendars", [])]
    if not calendars:
        raise ConfigError(f"{paths.config} has no [[calendars]] entries.")
    labels = [c.label for c in calendars]
    if len(set(labels)) != len(labels):
        raise ConfigError("Calendar labels must be unique.")

    return Config(
        calendars=calendars,
        timezone=ZoneInfo(raw.get("timezone", "UTC")),
        email_to=list(raw.get("email", {}).get("to", [])),
    )
