"""KAN-437: the PR check reads the ticket through the tracker role (actions/work-system-pr/tracker.py).

check.py sees a normalised issue only. Two fake providers with different field layouts pass rule 6 end to end without
a change to check.py; the jira-cloud provider keeps Jira's JSON on its side of the seam.
"""

import http.client
import importlib.util
import inspect
import json
import os
import subprocess
import sys
import urllib.error
from pathlib import Path
from typing import ClassVar

import pytest

ROOT = Path(__file__).resolve().parents[1]
CHECK = ROOT / "actions/work-system-pr/check.py"
if "work_system_pr" in sys.modules:
    wsp = sys.modules["work_system_pr"]
else:
    spec = importlib.util.spec_from_file_location("work_system_pr", CHECK)
    wsp = importlib.util.module_from_spec(spec)
    sys.modules["work_system_pr"] = wsp
    spec.loader.exec_module(wsp)
tracker = wsp.tracker

JIRA_FIELD_NAMES = ("statusCategory", "issuetype", "issuelinks", "inwardIssue", '"fields"', "rest/api")


# --- two fake trackers with different field layouts ------------------------------------------------------------------

class FakeA:
    """Keeps tickets as {state: {group}, type, tags, blockers: [key]}."""

    label = "Tracker A"
    inputs = ("A_TOKEN",)
    world: ClassVar[dict] = {}

    def __init__(self, config):
        assert config == {"A_TOKEN": "secret-a"}

    def read(self, key):
        if key not in self.world:
            raise tracker.TicketMissing("no such item")
        t = self.world[key]

        def norm(k, x):
            group = {"backlog": "todo", "active": "in_progress", "closed": "done"}[x["state"]["group"]]
            return {"key": k, "category": group, "kind": x["type"], "labels": x["tags"]}

        return {**norm(key, t), "status": t["state"]["name"],
                "blocked_by": [norm(b, self.world[b]) for b in t["blockers"]]}


class FakeB:
    """Keeps tickets as flat rows: [key, status, is_finished, issue_class, labels_csv, blocked_by_csv]."""

    label = "Tracker B"
    inputs = ("B_URL", "B_TOKEN")
    rows: ClassVar[list] = []

    def __init__(self, config):
        self.config = config

    def read(self, key):
        rows = {r[0]: r for r in self.rows}
        if key not in rows:
            raise tracker.TrackerUnreachable("tracker B timed out")

        def norm(r):
            kind = {"Feature": "work", "Bug": "work", "Theme": "epic", "ADR": "decision"}[r[3]]
            return {"key": r[0], "category": "done" if r[2] else "todo", "kind": kind,
                    "labels": [x for x in r[4].split(",") if x]}

        r = rows[key]
        return {**norm(r), "status": r[1], "blocked_by": [norm(rows[b]) for b in r[5].split(",") if b]}


@pytest.fixture
def fakes(monkeypatch):
    monkeypatch.setitem(tracker.PROVIDERS, "fake-a", FakeA)
    monkeypatch.setitem(tracker.PROVIDERS, "fake-b", FakeB)
    FakeA.world = {
        "KAN-315": {"state": {"group": "active", "name": "Doing"}, "type": "work", "tags": ["exec:pair"],
                    "blockers": []},
        "KAN-316": {"state": {"group": "closed", "name": "Shipped"}, "type": "work", "tags": ["exec:pair"],
                    "blockers": []},
        "KAN-317": {"state": {"group": "active", "name": "Doing"}, "type": "work", "tags": ["exec:pair"],
                    "blockers": ["KAN-330"]},
        "KAN-330": {"state": {"group": "backlog", "name": "Open"}, "type": "decision", "tags": [], "blockers": []},
    }
    FakeB.rows = [
        ["KAN-315", "Ready", False, "Feature", "exec:agent", ""],
        ["KAN-316", "Released", True, "Bug", "exec:pair", ""],
        ["KAN-317", "Ready", False, "Feature", "exec:pair", "KAN-330"],
        ["KAN-330", "Proposed", False, "ADR", "", ""],
    ]


