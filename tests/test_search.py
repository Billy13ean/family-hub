import json
import sys
from datetime import date, datetime

import pytest

import home_manager.__main__ as cli
from home_manager import deck, finder, search
from home_manager.config import ConfigError
from home_manager.pending import Item, Queue

TERMS = search.Terms(
    titles=("Trail Crew Lead",),
    locations=("Springfield, IL",),
    companies=tuple(f"Company {n}" for n in range(1, 8)) + ("The Example Parks",),
    boards=("job-sites", "builtin"),
)


def posting(title="Trail Crew Lead", company="Example Parks", url="https://careers.exampleparks.com/jobs/1", remote="on-site"):
    return {"title": title, "company": company, "location": "Springfield, IL", "url": url, "remote": remote}


def test_terms_need_titles_and_known_boards(tmp_path):
    path = tmp_path / "search.toml"
    with pytest.raises(ConfigError, match="doesn't exist"):
        search.load_terms(path)
    path.write_text('titles = []\n')
    with pytest.raises(ConfigError, match="at least one job title"):
        search.load_terms(path)
    path.write_text('titles = ["A"]\nboards = ["monster"]\n')
    with pytest.raises(ConfigError, match="Unknown board 'monster'"):
        search.load_terms(path)
    path.write_text('titles = ["A", "A"]\ncompanies = "Example"\n')
    with pytest.raises(ConfigError, match="must be a list"):
        search.load_terms(path)


def test_runs_split_the_watchlist_and_add_one_per_board():
    runs = search.runs(TERMS, "remote")
    assert [source for _, source, _ in runs] == ["companies"] * 3 + ["job-sites", "builtin"]
    assert len(runs[0][2]) == search.COMPANIES_PER_RUN and runs[2][2] == ("Company 7", "The Example Parks")
    assert all("Work mode: only remote roles." in prompt for prompt, _, _ in runs)
    assert "site:jobs.lever.co" in runs[3][0] and "site:builtin.com" in runs[4][0]
    assert [s for _, s, _ in search.runs(TERMS, "any", "boards")] == ["job-sites", "builtin"]


def test_check_keeps_only_trusted_links_at_asked_for_companies():
    answer = {"jobs": [
        posting(),
        posting(company="Example Parks LLC"),
        posting(company="Other Co", url="https://careers.otherco.com/1"),  # not on the watchlist
        posting(url="https://exampleparks-jobs.example/1"),  # not the company's site
        posting(title=""),
        "junk",
    ]}  # fmt: skip
    kept = search.check(answer, "companies", ("The Example Parks",))
    assert [f.company for f in kept] == ["Example Parks", "Example Parks LLC"]
    board = {"jobs": [posting(company="Other Co", url="https://builtin.com/job/trail-crew-lead/1")]}
    assert search.check(board, "builtin")[0].url == "https://builtin.com/job/trail-crew-lead/1"
    assert search.check(board, "wellfound") == []  # a board's links count only in its own search
    assert search.check({"jobs": "nope"}, "builtin") == []


def test_search_dedupes_filters_mode_and_reports_failed_runs(monkeypatch):
    def fake(prompt, schema, tools):
        assert tools == "WebSearch,WebFetch"
        if "Built In" in prompt:
            raise finder.FinderError("claude took longer than 300 seconds.")
        return {"jobs": [posting(), posting(remote="remote", title="Trail Crew Lead II"), posting(remote="unknown", title="Ranger")]}

    monkeypatch.setattr(search, "run_claude", fake)
    found, problems = search.search(TERMS, "on-site")
    assert sorted(f.title for f in found) == ["Ranger", "Trail Crew Lead"]  # once each; the remote one filtered
    assert problems == ["builtin: claude took longer than 300 seconds."]


