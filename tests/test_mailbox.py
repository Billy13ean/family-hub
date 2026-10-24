import imaplib
import sys
from datetime import date
from pathlib import Path

import pytest

import home_manager.__main__ as cli
from home_manager import finder, mailbox

ALERT = (Path(__file__).parent / "fixtures" / "linkedin_alert.eml").read_bytes()
FAKE_ALERT = ALERT.replace(b"dkim=pass header.i=@linkedin.com", b"dkim=fail header.i=@linkedin.com")


class FakeImap:
    """Just enough of imaplib.IMAP4_SSL: a Gmail inbox holding (uid, raw, read) emails."""

    def __init__(self, emails, password="abcdefghijklmnop"):
        self.emails = {uid: [raw, False] for uid, raw in emails}
        self.password = password
        self.searches = []
        self.logged_out = False

    def login(self, user, password):
        if password != self.password:
            raise imaplib.IMAP4.error(b"[AUTHENTICATIONFAILED] Invalid credentials (Failure)")
        return "OK", [b"Success"]

    def select(self, mailbox):
        return "OK", [str(len(self.emails)).encode()]

    def uid(self, command, *args):
        if command == "SEARCH":
            self.searches.append(args)
            unread = [uid for uid, (_, read) in self.emails.items() if not read]
            return "OK", [b" ".join(unread)]
        if command == "FETCH":
            uid = args[0]
            assert args[1] == "(BODY.PEEK[])"  # downloading must not mark it read
            return "OK", [(b"1 (UID " + uid + b" BODY[] {%d}" % len(self.emails[uid][0]), self.emails[uid][0]), b")"]
        if command == "STORE":
            assert args[1:] == ("+FLAGS", r"(\Seen)")
            for uid in args[0].split(b","):
                self.emails[uid][1] = True
            return "OK", []
        raise AssertionError(command)

    def logout(self):
        self.logged_out = True
        return "BYE", []


def write_login(path, password="abcd efgh ijkl mnop", mode=0o600):
    path.write_text(f'address = "hub@example.com"\napp_password = "{password}"\n')
    path.chmod(mode)


def test_load_login_needs_a_private_filled_in_file(tmp_path):
    path = tmp_path / "gmail.toml"
    with pytest.raises(mailbox.MailboxError, match="doesn't exist"):
        mailbox.load_login(path)
    write_login(path, mode=0o644)
    with pytest.raises(mailbox.MailboxError, match="chmod 600"):
        mailbox.load_login(path)
    write_login(path, password="")
    with pytest.raises(mailbox.MailboxError, match="Fill in"):
        mailbox.load_login(path)
    write_login(path)
    assert mailbox.load_login(path) == mailbox.Login("hub@example.com", "abcdefghijklmnop")


def test_inbox_searches_only_linkedin_and_reports_a_bad_login():
    imap = FakeImap([(b"7", ALERT)])
    with mailbox.Inbox(mailbox.Login("hub@example.com", "abcdefghijklmnop"), connect=lambda: imap) as box:
        assert box.unread_alerts() == [(b"7", ALERT)]
    assert imap.searches == [(None, "UNSEEN", "FROM", '"jobalerts-noreply@linkedin.com"')]
    assert imap.logged_out

    with pytest.raises(mailbox.MailboxError, match="refused the login.*AUTHENTICATIONFAILED"):
        with mailbox.Inbox(mailbox.Login("hub@example.com", "wrong"), connect=lambda: FakeImap([])):
            pass


@pytest.fixture
def run(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HOME_MANAGER_CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(cli, "_today", lambda config: date(2026, 10, 24))
    write_login(tmp_path / "gmail.toml")
    imap = FakeImap([(b"7", ALERT), (b"8", FAKE_ALERT)])
    monkeypatch.setattr(cli, "inbox", lambda login: mailbox.Inbox(login, connect=lambda: imap))

    def run(*argv):
        monkeypatch.setattr(sys, "argv", ["hm", *argv])
        cli.main()
        return capsys.readouterr().out

    run.imap = imap
    return run


def test_fetch_queues_real_alerts_and_marks_everything_read(run):
    out = run("jobs", "fetch")
    assert out.startswith("4 new jobs from 2 emails (0 seen before).")
    assert "#1 Trail Crew Lead · Example Parks" in out
    assert "Skipped an email: Says it's from LinkedIn but doesn't pass LinkedIn's signature check." in out
    assert all(read for _, read in run.imap.emails.values())

    assert run("jobs", "fetch").startswith("0 new jobs from 0 emails")
    assert "Trail Crew Lead" in run("pending", "list")


def test_fetch_leaves_emails_unread_when_the_queue_cant_be_saved(run, monkeypatch):
    def broken_save(self):
        raise OSError("disk full")

    monkeypatch.setattr(cli.pq.Queue, "save", broken_save)
    with pytest.raises(OSError):
        run("jobs", "fetch")
    assert not any(read for _, read in run.imap.emails.values())


def test_loop_fetches_then_finds_and_survives_errors(run, monkeypatch):
    calls = []
    monkeypatch.setattr(finder, "find", lambda title, company, location: calls.append(title) or finder.Posting())

    class Stop(Exception):
        pass

    def sleep(seconds):
        raise Stop

    monkeypatch.setattr(cli.systime, "sleep", sleep)
    monkeypatch.setattr(sys, "argv", ["hm", "jobs", "loop"])
    with pytest.raises(Stop):
        cli.main()
    assert calls[0] == "Trail Crew Lead" and len(calls) == 4  # each new job looked up once

    def refuse(login):
        raise mailbox.MailboxError("Can't reach imap.gmail.com")

    monkeypatch.setattr(cli, "inbox", refuse)
    calls.clear()
    with pytest.raises(Stop):
        cli.main()
    assert calls == []