def run_main(tmp_path, monkeypatch, key, env):
    pr = {"number": 7, "title": f"{key}: change", "body": f"Jira: {key}\nDocs: none needed - test\n",
          "head": {"ref": f"{key}-x"}, "html_url": "https://github.com/o/r/pull/7", "base": {"sha": "b" * 40},
          "labels": [], "user": {"login": "sean"}}
    ev = tmp_path / "event.json"
    ev.write_text(json.dumps({"pull_request": pr}))
    summary = tmp_path / "summary.md"
    summary.write_text("")
    for k in ("INPUT_ORG_FILE", "INPUT_JIRA_BASE_URL", "INPUT_JIRA_USER", "INPUT_JIRA_TOKEN", "INPUT_ALLOW_UNVERIFIED"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(ev))
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    monkeypatch.setenv("GITHUB_API_URL", "http://127.0.0.1:9")  # the file list is unreachable: rule 6 doesn't need it
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    for k, v in env.items():
        monkeypatch.setenv(f"INPUT_{k}", v)
    rc = wsp.main()
    return rc, summary.read_text()


A = {"TRACKER_PROVIDER": "fake-a", "A_TOKEN": "secret-a"}
B = {"TRACKER_PROVIDER": "fake-b", "B_URL": "https://tracker-b.example.com", "B_TOKEN": "secret-b"}


@pytest.mark.parametrize("env", [A, B], ids=["layout-a", "layout-b"])
def test_rule_6_end_to_end_through_a_fake_tracker(tmp_path, monkeypatch, fakes, env):
    rc, summary = run_main(tmp_path, monkeypatch, "KAN-315", env)
    assert rc == 0 and "Passes for KAN-315." in summary, summary
    rc, summary = run_main(tmp_path, monkeypatch, "KAN-316", env)
    assert rc == 1 and "error: KAN-316 is " in summary and "reopen it" in summary
    rc, summary = run_main(tmp_path, monkeypatch, "KAN-317", env)
    assert rc == 1 and "blocked by open Decision KAN-330" in summary
    rc, summary = run_main(tmp_path, monkeypatch, "KAN-330", env)
    assert rc == 1 and "KAN-330 is a decision" in summary


def test_a_missing_ticket_fails_and_an_unreachable_tracker_fails_closed(tmp_path, monkeypatch, fakes):
    rc, summary = run_main(tmp_path, monkeypatch, "KAN-999", A)
    assert rc == 1 and "KAN-999 could not be read from Tracker A (no such item)" in summary
    # a configured tracker that doesn't answer fails the check (KAN-365), unless allow-unverified is set
    rc, summary = run_main(tmp_path, monkeypatch, "KAN-999", B)
    assert rc == 1 and "error: Tracker B was not reachable (tracker B timed out)" in summary
    rc, summary = run_main(tmp_path, monkeypatch, "KAN-999", {**B, "ALLOW_UNVERIFIED": "true"})
    assert rc == 0 and "Tracker B was not reachable (tracker B timed out)" in summary
    assert "(allow-unverified is set)" in summary


def test_a_provider_without_its_inputs_skips_rule_6_with_a_notice(tmp_path, monkeypatch, fakes):
    rc, summary = run_main(tmp_path, monkeypatch, "KAN-316", {"TRACKER_PROVIDER": "fake-b", "B_TOKEN": "t"})
    assert rc == 0
    assert "no tracker credentials given (tracker-provider fake-b needs b-url); rule 6 skipped" in summary


def test_an_unknown_provider_fails_rather_than_skipping(tmp_path, monkeypatch, fakes):
    rc, summary = run_main(tmp_path, monkeypatch, "KAN-315", {"TRACKER_PROVIDER": "./my_tracker.py"})
    assert rc == 1 and "tracker-provider './my_tracker.py' is not one of: fake-a, fake-b, jira-cloud" in summary


@pytest.mark.parametrize("answer, words", [
    ({"key": "KAN-315", "category": "Done", "kind": "work", "labels": [], "blocked_by": []},
     "category 'Done' is not one of todo, in_progress, done"),
    ({"key": "KAN-1", "category": "todo", "kind": "work", "labels": [], "blocked_by": []},
     "answered for KAN-1, not KAN-315"),
    ({"key": "KAN-315", "category": "todo", "kind": "work", "labels": ["exec:pair"]}, "has no blocked_by"),
    ({"key": "KAN-315", "category": "todo", "kind": "work", "blocked_by": []}, "has no labels"),
    ({"key": "KAN-315", "category": "todo", "kind": "work", "labels": ["exec:pair"],
      "blocked_by": [{"key": "KAN-330", "category": "todo", "kind": "work"}]},
     "an issue blocking KAN-315 has no labels"),
    ({"key": "KAN-315", "category": "todo", "kind": "work", "labels": ["exec:pair"], "blocked_by": [],
      "issue_type": ["Story"]}, "issue_type must be a string"),
])
def test_an_answer_that_is_not_normalised_fails_the_check(tmp_path, monkeypatch, fakes, answer, words):
    monkeypatch.setattr(FakeA, "read", lambda self, key: answer)
    rc, summary = run_main(tmp_path, monkeypatch, "KAN-315", A)
    assert rc == 1 and words in summary and "the ticket was not checked" in summary, summary


