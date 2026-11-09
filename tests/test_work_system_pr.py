"""The work-system PR check (actions/work-system-pr): rules over the PR payload and the Jira ticket."""

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CHECK = ROOT / "actions/work-system-pr/check.py"
spec = importlib.util.spec_from_file_location("work_system_pr", CHECK)
wsp = importlib.util.module_from_spec(spec)
sys.modules["work_system_pr"] = wsp  # dataclasses look the module up
spec.loader.exec_module(wsp)

BODY = "## What and why\nAdds the gate.\n\nJira: KAN-315\nDocs: actions/work-system-pr/README.md\n"


def pr(title="KAN-315: add the PR gate", body=BODY, branch="KAN-315-work-system-layer", labels=(), author="sean"):
    return {"number": 7, "title": title, "body": body, "head": {"ref": branch},
            "labels": [{"name": n} for n in labels], "user": {"login": author}}


def test_passes_with_the_contract():
    r = wsp.check_pr(pr(), [])
    assert r.errors == [] and r.warnings == [] and r.key == "KAN-315"


def test_cloud_branch_only_warns():
    r = wsp.check_pr(pr(branch="claude/wizardly-pascal-qolknc"), [])
    assert r.errors == [] and len(r.warnings) == 1


@pytest.mark.parametrize("title", ["add the PR gate", "feat: KAN-315 add the gate", "kan-315: lower case"])
def test_title_needs_the_key_first(title):
    assert any("title must start" in e for e in wsp.check_pr(pr(title=title), []).errors)


def test_bracketed_key_is_accepted():
    assert wsp.check_pr(pr(title="[KAN-315] add the gate"), []).errors == []


def test_tracker_line_required_and_must_match():
    assert any("Jira: KAN-315" in e for e in wsp.check_pr(pr(body="Docs: x"), []).errors)
    assert any("must name the title's key" in e for e in
               wsp.check_pr(pr(body="Jira: KAN-999\nDocs: x"), []).errors)


def test_docs_line_required_with_a_reason():
    assert any("Docs:" in e for e in wsp.check_pr(pr(body="Jira: KAN-315"), []).errors)
    assert any("must say why" in e for e in wsp.check_pr(pr(body="Jira: KAN-315\nDocs: none needed"), []).errors)
    assert wsp.check_pr(pr(body="Jira: KAN-315\nDocs: none needed - internal refactor"), []).errors == []


def test_docs_line_can_be_turned_off():
    assert wsp.check_pr(pr(body="Jira: KAN-315"), [], require_docs=False).errors == []


def test_decision_needs_an_adr_that_names_it():
    body = BODY + "Decision: KAN-240\n"
    assert any("no ADR" in e for e in wsp.check_pr(pr(body=body), [{"filename": "src/x.py", "patch": ""}]).errors)
    wrong = [{"filename": "docs/decisions/0009-x.md", "status": "added", "patch": "+# 9. Retry\n+Decision: KAN-1"}]
    assert any("mentions KAN-240" in e for e in wsp.check_pr(pr(body=body), wrong).errors)
    right = [{"filename": "docs/decisions/0009-x.md", "status": "added", "patch": "+Decided in KAN-240."}]
    assert wsp.check_pr(pr(body=body), right).errors == []


def test_decision_without_file_list_warns():
    r = wsp.check_pr(pr(body=BODY + "Decision: KAN-240\n"), None)
    assert r.errors == [] and any("ADR" in w for w in r.warnings)


@pytest.mark.parametrize("kw", [{"labels": ["no-ticket"]}, {"author": "dependabot[bot]"}])
def test_exemptions(kw):
    r = wsp.check_pr(pr(title="bump requests", body="", **kw), [])
    assert r.exempt and r.errors == []


def issue(cat="indeterminate", name="In Progress", itype="Story", labels=("lane:pair",)):
    return {"fields": {"status": {"name": name, "statusCategory": {"key": cat}}, "issuetype": {"name": itype},
                       "labels": list(labels)}}


def test_ticket_ok():
    assert wsp.check_ticket(issue(), [], "KAN-315") == []


@pytest.mark.parametrize("kw, words", [
    ({"cat": "done", "name": "Done"}, "is Done"),
    ({"cat": "done", "name": "Wont Do"}, "is Wont Do"),
    ({"itype": "Epic"}, "is a epic"),
    ({"itype": "Decision"}, "is a decision"),
    ({"labels": ("repo:hangar",)}, "no execution label"),
    ({"itype": "Task", "labels": ("type:decision", "exec:human")}, "is a decision"),
])
def test_ticket_rules(kw, words):
    assert any(words in e for e in wsp.check_ticket(issue(**kw), [], "KAN-315"))


def test_exec_labels_count_as_laned():
    assert wsp.check_ticket(issue(labels=("exec:agent",)), [], "KAN-315") == []


def test_task_decision_blocks_like_a_decision():
    d = {"key": "KAN-330", "fields": {"issuetype": {"name": "Task"}, "labels": ["type:decision"],
                                      "status": {"statusCategory": {"key": "new"}}}}
    assert any("KAN-330" in e for e in wsp.check_ticket(issue(), [d], "KAN-315"))


def test_open_blocking_decision_fails_and_answered_one_passes():
    open_d = {"key": "KAN-320", "fields": {"issuetype": {"name": "Decision"}, "status": {"statusCategory": {"key": "new"}}}}
    done_d = {"key": "KAN-321", "fields": {"issuetype": {"name": "Decision"}, "status": {"statusCategory": {"key": "done"}}}}
    assert any("KAN-320" in e for e in wsp.check_ticket(issue(), [open_d], "KAN-315"))
    assert wsp.check_ticket(issue(), [done_d], "KAN-315") == []


def test_main_on_an_event_file(tmp_path):
    ev = tmp_path / "event.json"
    ev.write_text(json.dumps({"pull_request": pr(title="no key here")}))
    env = {**os.environ, "GITHUB_EVENT_PATH": str(ev), "GITHUB_REPOSITORY": "o/r", "GITHUB_API_URL": "http://127.0.0.1:9",
           "GITHUB_STEP_SUMMARY": str(tmp_path / "summary.md")}
    r = subprocess.run([sys.executable, str(CHECK)], env=env, capture_output=True, text=True)
    assert r.returncode == 1 and "::error::" in r.stdout
    assert "Work-system PR check" in (tmp_path / "summary.md").read_text()
    ev.write_text(json.dumps({"pull_request": pr()}))
    r = subprocess.run([sys.executable, str(CHECK)], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
