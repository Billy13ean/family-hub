"""Sends the summary by email through the Gmail API (send-only scope)."""

import base64
from email.message import EmailMessage

from googleapiclient.discovery import build


def send_email(creds, to: list[str], subject: str, body: str) -> None:
    message = EmailMessage()
    message["To"] = ", ".join(to)
    message["Subject"] = subject
    message.set_content(body)
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()

    gmail = build("gmail", "v1", credentials=creds, cache_discovery=False)
    gmail.users().messages().send(userId="me", body={"raw": raw}).execute()