def test_a_provider_that_crashes_fails_the_check_without_a_traceback(tmp_path, monkeypatch, fakes):
    monkeypatch.setattr(FakeA, "read", lambda self, key: {}["boom"])
    rc, summary = run_main(tmp_path, monkeypatch, "KAN-315", A)
    assert rc == 1 and "the fake-a provider failed: KeyError" in summary


def test_an_unknown_provider_is_ignored_on_a_pr_without_a_ticket(tmp_path, monkeypatch, fakes):
    rc, _ = run_main(tmp_path, monkeypatch, "KAN-315", {"TRACKER_PROVIDER": "nope"})
    assert rc == 1  # with a ticket key, an unknown provider fails
    pr = {"number": 7, "title": "bump requests", "body": "", "head": {"ref": "x"}, "html_url": "u",
          "base": {"sha": "b" * 40}, "labels": [{"name": "no-ticket"}], "user": {"login": "sean"}}
    (tmp_path / "event.json").write_text(json.dumps({"pull_request": pr}))
    assert wsp.main() == 0


def test_this_repository_runs_the_check_without_tracker_credentials(tmp_path):
    """The repository's own workflow passes no credentials: rule 6 is skipped with a visible notice."""
    pr = {"number": 7, "title": "KAN-437: x", "body": "Jira: KAN-437\nDocs: none needed - test\n",
          "head": {"ref": "KAN-437-x"}, "html_url": "u", "base": {"sha": "b" * 40}, "labels": [],
          "user": {"login": "sean"}}
    ev = tmp_path / "event.json"
    ev.write_text(json.dumps({"pull_request": pr}))
    env = {k: v for k, v in os.environ.items() if not k.startswith(("INPUT_", "GITHUB_"))}
    env.update(GITHUB_EVENT_PATH=str(ev), GITHUB_REPOSITORY="o/r", GITHUB_API_URL="http://127.0.0.1:9")
    r = subprocess.run([sys.executable, str(CHECK)], env=env, capture_output=True, text=True, check=False)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "::warning::no tracker credentials given (tracker-provider jira-cloud needs jira-base-url, jira-user, " \
           "jira-token); rule 6 skipped" in r.stdout
    workflow = (ROOT / ".github/workflows/work-system.yml").read_text()
    assert "uses: ./actions/work-system-pr" in workflow and "jira-token" not in workflow


def test_check_py_reads_no_tracker_json_for_rule_6():
    rule6 = inspect.getsource(wsp.check_ticket) + inspect.getsource(wsp._is_decision)
    assert not [n for n in JIRA_FIELD_NAMES if n in rule6]
    src = CHECK.read_text()
    assert "def _jira(" not in src and "fields=status,labels,issuetype,issuelinks" not in src
    main = inspect.getsource(wsp.main)
    rule6_main = main[main.index("tracker.from_inputs"):main.index("gates: list[Gate]")]
    assert "_get(" not in rule6_main and not [n for n in JIRA_FIELD_NAMES if n in rule6_main]


# --- the jira-cloud provider -----------------------------------------------------------------------------------------

def jira(key, cat="indeterminate", name="In Progress", itype="Task", labels=(), links=()):
    return {"key": key, "fields": {"status": {"name": name, "statusCategory": {"key": cat}},
                                   "issuetype": {"name": itype}, "labels": list(labels), "issuelinks": list(links)}}


def blocks(issue, kind="Blocks"):
    return {"type": {"name": kind}, "inwardIssue": {"key": issue["key"], "fields": {
        "status": issue["fields"]["status"], "issuetype": issue["fields"]["issuetype"]}}}


def provider(issues, errors=None):
    seen = []

    def get(url, headers):
        assert headers["Authorization"].startswith("Basic ")
        seen.append(url)
        key = url.split("/issue/")[1].split("?")[0]
        if key in (errors or {}):
            raise errors[key]
        if key not in issues:
            raise urllib.error.HTTPError(url, 404, "Not Found", None, None)  # type: ignore[arg-type]
        return issues[key]

    cfg = {"JIRA_BASE_URL": "https://example.atlassian.net/", "JIRA_USER": "bot@example.com", "JIRA_TOKEN": "t"}
    return tracker.Reader("jira-cloud", tracker.JiraCloud(cfg, get=get)), seen


