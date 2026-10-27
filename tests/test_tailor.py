import io
import json
import sys
import zipfile
from datetime import date, datetime
from xml.etree import ElementTree

import pytest

import home_manager.__main__ as cli
from home_manager import docx, finder, mailbox, tailor
from home_manager.pending import ACCEPTED, Item, Queue

FACTS = """# Career facts: Sam Example
Sam Example  •  555.010.0199  •  sam@example.com  •  linkedin.com/in/sam-example
- Cut trail repair time from 10 days to 4 at Example Parks, 2019 – 2024.
SECRET-FACTS"""

RESUME = """# Sam Example
555.010.0199  •  sam@example.com  •  linkedin.com/in/sam-example

## Experience
### Trail Crew Lead, Example Parks, 2019 – 2024
- **Cut trail repair time** from 10 days to 4 & kept crews <safe>.
*Seasonal crews*"""

LETTER = "# Sam Example\n\nOctober 27, 2026\n\nI cut repair time from 10 days to 4."

POSTING = {"url": "https://careers.exampleparks.com/jobs/123", "pay": "$48K-$52K / year", "remote": "on-site",
           "description": "Leads a trail crew.", "closed": False, "suspicious": False, "suspicious_reason": "", "note": ""}  # fmt: skip


def test_docx_is_a_valid_word_file_with_styles_and_bold():
    data = docx.build(RESUME + "\n---\n\x07odd")
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        assert {"[Content_Types].xml", "word/document.xml", "word/styles.xml", "word/numbering.xml"} <= set(z.namelist())
        for name in z.namelist():
            ElementTree.fromstring(z.read(name))  # every part is well-formed XML
        document = z.read("word/document.xml").decode()
    assert '<w:pStyle w:val="Title"/>' in document and '<w:pStyle w:val="ListBullet"/>' in document
    assert '<w:rPr><w:b/></w:rPr><w:t xml:space="preserve">Cut trail repair time</w:t>' in document
    assert "&amp; kept crews &lt;safe&gt;" in document and "<w:i/>" in document
    assert "---" not in document and "\x07" not in document


def test_check_removes_unknown_links_and_flags_unknown_numbers():
    resume = RESUME + "\n- Grew visits 40% (see https://evil.example/x or apply@evil.example, evil.com)."
    draft = tailor.check(resume, LETTER, "No chainsaw license.", FACTS, date(2026, 10, 27))
    assert "evil" not in draft.resume and len(draft.removed_links) == 3
    assert "sam@example.com" in draft.resume and "linkedin.com/in/sam-example" in draft.resume
    assert draft.unchecked_numbers == ["40"]  # 27 and 2026 are today's date
    assert draft.gaps == "No chainsaw license."


class FakeClaude:
    def __init__(self):
        self.runs = []

    def __call__(self, prompt, schema, tools):
        self.runs.append((prompt, tools))
        if "requirements" in schema["properties"]:
            return {"found": True, "about": "A parks company.", "requirements": "- Lead crews\n- Chainsaw license, see https://x.example"}
        return {"resume": RESUME, "cover_letter": LETTER, "gaps": "No chainsaw license."}


