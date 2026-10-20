"""LinkedIn alert parsing and the pending queue. The fixture is a made-up alert in LinkedIn's real layout."""

import sys
from datetime import date
from pathlib import Path

import pytest

import home_manager.__main__ as cli
from home_manager import jobs
from home_manager.pending import ACCEPTED, PendingError, Queue

ALERT = Path(__file__).parent / "fixtures" / "linkedin_alert.eml"


def test_parse_alert_reads_every_card_once():
    found = jobs.parse_alert(ALERT.read_bytes())
    assert [j.job_id for j in found] == ["1000000001", "1000000002", "1000000003", "1000000004"]
    first, _, _, bakery = found
    assert first.line() == "Trail Crew Lead · Example Parks · United States"
    assert first.alert == "park ranger in North America"
    assert bakery.line() == "Pastry Chef, Morning Shift · Demo Bakery · Chicago, IL · $55K-$62K / year"
    assert bakery.alert == "pastry chef jobs in Chicago"


def test_links_drop_the_sign_in_token():
    for job in jobs.parse_alert(ALERT.read_bytes()):
        assert job.link == f"https://www.linkedin.com/jobs/view/{job.job_id}/"
        assert "otpToken" not in repr(job)


def test_rejects_mail_that_is_not_really_from_linkedin():
    raw = ALERT.read_bytes()
    with pytest.raises(jobs.JobAlertError, match="Not a LinkedIn job alert"):
        jobs.parse_alert(raw.replace(b"jobalerts-noreply@linkedin.com", b"jobs@linkedln-careers.example"))
    with pytest.raises(jobs.JobAlertError, match="signature"):
        jobs.parse_alert(raw.replace(b"dkim=pass header.i=@linkedin.com", b"dkim=fail header.i=@linkedin.com"))


def test_clean_keeps_one_short_line_without_links():
    assert jobs.clean("<b>Manager</b>​ apply at https://evil.example/x now\x07") == "Manager apply at now"
    assert len(jobs.clean("x" * 500)) == jobs.MAX_FIELD


def test_queue_never_proposes_the_same_key_twice(tmp_path):
    queue = Queue(tmp_path / "pending.json")
    assert queue.add("job", "linkedin:1", "One", {}, date(2026, 10, 19)).number == 1
    assert queue.add("job", "linkedin:1", "One again", {}, date(2026, 10, 20)) is None
    queue.decide(1, ACCEPTED)
    queue.save()

    queue = Queue(tmp_path / "pending.json")
    assert queue.waiting() == []
    assert queue.add("job", "linkedin:2", "Two", {}, date(2026, 10, 20)).number == 2
    with pytest.raises(PendingError, match="already accepted"):
        queue.decide(1, ACCEPTED)
    with pytest.raises(PendingError, match="Nothing numbered #9"):
        queue.decide(9, ACCEPTED)


@pytest.fixture
def run(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HOME_MANAGER_CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(cli, "_today", lambda config: date(2026, 10, 19))

    def run(*argv):
        monkeypatch.setattr(sys, "argv", ["hm", *argv])
        cli.main()
        return capsys.readouterr().out

    return run


def test_scan_then_accept_and_reject(run):
    out = run("jobs", "scan", str(ALERT))
    assert out.startswith("4 new jobs (0 seen before).")
    assert "#4 Pastry Chef, Morning Shift · Demo Bakery" in out
    assert "https://www.linkedin.com/jobs/view/1000000004/" in out

    assert run("jobs", "scan", str(ALERT)).startswith("0 new jobs (4 seen before).")
    assert "Accepted: #1 Trail Crew Lead" in run("pending", "accept", "1")
    assert "Rejected: #2" in run("pending", "reject", "2")

    out = run("pending", "list", "--kind", "job")
    assert "#1" not in out and "#2" not in out and "#3 [job] Wildlife Survey Technician" in out