def test_jira_cloud_normalises_status_kind_labels_and_blockers():
    dec = jira("KAN-320", "new", "Needs Decision", "Decision")
    task_dec = jira("KAN-330", "new", "To Do", "Task", ["type:decision"])
    work = jira("KAN-340", "done", "Done", "Story", ["exec:pair"])
    me = jira("KAN-315", labels=["exec:pair", "DATA-change"],
              links=[blocks(dec), blocks(task_dec), blocks(work), blocks(dec, "Relates"),
                     {"type": {"name": "Blocks"}, "outwardIssue": {"key": "KAN-999"}}])
    r, seen = provider({i["key"]: i for i in (dec, task_dec, work, me)})
    got = r.read("KAN-315")
    assert got == {"key": "KAN-315", "status": "In Progress", "category": "in_progress", "kind": "work",
                   "labels": ["exec:pair", "DATA-change"],
                   "blocked_by": [{"key": "KAN-320", "category": "todo", "kind": "decision", "labels": []},
                                  {"key": "KAN-330", "category": "todo", "kind": "work", "labels": ["type:decision"]},
                                  {"key": "KAN-340", "category": "done", "kind": "work", "labels": ["exec:pair"]}],
                   "issue_type": "Task"}
    assert seen[0] == "https://example.atlassian.net/rest/api/3/issue/KAN-315?fields=status,labels,issuetype,issuelinks"
    assert not any("KAN-320" in u for u in seen)  # a Decision's link summary is enough; no second read
    errs = wsp.check_ticket(got, "KAN-315")
    assert any("KAN-320" in e for e in errs) and any("KAN-330" in e for e in errs)
    assert not any("KAN-340" in e for e in errs)


@pytest.mark.parametrize("cat, itype, want", [("done", "Story", ("done", "work")), ("new", "Epic", ("todo", "epic")),
                                              ("weird", "Bug", ("in_progress", "work"))])
def test_jira_cloud_categories_and_kinds(cat, itype, want):
    r, _ = provider({"KAN-1": jira("KAN-1", cat, "S", itype)})
    got = r.read("KAN-1")
    assert (got["category"], got["kind"]) == want


def test_jira_cloud_errors():
    r, _ = provider({})
    with pytest.raises(tracker.TicketMissing, match="HTTP 404"):
        r.read("KAN-1")
    r, _ = provider({}, {"KAN-1": ValueError("Expecting value: line 1 column 1")})  # an SSO page, not JSON
    with pytest.raises(tracker.TrackerUnreachable):
        r.read("KAN-1")
    r, _ = provider({}, {"KAN-1": urllib.error.URLError("timed out")})
    with pytest.raises(tracker.TrackerUnreachable):
        r.read("KAN-1")
    r, _ = provider({}, {"KAN-1": http.client.IncompleteRead(b"{")})  # the connection cut mid-answer
    with pytest.raises(tracker.TrackerUnreachable):
        r.read("KAN-1")
    r, _ = provider({"KAN-1": {"errorMessages": []}})
    with pytest.raises(tracker.TrackerUnreachable, match="not an issue"):
        r.read("KAN-1")


def test_jira_cloud_fails_on_a_blocker_it_cannot_read():
    hidden = jira("KAN-9", "new", "To Do", "Task")
    me = jira("KAN-1", labels=["exec:pair"], links=[blocks(hidden)])
    err = urllib.error.HTTPError("u", 403, "Forbidden", None, None)  # type: ignore[arg-type]
    r, _ = provider({"KAN-1": me}, {"KAN-9": err})
    with pytest.raises(tracker.BlockerUnreadable, match=r"KAN-9 blocks it and could not be read \(HTTP 403\)"):
        r.read("KAN-1")


def test_jira_cloud_judges_a_moved_ticket_under_the_key_asked_for():
    moved = jira("OPS-12", "done", "Done", "Story", ["exec:pair"])  # Jira answers KAN-1 with the issue's new key
    r, _ = provider({"KAN-1": moved})
    got = r.read("KAN-1")
    assert got["key"] == "KAN-1" and any("is Done" in e for e in wsp.check_ticket(got, "KAN-1"))


