"""iMessage helpers for the family hub (macOS only).

`send` posts the morning digest through the Messages app. `family_chats` looks
up the chat id of each allowlisted family member, so the hub can reread
conversations with the iMessage plugin after it has been switched off.
"""

import json
import os
import sqlite3
import subprocess
from pathlib import Path

# `participant` replaced `buddy` in Messages' AppleScript dictionary on newer macOS.
_SEND_SCRIPT = """
on run argv
    set theText to item 1 of argv
    tell application "Messages"
        set theService to 1st account whose service type = iMessage
        repeat with i from 2 to (count of argv)
            send theText to participant (item i of argv) of theService
        end repeat
    end tell
end run
"""

_DM_STYLE = 45  # chat.style for one-to-one chats (43 is a group)


class MessagesError(Exception):
    pass


def send(text: str, handles: list[str]) -> None:
    """Send `text` by iMessage to each handle (+15551234567 or an Apple Account email)."""
    if not handles:
        raise MessagesError("Nobody to send to. Set [digest] to = [...] in config.toml.")
    try:
        result = subprocess.run(
            ["osascript", "-", text, *handles],
            input=_SEND_SCRIPT, text=True, capture_output=True, timeout=120,
        )
    except FileNotFoundError:
        raise MessagesError("osascript isn't available; sending iMessages only works on macOS.") from None
    except subprocess.TimeoutExpired:
        raise MessagesError("Messages didn't respond within 2 minutes.") from None
    if result.returncode != 0:
        raise MessagesError(
            f"Messages couldn't send: {result.stderr.strip() or 'unknown error'}. If macOS asked whether "
            "Terminal may control Messages, allow it in System Settings > Privacy & Security > Automation."
        )


def allowlist(state_dir: Path | None = None) -> list[str]:
    """Handles allowed to text the hub, from the iMessage plugin's access.json."""
    state_dir = state_dir or Path(
        os.environ.get("IMESSAGE_STATE_DIR", Path.home() / ".claude" / "channels" / "imessage")
    )
    path = state_dir / "access.json"
    try:
        return list(json.loads(path.read_text()).get("allowFrom", []))
    except FileNotFoundError:
        raise MessagesError(f"No allowlist at {path}. Set it up as hub/README.md describes.") from None
    except (json.JSONDecodeError, AttributeError):
        raise MessagesError(f"{path} isn't valid JSON.") from None


def family_chats(handles: list[str], db: Path | None = None) -> list[tuple[str, str]]:
    """(handle, chat id) for each one-to-one chat with an allowlisted handle."""
    db = db or Path.home() / "Library" / "Messages" / "chat.db"
    wanted = {h.lower() for h in handles}
    try:
        with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as con:
            rows = con.execute(
                """
                SELECT h.id, c.guid
                FROM chat c
                JOIN chat_handle_join j ON j.chat_id = c.ROWID
                JOIN handle h ON h.ROWID = j.handle_id
                WHERE c.style = ?
                ORDER BY h.id
                """,
                (_DM_STYLE,),
            ).fetchall()
    except sqlite3.Error as e:
        raise MessagesError(
            f"Can't read the Messages database ({e}). Terminal needs Full Disk Access."
        ) from None
    return [(handle, guid) for handle, guid in rows if handle.lower() in wanted]
