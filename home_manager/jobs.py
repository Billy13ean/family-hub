"""LinkedIn job-alert emails: pull out the jobs in them.

Every link in an alert email carries a one-time LinkedIn sign-in token
(otpToken), so only the job ID is kept. Raw links are never stored, printed
or passed on; `Job.link` rebuilds a clean one from the ID.

Everything in the email is untrusted text: anyone can send mail, so the
sender must pass LinkedIn's DKIM check, and every field is trimmed to one
short line with links removed.
"""

import email
import re
from dataclasses import dataclass
from email import policy
from email.utils import parseaddr

SENDER = "jobalerts-noreply@linkedin.com"
MAX_FIELD = 120

_VIEW_JOB = re.compile(r"^View job: https://www\.linkedin\.com/comm/jobs/view/(\d+)/")
_ALERT_FOR = re.compile(r"^Your job alert for (.+)$")
_JOBS_IN = re.compile(r"^(.+) jobs in (.+)$")
_SKIP = ("New jobs match", "New jobs from your other alerts", "Manage alerts:", "See all jobs", "Edit alert", "---")
_PAY = re.compile(r"\$\d")


class JobAlertError(Exception):
    pass


@dataclass(frozen=True)
class Job:
    job_id: str
    title: str
    company: str
    location: str
    pay: str = ""
    alert: str = ""  # the saved search that found it

    @property
    def key(self) -> str:
        return f"linkedin:{self.job_id}"

    @property
    def link(self) -> str:
        return f"https://www.linkedin.com/jobs/view/{self.job_id}/"

    def line(self) -> str:
        return " · ".join(part for part in (self.title, self.company, self.location, self.pay) if part)


def clean(text: str) -> str:
    """One short line of plain text: no tags, links or control characters."""
    text = re.sub(r"<[^>]*>", "", text)
    text = re.sub(r"\S*://\S*", "", text)
    text = "".join(ch for ch in text if ch.isprintable())
    return " ".join(text.split())[:MAX_FIELD]


def from_linkedin(msg) -> bool:
    """True when Gmail's own check (the topmost Authentication-Results) saw a valid LinkedIn signature."""
    results = msg.get_all("Authentication-Results") or []
    return bool(results) and "dkim=pass header.i=@linkedin.com" in str(results[0])


def parse_alert(raw: bytes) -> list[Job]:
    msg = email.message_from_bytes(raw, policy=policy.default)
    sender = parseaddr(str(msg["From"] or ""))[1].lower()
    if sender != SENDER:
        raise JobAlertError(f"Not a LinkedIn job alert (from {sender or 'nobody'}).")
    if not from_linkedin(msg):
        raise JobAlertError("Says it's from LinkedIn but doesn't pass LinkedIn's signature check.")
    body = msg.get_body(("plain",))
    if body is None:
        raise JobAlertError("The alert has no plain-text part.")
    return parse_alert_text(body.get_content())


def parse_alert_text(text: str) -> list[Job]:
    """Jobs in the order the email lists them, each once."""
    jobs: dict[str, Job] = {}
    alert, card = "", []
    for raw_line in text.splitlines():
        line = clean(raw_line)
        if not line or line.startswith(_SKIP):
            continue
        view = _VIEW_JOB.match(raw_line.strip())
        if view:
            job_id = view.group(1)
            if len(card) >= 3 and job_id not in jobs:
                pay = next((l for l in card[3:] if _PAY.search(l)), "")
                jobs[job_id] = Job(job_id, card[0], card[1], card[2], pay, alert)
            card = []
            continue
        if _ALERT_FOR.match(line) or _JOBS_IN.match(line):  # a new saved search starts
            alert, card = line.removeprefix("Your job alert for "), []
            continue
        card.append(line)
    return list(jobs.values())