@pytest.fixture
def run(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HOME_MANAGER_CONFIG_DIR", str(tmp_path))
    (tmp_path / "search.toml").write_text('titles = ["Trail Crew Lead"]\ncompanies = ["Example Parks"]\nboards = ["builtin"]\n')
    queue = Queue(tmp_path / "pending.json")
    queue.items = [
        Item(1, "job", "linkedin:1", "Trail Crew Lead · Example Parks · Springfield, IL", "2026-11-01",
             data={"link": "https://x", "role": "Trail Crew Lead", "company": "Example Parks", "location": "Springfield, IL"}),
    ]  # fmt: skip
    queue.save()
    monkeypatch.setattr(cli, "_today", lambda config: date(2026, 11, 8))
    looked_up = []
    monkeypatch.setattr(finder, "find", lambda title, company, location: looked_up.append(title) or finder.Posting(remote="remote"))
    monkeypatch.setattr(
        search, "run_claude",
        lambda prompt, schema, tools: {"jobs": [posting(), posting(title="Park Ranger", url="https://builtin.com/job/1")]},
    )  # fmt: skip

    def run(*argv):
        monkeypatch.setattr(sys, "argv", ["hm", *argv])
        cli.main()
        return capsys.readouterr().out

    run.dir, run.looked_up = tmp_path, looked_up
    return run


def test_search_queues_new_jobs_once_and_looks_them_up(run):
    out = run("jobs", "search")
    assert "Searching 1 companies and 1 job boards for any roles" in out
    assert "1 new job from the search (1 seen before)." in out  # Trail Crew Lead came from an alert already
    assert run.looked_up == ["Park Ranger"]
    saved = json.loads((run.dir / "pending.json").read_text())
    assert saved[1]["key"] == "web:example-parks-park-ranger" and saved[1]["data"]["source"] == "builtin"
    state = json.loads((run.dir / "jobs-state.json").read_text())
    assert "last_search" in state and "search_running" not in state


def test_list_json_filters_and_sorts_for_the_deck(run):
    with cli.pq.editing(run.dir / "pending.json") as queue:
        queue.items[0].data.update(posting={"remote": "hybrid", "pay": "$50K", "closed": False}, fit={"score": 6, "reason": "Close."})
        queue.add("job", "web:a", "Ranger · Demo Outdoors", {"link": "https://y", "posting": {"remote": "remote"}, "fit": {"score": 9}}, date(2026, 11, 8))
        queue.add("job", "web:b", "Unscored · Demo Outdoors", {"link": "https://z"}, date(2026, 11, 8))
    data = json.loads(run("jobs", "list", "--json"))
    assert [j["number"] for j in data["jobs"]] == [2, 1, 3]
    assert data["jobs"][1] == {"number": 1, "title": "Trail Crew Lead · Example Parks · Springfield, IL", "link": "https://x",
                               "remote": "hybrid", "pay": "$50K", "fit": 6, "reason": "Close.", "closed": False, "added": "2026-11-01"}  # fmt: skip
    assert data["search"] == {"requested": False, "running": "", "last": ""}
    assert [j["number"] for j in json.loads(run("jobs", "list", "--json", "--min-fit", "7"))["jobs"]] == [2]
    assert [j["number"] for j in json.loads(run("jobs", "list", "--json", "--mode", "hybrid"))["jobs"]] == [1, 3]


def test_later_asks_the_loop_which_runs_it_within_a_minute(run, monkeypatch):
    assert "within a minute" in run("jobs", "search", "--later", "--mode", "remote")
    assert json.loads(run("jobs", "list", "--json"))["search"]["requested"] is True
    for name in ("fetch", "find", "notify"):
        monkeypatch.setattr(cli, f"cmd_jobs_{name}", lambda args: None)
    modes = []
    monkeypatch.setattr(cli, "_search_now", lambda mode, only: modes.append(mode))

    class Stop(Exception):
        pass

    def sleep(seconds):
        raise Stop

    monkeypatch.setattr(cli.systime, "sleep", sleep)
    monkeypatch.setattr(sys, "argv", ["hm", "jobs", "loop"])
    with pytest.raises(Stop):
        cli.main()
    assert modes == ["remote"]
    assert "search_requested" not in json.loads((run.dir / "jobs-state.json").read_text())


def test_the_loop_clears_a_search_a_restart_cut_short(run, monkeypatch, capsys):
    (run.dir / "jobs-state.json").write_text(json.dumps({"search_running": "2026-10-19T20:45", "weekly_sent": "x"}))
    for name in ("fetch", "find", "notify"):
        monkeypatch.setattr(cli, f"cmd_jobs_{name}", lambda args: None)

    class Stop(Exception):
        pass

    def sleep(seconds):
        raise Stop

    monkeypatch.setattr(cli.systime, "sleep", sleep)
    monkeypatch.setattr(sys, "argv", ["hm", "jobs", "loop"])
    with pytest.raises(Stop):
        cli.main()
    assert "Cleared a search that a restart cut short" in capsys.readouterr().out
    assert json.loads((run.dir / "jobs-state.json").read_text()) == {"weekly_sent": "x"}
    assert json.loads(run("jobs", "list", "--json"))["search"]["running"] == ""


def test_a_reply_during_a_slow_lookup_is_kept(run, monkeypatch):
    def slow_find(title, company, location):
        run("pending", "accept", "1")  # Nick says "tailor 1" while this lookup runs
        return finder.Posting(remote="remote")

    monkeypatch.setattr(finder, "find", slow_find)
    run("jobs", "find", "1")
    saved = json.loads((run.dir / "pending.json").read_text())[0]
    assert saved["status"] == "accepted" and saved["data"]["posting"]["remote"] == "remote"


@pytest.mark.parametrize(
    "command, ok",
    [
        ("jobs list --json", True),
        ("jobs list --json --min-fit 8 --mode remote", True),
        ("jobs search --later --mode hybrid", True),
        ("pending accept 14", True),
        ("pending reject 14 --why 'too junior'", True),
        ("jobs list", False),
        ("jobs list --json --min-fit 11", False),
        ("jobs list --json --mode moon", False),
        ("jobs list --json --mode remote --mode any", False),
        ("jobs search", False),
        ("jobs tailor 14", False),
        ("pending accept 14 15", False),
        ("pending accept ²", False),
        ("pending reject 14 --why " + "x" * 81, False),
        ("summary --send", False),
        ("pending accept 14; rm -rf ~", False),
        ("", False),
    ],
)
def test_the_deck_key_runs_only_these_commands(command, ok):
    import shlex

    assert deck.allowed(shlex.split(command)) is ok


def test_the_deck_refuses_before_running_anything(monkeypatch):
    monkeypatch.setenv("SSH_ORIGINAL_COMMAND", "summary --send")
    monkeypatch.setattr(cli, "main", lambda: pytest.fail("ran a refused command"))
    with pytest.raises(SystemExit, match="may only list jobs"):
        deck.main()
    monkeypatch.setenv("SSH_ORIGINAL_COMMAND", "pending accept 'unclosed")
    with pytest.raises(SystemExit):
        deck.main()
