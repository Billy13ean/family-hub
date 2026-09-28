import json
import sqlite3

import pytest

from home_manager import messages


def test_family_chats_only_lists_allowlisted_one_to_one_chats(tmp_path):
    db = tmp_path / "chat.db"
    with sqlite3.connect(db) as con:
        con.executescript("""
            CREATE TABLE chat (ROWID INTEGER PRIMARY KEY, guid TEXT, style INTEGER);
            CREATE TABLE handle (ROWID INTEGER PRIMARY KEY, id TEXT);
            CREATE TABLE chat_handle_join (chat_id INTEGER, handle_id INTEGER);
            INSERT INTO handle VALUES (1, '+15551234567'), (2, '+15550000000'), (3, 'Wife@iCloud.com');
            INSERT INTO chat VALUES (1, 'iMessage;-;+15551234567', 45), (2, 'iMessage;-;+15550000000', 45),
                                    (3, 'iMessage;-;wife@icloud.com', 45), (4, 'iMessage;+;chat123', 43);
            INSERT INTO chat_handle_join VALUES (1, 1), (2, 2), (3, 3), (4, 1);
        """)
    chats = messages.family_chats(["+15551234567", "wife@icloud.com"], db)
    assert chats == [("+15551234567", "iMessage;-;+15551234567"), ("Wife@iCloud.com", "iMessage;-;wife@icloud.com")]


def test_allowlist(tmp_path):
    (tmp_path / "access.json").write_text(json.dumps({"dmPolicy": "allowlist", "allowFrom": ["+15551234567"]}))
    assert messages.allowlist(tmp_path) == ["+15551234567"]
    with pytest.raises(messages.MessagesError):
        messages.allowlist(tmp_path / "missing")


def test_send_needs_someone_to_send_to():
    with pytest.raises(messages.MessagesError, match="Nobody"):
        messages.send("hi", [])
