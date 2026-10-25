import json
import sys
from datetime import date, datetime, time

import pytest

import home_manager.__main__ as cli
from home_manager import job_texts
from home_manager.pending import Item, Queue

POSTING = {"url": "", "pay": "$140K-$160K / year", "remote": "hybrid", "description": "LONG WEB DESCRIPTION",
           "closed": False, "suspicious": False, "suspicious_reason": "", "note": ""}  # fmt: skip


def job(number, score, added="2026-10-24", **data):
    return Item(
        number, "job", f"linkedin:{number}", f"Job {number} · Example Co · New York, NY", added,
        data={"link": f"https://careers.example.com/{number}", "posting": POSTING,
              "fit": {"score": score, "reason": f"Reason {number}."}, **data},
    )  # fmt: skip


@pytest.mark.parametrize(
    "now, quiet",
    [(time(20, 59), False), (time(21, 0), True), (time(2, 0), True), (time(7, 59), True), (time(8, 0), False)],
)
def test_quiet_hours_run_past_midnight(now, quiet):
    assert job_texts.quiet(now, time(21, 0), time(8, 0)) is quiet
    assert job_texts.quiet(now, time(1, 0), time(6, 0)) is (time(1, 0) <= now < time(6, 0))


def test_matches_are_new_scored_and_not_texted_yet():
    items = [job(1, 9), job(2, 7), job(3, 6), job(4, 8, texted="2026-10-24T09:00"), job(5, 10)]
    items[4].status = "rejected"
    items.append(Item(6, "job", "linkedin:6", "Not looked up", "2026-10-24"))
    assert [i.number for i in job_texts.matches(items, 7)] == [1, 2]


def test_match_text_has_only_short_checked_fields():
    text = job_texts.match_text([job(1, 9), job(2, 7)])
    assert text.startswith("2 new job matches:")
    assert "#1 Job 1 · Example Co · New York, NY\nHybrid · $140K-$160K / year · fit 9/10\nReason 1." in text
    assert "https://careers.example.com/2" in text
    assert 'Reply "tailor 1" or "pass 1"' in text
    assert "LONG WEB DESCRIPTION" not in text  # the hub's session can read its chat history


def test_weekly_text_lists_last_weeks_low_scores_best_first():
    items = [job(1, 9), job(2, 3), job(3, 6), job(4, 2, added="2026-10-10"), job(5, 6)]
    items.append(Item(6, "job", "linkedin:6", "Not looked up", "2026-10-24"))
    text = job_texts.weekly_text(items, 7, date(2026, 10, 25))
    assert text.startswith("Weekly job grading check: 4 jobs scored this week, 1 at 7+ (texted), 3 below 7.")
    lines = text.splitlines()
    assert [l.split()[0] for l in lines if l.startswith("#")] == ["#3", "#5", "#2"]
    assert "#3 6/10 Job 3 · Example Co · New York, NY: Reason 3." in text

    many = [job(n, 3) for n in range(1, 21)]
    assert "...and 5 more" in job_texts.weekly_text(many, 7, date(2026, 10, 25))
    assert job_texts.weekly_text([job(1, 9)], 7, date(2026, 10, 25)).endswith("0 below 7.")


def test_weekly_is_due_once_after_its_time():
    sunday = datetime(2026, 10, 25, 9, 30)
    assert job_texts.weekly_due(sunday, 6, time(9, 0), "")
    assert not job_texts.weekly_due(sunday, 6, time(9, 0), "2026-10-25")
    assert not job_texts.weekly_due(sunday.replace(hour=8), 6, time(9, 0), "")
    assert not job_texts.weekly_due(datetime(2026, 10, 26, 9, 30), 6, time(9, 0), "")


