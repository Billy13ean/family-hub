"""The only commands the Stream Deck's SSH key may run on the hub.

That key's line in the hub's ~/.ssh/authorized_keys forces `hub/deck-command`,
which runs this with what the Mac asked for (SSH_ORIGINAL_COMMAND). Anything
that isn't one of these exact shapes is refused, so the key can list waiting
jobs, tailor or pass one, and ask for a search, and nothing else. A search only
asks: the jobs loop runs it, since claude can't sign in from an SSH session.
"""

import os
import shlex
import sys

from . import __main__ as cli
from .search import MODES

REFUSED = "error: the Stream Deck may only list jobs, tailor or pass one, and ask for a search."
MAX_WHY = 80


def _number(text: str) -> bool:
    return text.isascii() and text.isdigit() and len(text) <= 6


def _options(words: list[str], checks: dict) -> bool:
    """--flag value pairs, each flag at most once, each value passing its check."""
    if len(words) % 2:
        return False
    flags = words[::2]
    return len(set(flags)) == len(flags) and all(f in checks and checks[f](v) for f, v in zip(flags, words[1::2]))


def allowed(words: list[str]) -> bool:
    fit = lambda v: _number(v) and int(v) <= 10  # noqa: E731
    match words:
        case ["jobs", "list", "--json", *rest]:
            return _options(rest, {"--min-fit": fit, "--mode": MODES.__contains__})
        case ["jobs", "search", "--later", *rest]:
            return _options(rest, {"--mode": MODES.__contains__})
        case ["pending", "accept", n]:
            return _number(n)
        case ["pending", "reject", n]:
            return _number(n)
        case ["pending", "reject", n, "--why", why]:
            return _number(n) and 0 < len(why) <= MAX_WHY and why.isprintable()
    return False


def main() -> None:
    try:
        words = shlex.split(os.environ.get("SSH_ORIGINAL_COMMAND", ""))
    except ValueError:
        words = []
    if not allowed(words):
        sys.exit(REFUSED)
    sys.argv = ["hm", *words]
    cli.main()


if __name__ == "__main__":
    main()
