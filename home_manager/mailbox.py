"""The hub's own Gmail account: LinkedIn job alerts in over IMAP, tailored drafts out over SMTP.

Nick's Gmail forwards LinkedIn alerts here with a filter, so this inbox only
ever holds what that filter sends. The login is the hub account's address and
a Google app password, kept in ~/.config/home-manager/gmail.toml (outside the
repo, readable only by its owner). No AI reads this mailbox: this module hands
the raw emails to `jobs.parse_alert`, which checks LinkedIn's signature.

The only mail it sends is tailored drafts, to the one address in `[jobs] email`.
"""

import imaplib
import smtplib
import stat
from email.message import EmailMessage
import tomllib
from dataclasses import dataclass
from pathlib import Path

from .jobs import SENDER

HOST = "imap.gmail.com"
SMTP_HOST = "smtp.gmail.com"
DOCX = "vnd.openxmlformats-officedocument.wordprocessingml.document"
TIMEOUT = 60  # seconds
MAX_EMAILS = 50  # per fetch; anything more waits for the next one


class MailboxError(Exception):
    pass


@dataclass(frozen=True)
class Login:
    address: str
    app_password: str


def load_login(path: Path) -> Login:
    if not path.exists():
        raise MailboxError(f"{path} doesn't exist. Copy gmail.example.toml there and fill it in.")
    if path.stat().st_mode & (stat.S_IRWXG | stat.S_IRWXO):
        raise MailboxError(f"{path} holds a password, so only you may read it: run chmod 600 {path}")
    try:
        raw = tomllib.loads(path.read_text())
    except tomllib.TOMLDecodeError as e:
        raise MailboxError(f"{path} isn't valid TOML: {e}") from None
    address = str(raw.get("address", "")).strip()
    password = "".join(str(raw.get("app_password", "")).split())  # Google shows it in groups of four
    if not address or not password:
        raise MailboxError(f"Fill in address and app_password in {path}.")
    return Login(address, password)


class Inbox:
    """Unread LinkedIn alerts in the hub's inbox. Use as `with Inbox(login) as inbox:`."""

    def __init__(self, login: Login, connect=None):
        self.login = login
        self.connect = connect or (lambda: imaplib.IMAP4_SSL(HOST, timeout=TIMEOUT))
        self.imap = None

    def __enter__(self) -> "Inbox":
        try:
            self.imap = self.connect()
            self.imap.login(self.login.address, self.login.app_password)
            self._ok(self.imap.select("INBOX"), "open the inbox")
        except imaplib.IMAP4.error as e:
            self.close()
            raise MailboxError(f"Gmail refused the login for {self.login.address}: {_text(e)}") from None
        except OSError as e:
            self.close()
            raise MailboxError(f"Can't reach {HOST}: {e}") from None
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        if self.imap is not None:
            try:
                self.imap.logout()
            except (imaplib.IMAP4.error, OSError):
                pass
            self.imap = None

    def unread_alerts(self) -> list[tuple[bytes, bytes]]:
        """(uid, raw email) for each unread alert, oldest first. Reading doesn't mark them read."""
        try:
            data = self._ok(self.imap.uid("SEARCH", None, "UNSEEN", "FROM", f'"{SENDER}"'), "search")
            uids = (data[0] or b"").split()[:MAX_EMAILS]
            emails = []
            for uid in uids:
                parts = self._ok(self.imap.uid("FETCH", uid, "(BODY.PEEK[])"), "download an email")
                raw = next((p[1] for p in parts if isinstance(p, tuple) and len(p) == 2), None)
                if raw:
                    emails.append((uid, raw))
            return emails
        except (imaplib.IMAP4.error, OSError) as e:
            raise MailboxError(f"Reading the inbox failed: {_text(e)}") from None

    def mark_read(self, uids: list[bytes]) -> None:
        if not uids:
            return
        try:
            self._ok(self.imap.uid("STORE", b",".join(uids), "+FLAGS", r"(\Seen)"), "mark emails read")
        except (imaplib.IMAP4.error, OSError) as e:
            raise MailboxError(f"Marking emails read failed: {_text(e)}") from None

    @staticmethod
    def _ok(response, doing: str):
        status, data = response
        if status != "OK":
            raise MailboxError(f"Gmail wouldn't {doing}: {_text(data)}")
        return data


def send(login: Login, to: str, subject: str, body: str, attachments: dict[str, bytes], connect=None) -> None:
    """Email `to` from the hub's account, with .docx attachments ({file name: contents})."""
    message = EmailMessage()
    message["From"], message["To"], message["Subject"] = login.address, to, subject
    message.set_content(body)
    for name, data in attachments.items():
        message.add_attachment(data, maintype="application", subtype=DOCX, filename=name)
    connect = connect or (lambda: smtplib.SMTP_SSL(SMTP_HOST, 465, timeout=TIMEOUT))
    try:
        with connect() as smtp:
            smtp.login(login.address, login.app_password)
            smtp.send_message(message)
    except smtplib.SMTPAuthenticationError as e:
        raise MailboxError(f"Gmail refused the login for {login.address}: {_text(e.smtp_error)}") from None
    except (smtplib.SMTPException, OSError) as e:
        raise MailboxError(f"Sending email through {SMTP_HOST} failed: {_text(str(e))}") from None


def _text(value) -> str:
    if isinstance(value, list):
        value = b" ".join(v for v in value if isinstance(v, bytes))
    if isinstance(value, bytes):
        value = value.decode(errors="replace")
    return " ".join(str(value).split())[:200]