@pytest.fixture
def run(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HOME_MANAGER_CONFIG_DIR", str(tmp_path))
    (tmp_path / "config.toml").write_text('timezone = "America/New_York"\n[jobs]\nto = "+15550000001"\n')
    queue = Queue(tmp_path / "pending.json")
    queue.items = [job(1, 9), job(2, 4), job(3, 7)]
    queue.save()
    sent = []
    monkeypatch.setattr(cli.messages, "send", lambda text, handles: sent.append((text, handles)))
    clock = {"now": datetime(2026, 10, 24, 12, 0)}  # a Saturday

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock["now"].replace(tzinfo=tz)

    monkeypatch.setattr(cli, "datetime", Clock)
    monkeypatch.setattr(cli, "_today", lambda config: clock["now"].date())

    def run(*argv):
        monkeypatch.setattr(sys, "argv", ["hm", *argv])
        cli.main()
        return capsys.readouterr().out

    run.sent, run.clock, run.dir = sent, clock, tmp_path
    return run


def test_notify_texts_matches_once_to_one_person(run):
    assert "Would text +15550000001" in run("jobs", "notify", "--dry-run")
    assert run.sent == []

    assert "Texted 2 job matches to +15550000001." in run("jobs", "notify")
    (text, handles), = run.sent
    assert handles == ["+15550000001"]
    assert "#1 Job 1" in text and "#3 Job 3" in text and "#2 Job 2" not in text

    assert "No new jobs at 7+" in run("jobs", "notify")
    assert len(run.sent) == 1


def test_notify_waits_out_quiet_hours(run):
    run.clock["now"] = datetime(2026, 10, 24, 23, 0)
    assert "Quiet hours until 08:00" in run("jobs", "notify")
    run.clock["now"] = datetime(2026, 10, 25, 6, 0)
    run("jobs", "notify")
    assert run.sent == []

    run.clock["now"] = datetime(2026, 10, 25, 8, 5)  # Sunday morning, before the weekly check
    run("jobs", "notify")
    assert len(run.sent) == 1 and "2 new job matches" in run.sent[0][0]


def test_weekly_check_goes_out_once_on_sunday(run):
    run.clock["now"] = datetime(2026, 10, 25, 9, 10)
    run("jobs", "notify")
    weekly = [t for t, _ in run.sent if t.startswith("Weekly job grading check")]
    assert len(weekly) == 1 and "#2 4/10 Job 2" in weekly[0]
    assert json.loads((run.dir / "jobs-state.json").read_text()) == {"weekly_sent": "2026-10-25"}

    run.clock["now"] = datetime(2026, 10, 25, 10, 10)
    run("jobs", "notify")
    assert sum(t.startswith("Weekly") for t, _ in run.sent) == 1


def test_report_previews_and_decisions_keep_a_reason(run):
    assert run("jobs", "report").startswith("Weekly job grading check: 3 jobs scored")
    assert run.sent == []

    assert "Rejected: #2" in run("pending", "reject", "2", "--why", "too junior https://x.example")
    assert "Accepted: #1" in run("pending", "accept", "1")
    saved = {i["number"]: i["data"] for i in json.loads((run.dir / "pending.json").read_text())}
    assert saved[2]["why"] == "too junior" and saved[2]["decided"] == "2026-10-24"
    assert "why" not in saved[1] and saved[1]["decided"] == "2026-10-24"


def test_notify_needs_someone_to_text(run):
    (run.dir / "config.toml").write_text("[jobs]\nmin_fit = 7\n")
    with pytest.raises(SystemExit, match=r"Set \[jobs\] to"):
        run("jobs", "notify")


def test_jobs_to_is_one_person(run):
    (run.dir / "config.toml").write_text('[jobs]\nto = ["+15550000001"]\n')
    assert "Would text +15550000001:" in run("jobs", "notify", "--dry-run")
    (run.dir / "config.toml").write_text('[jobs]\nto = ["+15550000001", "+15550000002"]\n')
    with pytest.raises(SystemExit, match="one person only"):
        run("jobs", "notify", "--dry-run")