def test_jira_cloud_fails_on_a_blocker_that_answers_badly():
    hidden = jira("KAN-9", "new", "To Do", "Task")
    me = jira("KAN-1", labels=["exec:pair"], links=[blocks(hidden)])
    r, _ = provider({"KAN-1": me, "KAN-9": "<html>Log in</html>"})
    with pytest.raises(tracker.BlockerUnreadable, match="KAN-9 blocks it and could not be read"):
        r.read("KAN-1")


def test_jira_cloud_skips_links_it_cannot_read_as_links():
    me = jira("KAN-1", labels=["exec:pair"], links=["junk", {"type": "Blocks", "inwardIssue": "KAN-2"},
                                                   {"type": {"name": "Blocks"}, "inwardIssue": {"key": 5}}])
    me["fields"]["status"] = "weird"
    r, _ = provider({"KAN-1": me})
    got = r.read("KAN-1")
    assert got["blocked_by"] == [] and got["category"] == "in_progress"


def test_providers_are_built_in_only():
    assert set(tracker.PROVIDERS) == {"jira-cloud"}
    reader, why = tracker.from_inputs(lambda k: "")
    assert reader is None and "jira-cloud needs jira-base-url, jira-user, jira-token" in why


def test_issue_type_is_optional_in_the_normalised_shape():
    # KAN-373: org gates with `when: issue_types` read it; a provider that doesn't give it reads as unknown (None)
    base = {"key": "KAN-1", "category": "todo", "kind": "work", "labels": [], "blocked_by": []}
    assert tracker.normalised(base, "KAN-1")["issue_type"] is None
    assert tracker.normalised({**base, "issue_type": ""}, "KAN-1")["issue_type"] is None
    assert tracker.normalised({**base, "issue_type": "Change Request"}, "KAN-1")["issue_type"] == "Change Request"


def test_jira_cloud_gives_the_issue_type_name():
    r, _ = provider({"KAN-1": jira("KAN-1", itype="Change Request")})
    assert r.read("KAN-1")["issue_type"] == "Change Request"


# --- the jira-cloud provider's gate tickets (rule 7, KAN-538) --------------------------------------------------------

def test_jira_cloud_reads_a_gate_ticket():
    issue = {"key": "SRE-7", "fields": {
        "project": {"key": "SRE"}, "issuetype": {"name": "Change Request"}, "status": {"name": "Approved"},
        "issuelinks": [{"outwardIssue": {"key": "KAN-1"}}, {"inwardIssue": {"key": "KAN-2"}}, "junk"],
        "description": {"type": "doc", "content": [{"type": "text", "text": "https://github.com/o/r/pull/7"}]},
        "customfield_10050": [{"value": "Approved"}, {"name": "x"}], "customfield_2": None}}
    r, seen = provider({"SRE-7": issue})
    got = r.gate_issue("SRE-7", ["customfield_2", "customfield_10050"])
    assert seen == ["https://example.atlassian.net/rest/api/3/issue/SRE-7?fields=status,project,issuetype,"
                    "issuelinks,description,customfield_10050,customfield_2"]
    assert got["project"] == "SRE" and got["issue_type"] == "Change Request" and got["status"] == "Approved"
    assert got["links"] == ["KAN-1", "KAN-2"] and "github.com/o/r/pull/7" in got["text"]
    assert got["field_values"] == {"customfield_10050": ["Approved", "x"], "customfield_2": []}
    assert "customfield_9" not in r.gate_issue("SRE-7", ["customfield_9"])["field_values"]  # not returned: absent


def test_jira_cloud_gate_ticket_errors():
    r, _ = provider({})
    with pytest.raises(tracker.TicketMissing, match="HTTP 404"):
        r.gate_issue("SRE-7")
    r, _ = provider({}, {"SRE-7": ValueError("Expecting value")})  # an SSO page
    with pytest.raises(tracker.TrackerUnreachable):
        r.gate_issue("SRE-7")
    r, _ = provider({"SRE-7": {"errorMessages": []}})
    with pytest.raises(tracker.TrackerUnreachable, match="not an issue"):
        r.gate_issue("SRE-7")


def test_jira_cloud_reads_a_gate_tickets_remote_links():
    r, seen = provider({"SRE-7/remotelink": [{"object": {"url": "https://github.com/o/r/pull/7"}}]})
    assert "https://github.com/o/r/pull/7" in r.gate_links("SRE-7")
    assert seen == ["https://example.atlassian.net/rest/api/3/issue/SRE-7/remotelink"]
    r, _ = provider({}, {"SRE-7/remotelink": urllib.error.URLError("down")})
    with pytest.raises(tracker.TrackerUnreachable):
        r.gate_links("SRE-7")