@pytest.fixture
def run(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HOME_MANAGER_CONFIG_DIR", str(tmp_path))
    (tmp_path / "config.toml").write_text('[jobs]\nto = "+15550000001"\nemail = "sam@example.com"\n')
    (tmp_path / "career-facts.md").write_text(FACTS)
    (tmp_path / "gmail.toml").write_text('address = "hub@example.com"\napp_password = "abcd"\n')
    (tmp_path / "gmail.toml").chmod(0o600)
    queue = Queue(tmp_path / "pending.json")
    queue.items = [
        Item(1, "job", "linkedin:1", "Trail Crew Lead · Example Parks · Springfield, IL", "2026-10-26", ACCEPTED,
             {"link": POSTING["url"], "role": "Trail Crew Lead", "company": "Example Parks", "location": "Springfield, IL",
              "posting": POSTING, "fit": {"score": 8, "reason": "Good fit."}}),
        Item(2, "job", "linkedin:2", "Baker · Demo Bakery · Remote", "2026-10-26", data={"link": "https://x"}),
    ]  # fmt: skip
    queue.save()
    fake = FakeClaude()
    monkeypatch.setattr(finder, "run_claude", fake)
    monkeypatch.setattr(tailor, "run_claude", fake)
    monkeypatch.setattr(cli, "_today", lambda config: date(2026, 10, 27))
    emails, texts = [], []
    monkeypatch.setattr(cli, "send_email", lambda login, to, subject, body, files: emails.append((to, subject, body, files)))
    monkeypatch.setattr(cli.messages, "send", lambda text, handles: texts.append((text, handles)))

    def run(*argv):
        monkeypatch.setattr(sys, "argv", ["hm", *argv])
        cli.main()
        return capsys.readouterr().out

    run.fake, run.emails, run.texts, run.dir = fake, emails, texts, tmp_path
    return run


def test_tailor_emails_drafts_once_and_keeps_facts_away_from_the_web(run):
    assert "Emailed a resume and cover letter to sam@example.com" in run("jobs", "tailor")
    (read_prompt, read_tools), (write_prompt, write_tools) = run.fake.runs
    assert read_tools == "WebSearch,WebFetch" and "SECRET-FACTS" not in read_prompt
    assert POSTING["url"] in read_prompt
    assert write_tools == "" and "SECRET-FACTS" in write_prompt and "- Lead crews" in write_prompt
    assert "https://x.example" not in write_prompt  # links from the web page are dropped
    assert "October 27, 2026" in write_prompt

    (to, subject, body, files), = run.emails
    assert to == "sam@example.com" and subject == "Tailored: Trail Crew Lead · Example Parks · Springfield, IL"
    assert sorted(files) == ["Sam Example Cover Letter - Example Parks.docx", "Sam Example Resume - Example Parks.docx"]
    assert "No chainsaw license." in body and POSTING["url"] in body and "Check these numbers" not in body
    (text, handles), = run.texts
    assert handles == ["+15550000001"] and "#1 Trail Crew Lead" in text and "in your email" in text

    saved = {i["number"]: i["data"] for i in json.loads((run.dir / "pending.json").read_text())}
    assert "tailored" in saved[1] and "tailored" not in saved[2]
    assert "No accepted jobs waiting" in run("jobs", "tailor")
    assert len(run.emails) == 1

    run("jobs", "tailor", "1")  # by number, it runs again
    assert len(run.emails) == 2


def test_tailor_gives_up_after_three_tries_and_says_so(run):
    (run.dir / "career-facts.md").unlink()
    for _ in range(3):
        assert "career-facts.md doesn't exist yet" in run("jobs", "tailor")
    assert run.emails == [] and run.fake.runs == []
    (text, _), = run.texts
    assert text.startswith("Couldn't tailor #1") and "doesn't exist" not in text
    assert "No accepted jobs waiting" in run("jobs", "tailor")


def test_tailor_needs_somewhere_to_email(run):
    (run.dir / "config.toml").write_text('[jobs]\nto = "+15550000001"\n')
    assert "Set [jobs] email" in run("jobs", "tailor")
    (run.dir / "config.toml").write_text('[jobs]\nemail = "not an address"\n')
    with pytest.raises(SystemExit, match="one email address"):
        run("jobs", "tailor")


def test_loop_tailors_between_hourly_fetches(run, monkeypatch):
    steps, sleeps = [], []
    for name in ("fetch", "find", "notify"):
        monkeypatch.setattr(cli, f"cmd_jobs_{name}", lambda args, name=name: steps.append(name))
    clock = {"now": datetime(2026, 10, 27, 12, 0)}

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock["now"].replace(tzinfo=tz)

    class Stop(Exception):
        pass

    def sleep(seconds):
        sleeps.append(seconds)
        clock["now"] += cli.timedelta(seconds=seconds)
        if len(sleeps) == 12:
            raise Stop

    monkeypatch.setattr(cli, "datetime", Clock)
    monkeypatch.setattr(cli.systime, "sleep", sleep)
    monkeypatch.setattr(sys, "argv", ["hm", "jobs", "loop"])
    with pytest.raises(Stop):
        cli.main()
    assert steps == ["fetch", "find", "notify"]  # once in the first 12 minutes
    assert len(run.emails) == 1  # tailored right away, not an hour later
    assert sum(sleeps) == 12 * 60


def test_send_builds_one_email_with_word_attachments():
    sent = []

    class FakeSmtp:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            pass

        def login(self, user, password):
            sent.append(("login", user, password))

        def send_message(self, message):
            sent.append(message)

    login = mailbox.Login("hub@example.com", "abcd")
    mailbox.send(login, "sam@example.com", "Tailored", "Body", {"Resume.docx": b"PK"}, connect=FakeSmtp)
    (_, user, password), message = sent
    assert (user, password) == ("hub@example.com", "abcd")
    assert message["To"] == "sam@example.com" and message["From"] == "hub@example.com"
    (attachment,) = message.iter_attachments()
    assert attachment.get_filename() == "Resume.docx" and attachment.get_content() == b"PK"
    assert attachment.get_content_type().endswith("wordprocessingml.document")
