import json
import sys
from datetime import date
from pathlib import Path

import pytest

import home_manager.__main__ as cli
from home_manager import finder

ALERT = Path(__file__).parent / "fixtures" / "linkedin_alert.eml"

FOUND = {
    "found": True,
    "url": "https://careers.exampleparks.com/jobs/123",
    "pay": "$48K-$52K / year",
    "remote": "on-site",
    "description": "Leads a trail crew. Apply at https://evil.example/now for more.",
    "suspicious": False,
    "suspicious_reason": "",
}


@pytest.mark.parametrize(
    "url, company",
    [
        ("https://careers.exampleparks.com/jobs/1", "Example Parks"),
        ("https://exampleparks.co.uk/jobs/1", "Example Parks, Inc."),
        ("https://www.demo-bakery.com/careers", "Demo Bakery"),
        ("https://jobs.demo.com/1", "Demo Bakery"),
        ("https://boards.greenhouse.io/exampleparks/jobs/1", "Example Parks"),
        ("https://exampleparks.wd5.myworkdayjobs.com/en-US/careers/job/1", "Example Parks"),
    ],
)
def test_company_sites_and_job_sites_pass(url, company):
    assert finder.url_problem(url, company) == ""


@pytest.mark.parametrize(
    "url, why",
    [
        ("http://exampleparks.com/jobs/1", "https"),
        ("https://exampleparks-jobs.com/1", "doesn't look like"),
        ("https://exampleparks.com.evil.example/1", "doesn't look like"),
        ("https://www.linkedin.com/jobs/view/1/", "doesn't look like"),
        ("https://notgreenhouse.io/exampleparks", "doesn't look like"),
        ("https://user@exampleparks.com/1", "plain web address"),
        ("https://exampleparks.com:8443/1", "plain web address"),
        ("https://203.0.113.9/jobs", "plain web address"),
        ("https://xn--exmpleparks-9db.com/1", "plain web address"),
        ("javascript:alert(1)", "https"),
    ],
)
def test_other_links_are_refused(url, why):
    assert why in finder.url_problem(url, "Example Parks")


def test_check_posting_cleans_and_caps_text():
    posting = finder.check_posting({**FOUND, "description": "x " * 1000, "pay": "<b>$50K</b>"}, "Example Parks")
    assert posting.url == FOUND["url"]
    assert posting.pay == "$50K"
    assert len(posting.description) == finder.MAX_DESCRIPTION
    links = finder.check_posting(FOUND, "Example Parks")
    assert "evil" not in links.description and "://" not in links.description


def test_a_bad_link_drops_everything_from_that_page():
    posting = finder.check_posting({**FOUND, "url": "https://exampleparks-hiring.example/1"}, "Example Parks")
    assert posting.url == "" and posting.pay == "" and posting.description == ""
    assert posting.suspicious and "link dropped" in posting.note


def test_not_found_and_junk_answers_fall_back():
    assert finder.check_posting({**FOUND, "found": False}, "Example Parks").note == "posting not found"
    junk = finder.check_posting({"found": "yes", "url": 5, "remote": "moon", "suspicious": "no"}, "Example Parks")
    assert junk.url == "" and junk.remote == "unknown" and junk.suspicious is False


def test_score_is_clamped_and_must_be_a_number(monkeypatch):
    monkeypatch.setattr(finder, "run_claude", lambda prompt, schema, tools: {"fit": 42, "reason": "Great https://x.example"})
    assert finder.score("profile", "Job", finder.Posting()) == (10, "Great")
    monkeypatch.setattr(finder, "run_claude", lambda prompt, schema, tools: {"fit": "9", "reason": ""})
    with pytest.raises(finder.FinderError, match="number"):
        finder.score("profile", "Job", finder.Posting())


class FakeClaude:
    """Answers like `claude -p` and records which tools and prompt each run got."""

    def __init__(self):
        self.runs = []

    def __call__(self, prompt, schema, tools):
        self.runs.append((prompt, tools))
        if "fit" in schema["properties"]:
            return {"fit": 7, "reason": "Outdoor work, pay above the floor."}
        if "Demo Bakery" in prompt:
            return {**FOUND, "url": "https://bakery-careers.example/1"}
        return FOUND


@pytest.fixture
def run(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HOME_MANAGER_CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(cli, "_today", lambda config: date(2026, 10, 19))
    fake = FakeClaude()
    monkeypatch.setattr(finder, "run_claude", fake)

    def run(*argv):
        monkeypatch.setattr(sys, "argv", ["hm", *argv])
        cli.main()
        return capsys.readouterr().out

    run.fake = fake
    run.dir = tmp_path
    return run


def test_find_looks_up_each_job_once_without_private_data(run):
    run("jobs", "scan", str(ALERT))
    (run.dir / "job-profile.md").write_text("Pay floor: $45K. SECRET-PROFILE")

    out = run("jobs", "find")
    assert "#1 Trail Crew Lead · Example Parks" in out
    assert "https://careers.exampleparks.com/jobs/123" in out
    assert "On-site · $48K-$52K / year · fit 7/10: Outdoor work" in out
    assert "bakery-careers.example doesn't look like Demo Bakery's own site" in out
    assert "https://www.linkedin.com/jobs/view/1000000004/" in out

    finds = [(p, t) for p, t in run.fake.runs if t]
    scores = [(p, t) for p, t in run.fake.runs if not t]
    assert len(finds) == len(scores) == 4
    assert all(t == "WebSearch,WebFetch" and "SECRET-PROFILE" not in p for p, t in finds)
    assert all("SECRET-PROFILE" in p for p, _ in scores)

    assert run("jobs", "find") == "No jobs left to look up.\n"
    assert "fit 7/10" in run("pending", "list")
    saved = json.loads((run.dir / "pending.json").read_text())
    assert saved[0]["data"]["link"] == "https://careers.exampleparks.com/jobs/123"


def test_find_without_a_profile_skips_scoring(run):
    run("jobs", "scan", str(ALERT))
    out = run("jobs", "find", "1")
    assert "fit" not in out.split("No fit scores")[0]
    assert "job-profile.md doesn't exist yet" in out
    assert all(tools for _, tools in run.fake.runs)
    with pytest.raises(SystemExit, match="No waiting job numbered #9"):
        run("jobs", "find", "9")
