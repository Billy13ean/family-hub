"""Proposals waiting for a yes or no: jobs now, events and bills from email later.

The queue is a JSON file next to config.toml, outside the repo. Each item gets
a short number to text back ("tailor 3"), and a key such as
"linkedin:4480922725" so the same thing is never proposed twice, even after
it's been turned down.
"""

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path

NEW, ACCEPTED, REJECTED = "new", "accepted", "rejected"


class PendingError(Exception):
    pass


@dataclass
class Item:
    number: int
    kind: str  # "job"
    key: str
    title: str  # one line, ready to text
    added: str  # YYYY-MM-DD
    status: str = NEW
    data: dict = field(default_factory=dict)


class Queue:
    def __init__(self, path: Path):
        self.path = path
        self.items: list[Item] = []
        if path.exists():
            try:
                self.items = [Item(**raw) for raw in json.loads(path.read_text())]
            except (ValueError, TypeError) as e:
                raise PendingError(f"{path} is damaged: {e}") from None

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps([asdict(i) for i in self.items], indent=1))
        os.replace(tmp, self.path)  # never leave a half-written queue

    def add(self, kind: str, key: str, title: str, data: dict, today: date) -> Item | None:
        """The new item, or None when this key was proposed before."""
        if any(i.key == key for i in self.items):
            return None
        number = max((i.number for i in self.items), default=0) + 1
        item = Item(number, kind, key, title, today.isoformat(), data=data)
        self.items.append(item)
        return item

    def waiting(self, kind: str | None = None) -> list[Item]:
        return [i for i in self.items if i.status == NEW and kind in (None, i.kind)]

    def decide(self, number: int, status: str) -> Item:
        item = next((i for i in self.items if i.number == number), None)
        if item is None:
            raise PendingError(f"Nothing numbered #{number}.")
        if item.status != NEW:
            raise PendingError(f"#{number} was already {item.status}.")
        item.status = status
        return item
