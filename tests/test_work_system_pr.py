"""The work-system PR check (actions/work-system-pr): rules over the PR payload and the Jira ticket."""

import base64
import email.message
import http.server
import importlib.util
import json
import os
import subprocess
import sys
import threading
import urllib.error
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CHECK = ROOT / "actions/work-system-pr/check.py"
spec = importlib.util.spec_from_file_location("work_system_pr", CHECK)
wsp = importlib.util.module_from_spec(spec)
sys.modules["work_system_pr"] = wsp  # dataclasses look the module up
spec.loader.exec_module(wsp)

PR_URL = "https://github.com/o/r/pull/7"
BASE_SHA = "b" * 40
HEAD_SHA = "h" * 40
BODY = "## What and why\nAdds the gate.\n\nJira: KAN-315\nDocs: actions/work-system-pr/README.md\n"


def pr(title="KAN-315: add the PR gate", body=BODY, branch="KAN-315-work-system-layer", labels=(), author="sean"):
    return {"number": 7, "title": title, "body": body, "head": {"ref": branch, "sha": HEAD_SHA}, "html_url": PR_URL,
            "base": {"sha": BASE_SHA, "ref": "main"},
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


def issue(cat="in_progress", name="In Progress", kind="work", labels=("lane:pair",), blocked_by=()):
    """A ticket as tracker.py normalises it (KAN-437)."""
    return {"key": "KAN-315", "status": name, "category": cat, "kind": kind, "labels": list(labels),
            "blocked_by": list(blocked_by)}


def test_ticket_ok():
    assert wsp.check_ticket(issue(), "KAN-315") == []


@pytest.mark.parametrize("kw, words", [
    ({"cat": "done", "name": "Done"}, "is Done"),
    ({"cat": "done", "name": "Wont Do"}, "is Wont Do"),
    ({"kind": "epic"}, "is a epic"),
    ({"kind": "decision"}, "is a decision"),
    ({"labels": ("repo:hangar",)}, "no execution label"),
    ({"labels": ("type:decision", "exec:human")}, "is a decision"),
])
def test_ticket_rules(kw, words):
    assert any(words in e for e in wsp.check_ticket(issue(**kw), "KAN-315"))


def test_exec_labels_count_as_laned():
    assert wsp.check_ticket(issue(labels=("exec:agent",)), "KAN-315") == []


def test_task_decision_blocks_like_a_decision():
    d = {"key": "KAN-330", "kind": "work", "labels": ["type:decision"], "category": "todo"}
    assert any("KAN-330" in e for e in wsp.check_ticket(issue(blocked_by=[d]), "KAN-315"))


def test_open_blocking_decision_fails_and_answered_one_passes():
    open_d = {"key": "KAN-320", "kind": "decision", "labels": [], "category": "todo"}
    done_d = {"key": "KAN-321", "kind": "decision", "labels": [], "category": "done"}
    assert any("KAN-320" in e for e in wsp.check_ticket(issue(blocked_by=[open_d]), "KAN-315"))
    assert wsp.check_ticket(issue(blocked_by=[done_d]), "KAN-315") == []


def test_a_blocking_work_item_does_not_block():
    w = {"key": "KAN-322", "kind": "work", "labels": ["exec:pair"], "category": "todo"}
    assert wsp.check_ticket(issue(blocked_by=[w]), "KAN-315") == []


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


# --- rule 7: the org's merge gates (org.yaml, team-harness.org/v1) ---------------------------------------------------

ORG_YAML = """\
schema: team-harness.org/v1
name: test-co
placeholder: false
params:
  tracker: "the WORKPROJ project on COMPANY-SITE.atlassian.net"
ticket_types:
  - {id: work, project: WORKPROJ, issue_type: Story, role: work}
  - {id: sre-approval, project: SREPROJ, issue_type: Task, role: approval,
     summary: "SRE approval: {work_key} {pr_title}"}
  - {id: infosec-review, project: SECPROJ, issue_type: Task, role: approval}
  - {id: data-review, project: DATAPROJ, issue_type: Task, role: approval}
  - {id: ui-review, project: UIPROJ, issue_type: Task, role: approval}
gates:
  - id: sre
    ticket: sre-approval
    when: always
    pr_line: SRE
    links: [pr, work]
    filed_by: agent
    approved_statuses: [Approved, Done]
  - id: infosec
    ticket: infosec-review
    when: {paths: ["src/auth/*", "deploy/**"]}
    pr_line: Infosec
    links: [repo, work]
    filed_by: agent
  - id: data
    ticket: data-review
    when: {labels: [data-change]}
    pr_line: Data
    filed_by: person
  - id: ui
    ticket: ui-review
    when: {paths: ["web/*"], labels: [ui]}
    pr_line: UI
    filed_by: agent
review_request:
  room: "the team's review room"
  template: |
    Review please: {pr_url}
    {gate_lines}
"""


@pytest.fixture
def org(tmp_path):
    p = tmp_path / "org.yaml"
    p.write_text(ORG_YAML)
    return wsp.load_org(str(p))


def gated(lines="SRE: SREPROJ-7\n", **kw):
    return pr(body=BODY + lines, **kw)


def by_id(gates):
    return {g.id: g for g in gates}


def test_always_gate_needs_its_line(org):
    gates, errs, warns = wsp.check_gates(gated(lines=""), [], org)
    g = by_id(gates)
    assert g["sre"].applies and g["sre"].state == "missing"
    assert len(errs) == 1 and "'sre'" in errs[0] and "sre-approval" in errs[0] and "SREPROJ" in errs[0]
    assert "file the approval ticket" in errs[0] and warns == []
    assert [g[i].state for i in ("infosec", "data", "ui")] == ["not required"] * 3


def test_present_gate_line_passes_when_unverified_is_allowed(org):
    gates, errs, warns = wsp.check_gates(gated(), [], org, allow_unverified=True)
    assert errs == [] and by_id(gates)["sre"].state == "not checked" and by_id(gates)["sre"].key == "SREPROJ-7"
    assert any("passing it unverified" in w for w in warns)


def test_without_jira_an_approval_gate_fails_closed(org):
    # fork and Dependabot PRs get no secrets: the key prefix alone must not pass a gate that needs an approval
    gates, errs, _ = wsp.check_gates(gated(), [], org)
    assert by_id(gates)["sre"].state == "unverified"
    assert any("'sre'" in e and "no Jira credentials" in e and "allow-unverified" in e for e in errs)


def test_without_jira_a_gate_without_approved_statuses_checks_the_prefix_only(org):
    files = [{"filename": "deploy/x.yaml"}]
    gates, errs, _ = wsp.check_gates(gated("SRE: SREPROJ-7\nInfosec: SECPROJ-8\n"), files, org, allow_unverified=True)
    assert errs == [] and by_id(gates)["infosec"].state == "not checked"


@pytest.mark.parametrize("value", ["pending", "Pending - filing after review"])
def test_pending_gate_line_fails(org, value):
    gates, errs, _ = wsp.check_gates(gated(lines=f"SRE: {value}\n"), [], org)
    assert by_id(gates)["sre"].state == "pending" and any("pending" in e and "'sre'" in e for e in errs)


def test_gate_line_that_is_not_a_key_fails(org):
    _, errs, _ = wsp.check_gates(gated(lines="SRE: ask the SRE team\n"), [], org)
    assert any("not a ticket key" in e for e in errs)


def test_gate_key_in_the_wrong_project_fails_offline(org):
    _, errs, _ = wsp.check_gates(gated(lines="SRE: SECPROJ-7\n"), [], org)
    assert any("SECPROJ-7 is not in SREPROJ" in e for e in errs)


def test_commented_gate_lines_do_not_count(org):
    _, errs, _ = wsp.check_gates(gated(lines="<!-- SRE: SREPROJ-7   Infosec: SECPROJ-8 -->\n"), [], org)
    assert any("'sre'" in e for e in errs)


def test_paths_gate_applies_on_a_matching_file(org):
    files = [{"filename": "deploy/prod/values.yaml"}]
    gates, errs, _ = wsp.check_gates(gated(), files, org)
    assert by_id(gates)["infosec"].applies and any("'infosec'" in e and "SECPROJ" in e for e in errs)
    gates, errs, _ = wsp.check_gates(gated("SRE: SREPROJ-7\nInfosec: SECPROJ-8\n"), files, org, allow_unverified=True)
    assert errs == [] and by_id(gates)["infosec"].state == "not checked"


def test_paths_gate_matches_a_rename_source(org):
    gates, _, _ = wsp.check_gates(gated(), [{"filename": "lib/x.py", "previous_filename": "src/auth/x.py"}], org)
    assert by_id(gates)["infosec"].applies


def test_paths_gate_skips_other_files_and_applies_when_files_are_unknown(org):
    gates, errs, _ = wsp.check_gates(gated(), [{"filename": "README.md"}], org, allow_unverified=True)
    assert not by_id(gates)["infosec"].applies and errs == []
    gates, errs, _ = wsp.check_gates(gated(), None, org)
    assert by_id(gates)["infosec"].applies and any("'infosec'" in e for e in errs)


def test_labels_gate_and_person_filed_message(org):
    gates, errs, _ = wsp.check_gates(gated(labels=["data-change"]), [], org)
    assert by_id(gates)["data"].applies
    msg = next(e for e in errs if "'data'" in e)
    assert "a person files that ticket" in msg and "DATAPROJ" in msg
    _, errs, _ = wsp.check_gates(gated("SRE: SREPROJ-7\nData: DATAPROJ-3\n", labels=["data-change"]), [], org,
                                 allow_unverified=True)
    assert errs == []


def test_paths_or_labels_gate_applies_on_either(org):
    assert by_id(wsp.check_gates(gated(labels=["ui"]), [], org)[0])["ui"].applies
    assert by_id(wsp.check_gates(gated(), [{"filename": "web/app.js"}], org)[0])["ui"].applies


def test_gates_hold_on_an_exempt_pr(org):
    p = pr(title="bump requests", body="", labels=["no-ticket"])
    assert wsp.check_pr(p, []).exempt
    assert any("'sre'" in e for e in wsp.check_gates(p, [], org)[1])


def test_placeholder_org_warns_and_enforces_nothing(tmp_path):
    p = tmp_path / "org.yaml"
    p.write_text(ORG_YAML.replace("placeholder: false", "placeholder: true"))
    gates, errs, warns = wsp.check_gates(gated(lines=""), [], wsp.load_org(str(p)))
    assert errs == [] and any("placeholder" in w for w in warns)
    assert by_id(gates)["sre"].state == "not enforced"


def test_org_file_may_be_json(tmp_path):
    import yaml
    p = tmp_path / "org.json"
    p.write_text(json.dumps(yaml.safe_load(ORG_YAML)))
    assert wsp.load_org(str(p))["name"] == "test-co"


def test_without_pyyaml_json_works_and_yaml_is_a_clear_error(tmp_path, monkeypatch):
    import yaml
    monkeypatch.setitem(sys.modules, "yaml", None)  # import yaml now raises ImportError
    j = tmp_path / "org.json"
    j.write_text(json.dumps(yaml.safe_load(ORG_YAML)))
    assert wsp.load_org(str(j))["name"] == "test-co"
    y = tmp_path / "org.yaml"
    y.write_text(ORG_YAML)
    with pytest.raises(wsp.OrgError, match="PyYAML is not installed"):
        wsp.load_org(str(y))


@pytest.mark.parametrize("text, words", [
    ("schema: [unclosed\n", "not valid YAML"),
    ("- just a list\n", "mapping at the top level"),
    (ORG_YAML.replace("team-harness.org/v1", "team-harness.org/v9"), "schema must be"),
    (ORG_YAML.replace("    pr_line: SRE\n", "    pr_line: SRE\n    sla: 2d\n"), "unknown key(s) sla"),
    (ORG_YAML.replace("ticket: sre-approval", "ticket: sre-approvl"), "unknown ticket type 'sre-approvl'"),
    (ORG_YAML.replace("ticket: sre-approval", "ticket: work"), "not 'approval'"),
    (ORG_YAML.replace("pr_line: Infosec", "pr_line: SRE"), "used by two gates"),
    (ORG_YAML.replace("id: infosec\n", "id: sre\n"), "gate id 'sre' is used twice"),
    (ORG_YAML.replace("when: always", "when: sometimes"), "when must be"),
    (ORG_YAML.replace('when: {labels: [data-change]}', 'when: {branches: [main]}'), "unknown key(s) branches"),
    (ORG_YAML.replace("filed_by: person", "filed_by: robot"), "filed_by must be"),
    (ORG_YAML.replace("links: [pr, work]", "links: [pr, wiki]"), "links has wiki"),
    (ORG_YAML.replace("approved_statuses: [Approved, Done]", "approved_statuses: Approved"), "approved_statuses"),
    # in step with scripts/sync_shared.py (PR 8)
    (ORG_YAML.replace("pr_line: Data", "pr_line: Docs"), "one of the PR check's own lines"),
    (ORG_YAML.replace("pr_line: Data", "pr_line: jira"), "one of the PR check's own lines"),
    (ORG_YAML.replace("pr_line: Data", "pr_line: Decision"), "one of the PR check's own lines"),
    (ORG_YAML.replace("    when: always\n", ""), "needs a 'when'"),
    (ORG_YAML.replace("    filed_by: person\n", ""), "needs a non-empty 'filed_by'"),
    (ORG_YAML[:ORG_YAML.index("gates:")] + "gates: []\n", "at least one gate"),
    (ORG_YAML[:ORG_YAML.index("gates:")], "at least one gate"),
])
def test_invalid_org_file_is_a_clear_error(tmp_path, text, words):
    p = tmp_path / "org.yaml"
    p.write_text(text)
    with pytest.raises(wsp.OrgError) as e:
        wsp.load_org(str(p))
    assert words in str(e.value)


def test_custom_tracker_line_is_reserved_too(tmp_path):
    p = tmp_path / "org.yaml"
    p.write_text(ORG_YAML.replace("pr_line: Data", "pr_line: Ticket"))
    assert wsp.load_org(str(p))["name"] == "test-co"
    with pytest.raises(wsp.OrgError, match="own lines"):
        wsp.load_org(str(p), tracker_line="Ticket")


def test_missing_org_file_is_a_clear_error(tmp_path):
    with pytest.raises(wsp.OrgError, match="could not be read"):
        wsp.load_org(str(tmp_path / "nope.yaml"))


def jira_issue(key, project, status, issue_type="Task", links=("KAN-315",), description: str | None = PR_URL):
    return {"key": key, "fields": {
        "project": {"key": project}, "status": {"name": status}, "issuetype": {"name": issue_type},
        "issuelinks": [{"type": {"name": "Relates"}, "outwardIssue": {"key": k}} for k in links],
        "description": {"type": "doc", "content": [{"type": "paragraph", "content": [
            {"type": "text", "text": f"Approve {description}"}]}]} if description else None}}


def fake_jira(issues, remote=None):
    def fetch(key):
        if key not in issues:
            raise urllib.error.HTTPError(f"https://jira/{key}", 404, "Not Found", {}, None)
        return issues[key]
    return fetch


def jira_gates(p, org, issues, remote=None, **kw):
    kw.setdefault("work_key", "KAN-315")
    return wsp.check_gates(p, kw.pop("files", []), org, fetch=fake_jira(issues),
                           remote_links=(lambda key: (remote or {}).get(key, [])), **kw)


def test_jira_gate_ticket_approved_passes(org):
    gates, errs, _ = jira_gates(gated(), org, {"SREPROJ-7": jira_issue("SREPROJ-7", "SREPROJ", "Approved")})
    assert errs == [] and by_id(gates)["sre"].state == "checked"


def test_jira_gate_ticket_not_yet_approved_fails(org):
    gates, errs, _ = jira_gates(gated(), org, {"SREPROJ-7": jira_issue("SREPROJ-7", "SREPROJ", "In Review")})
    assert any("SREPROJ-7 is In Review" in e and "Approved or Done" in e for e in errs)
    assert by_id(gates)["sre"].state == "not approved"


def test_jira_gate_ticket_in_another_project_fails(org):
    # moved since it was linked
    _, errs, _ = jira_gates(gated(), org, {"SREPROJ-7": jira_issue("SECPROJ-12", "SECPROJ", "Approved")})
    assert any("is in SECPROJ, not SREPROJ" in e for e in errs)


def test_jira_gate_ticket_missing_fails(org):
    _, errs, _ = jira_gates(gated(), org, {})
    assert any("SREPROJ-7 could not be read from Jira (HTTP 404)" in e for e in errs)


# --- rule 7 through the tracker seam (KAN-538) --------------------------------------------------------------------------

class Desk:
    """A tracker that isn't Jira: its own record layout, no HTTP, mapped to the normalised gate ticket by itself."""

    label = "Desk"

    def __init__(self, records, web_links=None, fail=None):
        self.records, self.web_links, self.fail, self.asked = records, web_links or {}, fail, []

    def gate_issue(self, key, fields):
        self.asked.append((key, list(fields)))
        if self.fail:
            raise self.fail
        if key not in self.records:
            raise wsp.tracker.TicketMissing("no such record")
        r = self.records[key]
        return {"key": key, "project": r["queue"], "issue_type": r["kind"], "status": r["state"],
                "links": r.get("related", []), "text": r.get("body", ""),
                "field_values": {f: r["extra"][f] for f in fields if f in r.get("extra", {})}}

    def gate_links(self, key):
        return " ".join(self.web_links.get(key, []))


def desk(state="Approved", **kw):
    return {"queue": "SREPROJ", "kind": "Task", "state": state, "related": ["KAN-315"], "body": f"see {PR_URL}", **kw}


def test_a_gate_reads_a_tracker_that_is_not_jira(org):
    t = Desk({"SREPROJ-7": desk()})
    gates, errs, _ = wsp.check_gates(gated(), [], org, tickets=t, work_key="KAN-315")
    assert errs == [] and by_id(gates)["sre"].state == "checked" and t.asked[0][0] == "SREPROJ-7"


@pytest.mark.parametrize("record, words", [
    (desk("In Review"), "SREPROJ-7 is In Review; it must be Approved or Done"),
    (desk(related=[]), "has no issue link to the work ticket KAN-315"),
    (desk(body="nothing here"), "does not link this PR"),
    (desk(queue="OPS"), "is in OPS, not SREPROJ"),
    (desk(kind="Bug"), "is a Bug, not a Task"),
])
def test_a_tracker_that_is_not_jira_holds_the_gate(org, record, words):
    _, errs, _ = wsp.check_gates(gated(), [], org, tickets=Desk({"SREPROJ-7": record}), work_key="KAN-315")
    assert any(words in e for e in errs), errs


def test_a_tracker_that_is_not_jira_links_the_pr_through_its_web_links(org):
    t = Desk({"SREPROJ-7": desk(body="")}, web_links={"SREPROJ-7": [PR_URL]})
    _, errs, _ = wsp.check_gates(gated(), [], org, tickets=t, work_key="KAN-315")
    assert errs == []


def test_a_tracker_that_is_not_jira_is_named_in_its_messages(org):
    _, errs, _ = wsp.check_gates(gated(), [], org, tickets=Desk({}), work_key="KAN-315")
    assert any("SREPROJ-7 could not be read from Desk (no such record)" in e for e in errs)
    _, errs, _ = wsp.check_gates(gated(), [], org, tickets=None, tracker_label="Desk", work_key="KAN-315")
    assert any("no Desk credentials" in e for e in errs)


@pytest.mark.parametrize("fail, answer", [
    (wsp.tracker.TrackerUnreachable("timed out"), None),
    (RuntimeError("a provider bug"), None),  # never passes the gate
    (None, {"key": "SREPROJ-7", "project": "SREPROJ"}),  # not the normalised shape
    (None, {**desk(), "key": "SREPROJ-9"}),  # answered for another ticket
])
def test_a_tracker_that_answers_badly_fails_the_gate_closed(org, fail, answer):
    class Bad(Desk):
        def gate_issue(self, key, fields):
            if fail:
                raise fail
            return answer
    gates, errs, _ = wsp.check_gates(gated(), [], org, tickets=Bad({}), work_key="KAN-315")
    assert by_id(gates)["sre"].state == "unverified" and errs, errs
    gates, errs, warns = wsp.check_gates(gated(), [], org, tickets=Bad({}), work_key="KAN-315",
                                         allow_unverified=True)
    assert errs == [] and by_id(gates)["sre"].state == "not checked" and warns


def test_a_tracker_that_is_not_jira_reads_the_approved_field(org2):
    ess = {"queue": "ESSPROJ", "kind": "Task", "state": "Open", "extra": {"customfield_10050": ["Approved"]}}
    t = Desk({"KAN-315": {"queue": "KAN", "kind": "Story", "state": "In Progress", "body": PR_URL},
              "SECPROJ-8": {"queue": "SECPROJ", "kind": "Task", "state": "Approved", "body": "https://github.com/o/r"},
              "ESSPROJ-2": ess})
    gates, _, _ = wsp.check_gates(gated(lines=ESS), [], org2, tickets=t, work_key="KAN-315",
                                  work_issue_type="Change Request", allow_unverified=True)
    assert by_id(gates)["ess"].state == "checked" and ("ESSPROJ-2", ["customfield_10050"]) in t.asked
    ess["extra"] = {}
    gates, errs, _ = wsp.check_gates(gated(lines=ESS), [], org2, tickets=t, work_key="KAN-315",
                                     work_issue_type="Change Request", allow_unverified=True)
    assert any("Desk returned no customfield_10050 field for ESSPROJ-2" in e for e in errs), errs


def test_a_mistyped_provider_fails_the_gates_of_a_pr_without_a_ticket(tmp_path, fake_api):
    """An exempt PR names no work ticket, so rule 6 never asks for the reader; the gates still need it (KAN-538)."""
    fake_api.files(["README.md"])
    fake_api.base_org(ORG_YAML)
    r, _ = run_main(tmp_path, "Docs: none needed - typo\nSRE: SREPROJ-7\n", api=fake_api, jira=True,
                    labels=["no-ticket"], title="Fix a typo",
                    extra_env={"INPUT_TRACKER_PROVIDER": "jira-clod", "INPUT_ALLOW_UNVERIFIED": "true"})
    assert r.returncode == 1, r.stdout
    assert "::error::tracker-provider 'jira-clod' is not one of: jira-cloud; the merge gates' tickets were not read" \
        in r.stdout


def test_a_gate_ticket_with_no_project_or_key_is_in_no_project(org):
    issue = jira_issue("SREPROJ-7", "SREPROJ", "Approved")
    issue.pop("key")
    issue["fields"].pop("project")
    _, errs, _ = jira_gates(gated(), org, {"SREPROJ-7": issue})
    assert any("is in an unknown project, not SREPROJ" in e for e in errs), errs


def test_check_py_reads_no_tracker_for_rule_7():
    """The approval gates name no tracker's fields and make no tracker call: tracker.py's provider does (KAN-538)."""
    src = (Path(wsp.__file__)).read_text()
    for name in ("rest/api", "remotelink", "issuelinks", "issuetype", "statusCategory", "inwardIssue",
                 "outwardIssue", "customfield_", "JIRA_BASE_URL", "JIRA_TOKEN", "_jira_fetcher", "Basic "):
        assert name not in src, name


def test_jira_status_not_required_without_approved_statuses(org):
    files = [{"filename": "src/auth/login.py"}]
    issues = {"SREPROJ-7": jira_issue("SREPROJ-7", "SREPROJ", "Done"),
              "SECPROJ-8": jira_issue("SECPROJ-8", "SECPROJ", "Open")}
    _, errs, _ = jira_gates(gated("SRE: SREPROJ-7\nInfosec: SECPROJ-8\n"), org, issues, files=files)
    assert errs == []


@pytest.mark.parametrize("exc", [
    urllib.error.URLError("timed out"),
    TimeoutError("The read operation timed out"),
    json.JSONDecodeError("Expecting value", "<!DOCTYPE html><title>Sign in</title>", 0),  # an SSO page
    urllib.error.HTTPError("https://jira/x", 503, "Service Unavailable", email.message.Message(), None),
])
def test_jira_unreachable_fails_a_gate_with_approved_statuses(org, exc):
    def fetch(key):
        raise exc
    gates, errs, _ = wsp.check_gates(gated(), [], org, fetch=fetch, work_key="KAN-315")
    assert by_id(gates)["sre"].state in {"unverified", "invalid"} and any("'sre'" in e for e in errs)


def test_jira_unreachable_passes_only_with_allow_unverified(org):
    def fetch(key):
        raise urllib.error.URLError("timed out")
    gates, errs, warns = wsp.check_gates(gated(), [], org, fetch=fetch, work_key="KAN-315", allow_unverified=True)
    assert errs == [] and any("passing it unverified" in w for w in warns)
    # the job summary must not say a ticket it never read was checked
    assert by_id(gates)["sre"].state == "not checked"
    assert any("not checked" in line for line in wsp.gate_summary(gates))


def test_unreadable_remote_links_are_read_once_and_reported_once(tmp_path):
    # a gate that links both the PR and the repository: one failed read, one error, state unverified
    p = tmp_path / "org.yaml"
    p.write_text(ORG_YAML.replace("links: [pr, work]", "links: [pr, repo, work]"))
    org = wsp.load_org(str(p))
    calls = []

    def remote_links(key):
        calls.append(key)
        raise urllib.error.URLError("timed out")
    gates, errs, _ = wsp.check_gates(gated(), [], org, fetch=fake_jira({"SREPROJ-7": jira_issue(
        "SREPROJ-7", "SREPROJ", "Approved", description=None)}), remote_links=remote_links, work_key="KAN-315")
    assert calls == ["SREPROJ-7"] and by_id(gates)["sre"].state == "unverified"
    assert len([e for e in errs if "remote links could not be read" in e]) == 1


@pytest.mark.parametrize("text, url, hit", [
    ("PR: https://github.com/o/r/pull/7.", PR_URL, True),  # a URL that ends a sentence
    ("see https://github.com/o/r.", "https://github.com/o/r", True),
    ("https://github.com/o/r?tab=x", "https://github.com/o/r", True),
    ("https://github.com/o/r/pull/9", "https://github.com/o/r", True),
    ("https://github.com/o/r2", "https://github.com/o/r", False),
    ("https://github.com/o/r.x", "https://github.com/o/r", False),
    ("https://github.com/o/r-fork", "https://github.com/o/r", False),
    ("https://github.com/o/r%2Dfork", "https://github.com/o/r", False),
    ("https://github.com/o/r/pull/70", PR_URL, False),
    ("https://github.com/o/r/pull/7.patch", PR_URL, False),
])
def test_mentions_names_the_url_itself(text, url, hit):
    assert wsp._mentions({"description": text}, url) is hit


def test_jira_pr_link_ignores_the_case_of_the_owner_and_repository(org):
    sre = jira_issue("SREPROJ-7", "SREPROJ", "Approved", description="https://github.com/O/R/pull/7")
    _, errs, _ = jira_gates(gated(), org, {"SREPROJ-7": sre})
    assert errs == []


@pytest.mark.parametrize("answer", [["not", "an", "issue"], {"errorMessages": ["login required"]}, None])
def test_jira_answer_that_is_not_an_issue_fails_closed(org, answer):
    gates, errs, _ = wsp.check_gates(gated(), [], org, fetch=lambda key: answer, work_key="KAN-315")
    assert by_id(gates)["sre"].state == "unverified" and any("not an issue" in e for e in errs)


def test_jira_unreachable_fails_a_gate_with_links_only(org):
    # infosec sets links but no approved_statuses: only Jira can show the links, so it fails closed too
    def fetch(key):
        raise urllib.error.URLError("timed out")
    files = [{"filename": "deploy/x.yaml"}]
    gates, errs, _ = wsp.check_gates(gated("SRE: SREPROJ-7\nInfosec: SECPROJ-8\n"), files, org, fetch=fetch,
                                     work_key="KAN-315")
    assert by_id(gates)["infosec"].state == "unverified"
    assert any("'infosec'" in e and "linking the repository and the work ticket" in e for e in errs)
    assert any("'sre'" in e for e in errs)


def test_without_jira_a_gate_with_links_only_fails_closed(org):
    files = [{"filename": "deploy/x.yaml"}]
    gates, errs, _ = wsp.check_gates(gated("SRE: SREPROJ-7\nInfosec: SECPROJ-8\n"), files, org)
    assert by_id(gates)["infosec"].state == "unverified"
    assert any("'infosec'" in e and "no Jira credentials" in e for e in errs)


def test_jira_unreachable_only_warns_for_a_gate_without_approved_statuses_or_links(org):
    def fetch(key):
        raise urllib.error.URLError("timed out")
    files = [{"filename": "web/app.js"}]
    gates, errs, warns = wsp.check_gates(gated("SRE: SREPROJ-7\nUI: UIPROJ-9\n"), files, org, fetch=fetch,
                                         work_key="KAN-315")
    assert not any("'ui'" in e for e in errs) and any("'ui'" in w and "not checked" in w for w in warns)
    assert by_id(gates)["ui"].state == "not checked"


def test_jira_repo_link_is_checked(org):
    # links: [repo] used to be accepted and never checked; a ticket that names another repository fails
    files = [{"filename": "deploy/x.yaml"}]
    sre = jira_issue("SREPROJ-7", "SREPROJ", "Approved")
    other = jira_issue("SECPROJ-8", "SECPROJ", "Open", description="https://github.com/o/r-fork")
    gates, errs, _ = jira_gates(gated("SRE: SREPROJ-7\nInfosec: SECPROJ-8\n"), org,
                                {"SREPROJ-7": sre, "SECPROJ-8": other}, files=files)
    assert by_id(gates)["infosec"].state == "invalid"
    assert any("'infosec'" in e and "does not name this repository" in e and "https://github.com/o/r" in e
               for e in errs)


@pytest.mark.parametrize("where", ["description", "remote"])
@pytest.mark.parametrize("url", ["https://github.com/o/r", "https://github.com/O/R/tree/main", PR_URL])
def test_jira_repo_link_may_be_the_repository_or_a_link_into_it(org, where, url):
    files = [{"filename": "deploy/x.yaml"}]
    sec = jira_issue("SECPROJ-8", "SECPROJ", "Open", description=url if where == "description" else None)
    remote = {"SECPROJ-8": [{"object": {"url": url}}]} if where == "remote" else None
    _, errs, _ = jira_gates(gated("SRE: SREPROJ-7\nInfosec: SECPROJ-8\n"), org,
                            {"SREPROJ-7": jira_issue("SREPROJ-7", "SREPROJ", "Approved"), "SECPROJ-8": sec},
                            remote, files=files)
    assert errs == []


def test_repo_url_comes_from_the_payload_or_the_pr_url():
    assert wsp._repo_url({"html_url": PR_URL}) == "https://github.com/o/r"
    assert wsp._repo_url({"html_url": PR_URL, "base": {"repo": {"html_url": "https://ghe.example/x/y/"}}}) \
        == "https://ghe.example/x/y"
    assert wsp._repo_url({"html_url": "https://github.com/o/r/issues/7"}) == ""


def test_jira_repo_link_without_a_repository_url_fails(org):
    files = [{"filename": "deploy/x.yaml"}]
    p = gated("SRE: SREPROJ-7\nInfosec: SECPROJ-8\n")
    p["html_url"] = ""
    issues = {"SREPROJ-7": jira_issue("SREPROJ-7", "SREPROJ", "Approved", description=PR_URL),
              "SECPROJ-8": jira_issue("SECPROJ-8", "SECPROJ", "Open")}
    _, errs, _ = jira_gates(p, org, issues, files=files)
    assert any("'infosec'" in e and "does not name this repository" in e for e in errs)


@pytest.mark.parametrize("itype", ["Epic", "Story"])
def test_jira_gate_ticket_of_another_issue_type_fails(org, itype):
    gates, errs, _ = jira_gates(gated(), org, {"SREPROJ-7": jira_issue("SREPROJ-7", "SREPROJ", "Approved", itype)})
    assert by_id(gates)["sre"].state == "invalid" and any(f"is a {itype}, not a Task" in e for e in errs)


def test_jira_issue_type_compares_case_insensitively(org):
    _, errs, _ = jira_gates(gated(), org, {"SREPROJ-7": jira_issue("SREPROJ-7", "SREPROJ", "Approved", "task")})
    assert errs == []


def test_jira_gate_ticket_without_a_link_to_the_work_ticket_fails(org):
    # an old approved ticket in the right project, for other work
    old = jira_issue("SREPROJ-7", "SREPROJ", "Approved", links=("KAN-1",))
    gates, errs, _ = jira_gates(gated(), org, {"SREPROJ-7": old})
    assert by_id(gates)["sre"].state == "invalid" and any("no issue link to the work ticket KAN-315" in e for e in errs)


def test_jira_work_link_may_be_inward(org):
    issue = jira_issue("SREPROJ-7", "SREPROJ", "Approved", links=())
    issue["fields"]["issuelinks"] = [{"type": {"name": "Relates"}, "inwardIssue": {"key": "KAN-315"}}]
    assert jira_gates(gated(), org, {"SREPROJ-7": issue})[1] == []


def test_jira_work_link_needs_a_work_key(org):
    issue = jira_issue("SREPROJ-7", "SREPROJ", "Approved")
    _, errs, _ = jira_gates(gated(), org, {"SREPROJ-7": issue}, work_key=None)
    assert any("names no work ticket" in e for e in errs)


def test_jira_pr_link_may_be_a_remote_link(org):
    issue = jira_issue("SREPROJ-7", "SREPROJ", "Approved", description=None)
    _, errs, _ = jira_gates(gated(), org, {"SREPROJ-7": issue})
    assert any("does not link this PR" in e and PR_URL in e for e in errs)
    remote = {"SREPROJ-7": [{"object": {"url": PR_URL, "title": "PR 7"}}]}
    assert jira_gates(gated(), org, {"SREPROJ-7": issue}, remote)[1] == []


def test_jira_pr_link_to_another_pr_fails(org):
    issue = jira_issue("SREPROJ-7", "SREPROJ", "Approved", description="https://github.com/o/r/pull/70")
    remote = {"SREPROJ-7": [{"object": {"url": "https://github.com/o/r/pull/6"}}]}
    _, errs, _ = jira_gates(gated(), org, {"SREPROJ-7": issue}, remote)
    assert any("does not link this PR" in e for e in errs)


def test_jira_remote_links_unreadable_fails_closed(org):
    issue = jira_issue("SREPROJ-7", "SREPROJ", "Approved", description=None)

    def remote(key):
        raise urllib.error.URLError("timed out")
    gates, errs, _ = wsp.check_gates(gated(), [], org, fetch=fake_jira({"SREPROJ-7": issue}), remote_links=remote,
                                     work_key="KAN-315")
    assert by_id(gates)["sre"].state == "unverified" and any("remote links could not be read" in e for e in errs)


# --- when: labels and paths ------------------------------------------------------------------------------------------

@pytest.mark.parametrize("label", ["Data-Change", "DATA-CHANGE"])
def test_labels_gate_is_case_insensitive(org, label):
    assert by_id(wsp.check_gates(gated(labels=[label]), [], org)[0])["data"].applies


def test_labels_gate_applies_on_the_work_tickets_jira_label(org):
    gates, _, _ = wsp.check_gates(gated(), [], org, work_labels=["exec:agent", "Data-Change"])
    assert by_id(gates)["data"].applies and "work ticket label Data-Change" in by_id(gates)["data"].why
    assert not by_id(wsp.check_gates(gated(), [], org, work_labels=["exec:agent"])[0])["data"].applies


def test_labels_gate_applies_when_the_work_tickets_labels_are_unknown(org):
    gates, _, _ = wsp.check_gates(gated(), [], org, work_labels=None)
    assert by_id(gates)["data"].applies and "could not be read" in by_id(gates)["data"].why


@pytest.mark.parametrize("path, pattern, hit", [
    ("Dockerfile", "**/Dockerfile", True),
    ("svc/Dockerfile", "**/Dockerfile", True),
    ("deploy/values.yaml", "deploy/**/*.yaml", True),
    ("deploy/prod/values.yaml", "deploy/**/*.yaml", True),
    ("a/b/c/d.tf", "a/**/c/**/*.tf", True),
    ("a/c/d.tf", "a/**/c/**/*.tf", True),
    ("Dockerfile.dev", "**/Dockerfile", False),
    ("README.md", "deploy/**", False),
])
def test_double_star_matches_zero_directories(path, pattern, hit):
    assert wsp.path_matches(path, pattern) is hit


def test_paths_gate_matches_a_root_file(tmp_path):
    p = tmp_path / "org.yaml"
    p.write_text(ORG_YAML.replace('"deploy/**"', '"**/Dockerfile"'))
    gates, _, _ = wsp.check_gates(gated(), [{"filename": "Dockerfile"}], wsp.load_org(str(p)))
    assert by_id(gates)["infosec"].applies


@pytest.mark.parametrize("hidden", ["<!-- SRE: SREPROJ-7\n", "text\n<!--\nSRE: SREPROJ-7\nmore"])
def test_unclosed_comment_hides_the_rest_of_the_body(org, hidden):
    _, errs, _ = wsp.check_gates(gated(lines=hidden), [], org, allow_unverified=True)
    assert any("'sre'" in e and "needs a 'SRE: <KEY>' line" in e for e in errs)


def test_gate_summary_lists_every_gate(org):
    gates, _, _ = wsp.check_gates(gated(labels=["data-change"]), [], org)
    table = "\n".join(wsp.gate_summary(gates))
    for words in ("| sre | `SRE: SREPROJ-7` | Task in SREPROJ |", "| infosec |", "a person files it", "missing",
                  "not required"):
        assert words in table


# --- main(): the org file from the base commit, and Jira, through a local fake GitHub and Jira --------------------

ORG_PATH = "orgs/test-co/org.yaml"


class FakeApi:
    """GitHub (PR files, contents at a ref) and Jira (issues, remote links) on one local port. Routes map a path to
    (status, body); a body that is not a str is sent as JSON."""

    def __init__(self):
        self.routes: dict[str, tuple[int, object]] = {}
        self.seen: list[str] = []
        api = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                api.seen.append(self.path)
                status, body = api.routes.get(self.path, (404, {"message": "Not Found"}))
                data = body.encode() if isinstance(body, str) else json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "text/html" if isinstance(body, str) else "application/json")
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, format: str, *args: object) -> None:
                pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def files(self, names):
        names = [*names, "changes/KAN-315.md"]  # the changelog fragment rule 8 asks for (tests/test_parallel_prs.py)
        self.routes["/repos/o/r/pulls/7/files?per_page=100&page=1"] = (200, [{"filename": n} for n in names])

    def base_org(self, text):
        content = base64.b64encode(text.encode()).decode()
        self.routes[f"/repos/o/r/contents/{ORG_PATH}?ref={BASE_SHA}"] = (200, {"encoding": "base64", "content": content})

    def issue(self, key, body, status=200):
        self.routes[f"/rest/api/3/issue/{key}?fields=status,project,issuetype,issuelinks,description"] = (status, body)


@pytest.fixture
def fake_api():
    api = FakeApi()
    yield api
    api.server.shutdown()


def run_main(tmp_path, body, org_text=ORG_YAML, org_file=ORG_PATH, api=None, jira=False, extra_env=None,
             labels=(), title="KAN-315: add the PR gate"):
    (tmp_path / "orgs/test-co").mkdir(parents=True, exist_ok=True)
    (tmp_path / "orgs/test-co/org.yaml").write_text(org_text)
    ev = tmp_path / "event.json"
    ev.write_text(json.dumps({"pull_request": pr(title=title, body=body, labels=labels)}))
    summary = tmp_path / "summary.md"
    summary.write_text("")
    url = api.url if api else "http://127.0.0.1:9"
    env = {**os.environ, "GITHUB_EVENT_PATH": str(ev), "GITHUB_REPOSITORY": "o/r", "GITHUB_API_URL": url,
           "GITHUB_STEP_SUMMARY": str(summary), "GITHUB_WORKSPACE": str(tmp_path), "INPUT_ORG_FILE": org_file}
    if jira:
        env.update(INPUT_JIRA_BASE_URL=url, INPUT_JIRA_USER="bot@example.com", INPUT_JIRA_TOKEN="t")
    env.update(extra_env or {})
    r = subprocess.run([sys.executable, str(CHECK)], env=env, capture_output=True, text=True, check=False)
    return r, summary.read_text()


GATE_LINES = "SRE: SREPROJ-7\nInfosec: SECPROJ-8\nUI: UIPROJ-9\n"


def test_main_enforces_gates_from_the_org_file(tmp_path, fake_api):
    fake_api.files(["README.md"])
    fake_api.base_org(ORG_YAML)
    r, summary = run_main(tmp_path, BODY, api=fake_api)
    assert r.returncode == 1 and "::error::gate 'sre'" in r.stdout
    assert "### Merge gates" in summary and "| sre |" in summary and "missing" in summary


def test_main_fails_when_github_is_unreachable_even_with_every_line(tmp_path):
    # neither the base commit's org file nor the PR's files can be read: nothing shows the PR left its gates alone
    r, _ = run_main(tmp_path, BODY + GATE_LINES, extra_env={"INPUT_ALLOW_UNVERIFIED": "true"})
    assert r.returncode == 1 and "could not be listed" in r.stdout and "gates were not checked" in r.stdout


def test_main_without_jira_fails_an_approval_gate(tmp_path, fake_api):
    fake_api.files(["README.md"])
    fake_api.base_org(ORG_YAML)
    r, summary = run_main(tmp_path, BODY + GATE_LINES, api=fake_api)
    assert r.returncode == 1 and "::error::gate 'sre': SREPROJ-7 could not be verified" in r.stdout
    assert "unverified" in summary


def test_main_without_jira_passes_with_allow_unverified(tmp_path, fake_api):
    fake_api.files(["README.md"])
    fake_api.base_org(ORG_YAML)
    r, summary = run_main(tmp_path, BODY + GATE_LINES, api=fake_api, extra_env={"INPUT_ALLOW_UNVERIFIED": "true"})
    assert r.returncode == 0, r.stdout + r.stderr
    assert "passing it unverified" in r.stdout and "Passes for KAN-315." in summary


def test_main_reads_the_org_file_at_the_base_commit(tmp_path, fake_api):
    # the PR's own copy says placeholder: true; the base commit's is enforced
    fake_api.files([ORG_PATH, "README.md"])
    fake_api.base_org(ORG_YAML)
    r, _ = run_main(tmp_path, BODY, ORG_YAML.replace("placeholder: false", "placeholder: true"), api=fake_api)
    assert r.returncode == 1 and "::error::gate 'sre'" in r.stdout and "is a placeholder" not in r.stdout
    assert f"this PR changes {ORG_PATH}" in r.stdout
    assert f"/repos/o/r/contents/{ORG_PATH}?ref={BASE_SHA}" in fake_api.seen


def test_main_fails_a_pr_that_adds_or_changes_an_org_file_missing_at_base(tmp_path, fake_api):
    fake_api.files([ORG_PATH])
    r, _ = run_main(tmp_path, BODY + GATE_LINES, api=fake_api, extra_env={"INPUT_ALLOW_UNVERIFIED": "true"})
    assert r.returncode == 1 and "does not exist at the base commit" in r.stdout
    assert "a PR can't set its own merge gates" in r.stdout


def test_main_uses_the_checkout_when_the_base_read_fails_and_the_pr_leaves_it_alone(tmp_path, fake_api):
    fake_api.files(["README.md"])
    r, _ = run_main(tmp_path, BODY + GATE_LINES, api=fake_api, extra_env={"INPUT_ALLOW_UNVERIFIED": "true"})
    assert r.returncode == 0, r.stdout + r.stderr
    assert "read from the checkout" in r.stdout


@pytest.mark.parametrize("org_file", ["{tmp}/orgs/test-co/org.yaml", "/etc/org.yaml", "../org.yaml",
                                      "orgs/../../org.yaml", "./..", "C:/org.yaml", "\\\\host\\org.yaml"])
def test_main_rejects_an_org_file_outside_the_repository(tmp_path, fake_api, org_file):
    # an absolute or escaping path would skip the base-commit read, so a PR could set its own gates
    fake_api.files(["README.md", "orgs/test-co/org.yaml"])
    fake_api.base_org(ORG_YAML)
    placeholder = ORG_YAML.replace("placeholder: false", "placeholder: true")
    r, _ = run_main(tmp_path, BODY, placeholder, org_file=org_file.format(tmp=tmp_path), api=fake_api,
                    extra_env={"INPUT_ALLOW_UNVERIFIED": "true"})
    assert r.returncode == 1 and "must be a path inside the repository" in r.stdout
    assert "is a placeholder" not in r.stdout and not any("/contents/" in p and "org.yaml" in p for p in fake_api.seen)


def test_main_normalises_a_dotted_org_file_path_and_reads_it_at_base(tmp_path, fake_api):
    fake_api.files(["README.md", ORG_PATH])
    fake_api.base_org(ORG_YAML)
    placeholder = ORG_YAML.replace("placeholder: false", "placeholder: true")
    r, _ = run_main(tmp_path, BODY, placeholder, org_file="./orgs/x/../test-co/org.yaml", api=fake_api)
    assert r.returncode == 1 and "::error::gate 'sre'" in r.stdout and "is a placeholder" not in r.stdout
    assert f"/repos/o/r/contents/{ORG_PATH}?ref={BASE_SHA}" in fake_api.seen


def _jira_world(api, sre=None, work_labels=("exec:pair",)):
    api.files(["README.md"])
    api.base_org(ORG_YAML)
    api.routes["/rest/api/3/issue/KAN-315?fields=status,labels,issuetype,issuelinks"] = (200, {
        "key": "KAN-315", "fields": {"status": {"name": "In Progress", "statusCategory": {"key": "indeterminate"}},
                                     "labels": list(work_labels), "issuetype": {"name": "Task"}, "issuelinks": []}})
    api.issue("SREPROJ-7", sre or (200, jira_issue("SREPROJ-7", "SREPROJ", "Approved")))
    api.issue("SECPROJ-8", (200, jira_issue("SECPROJ-8", "SECPROJ", "Open")))
    api.issue("UIPROJ-9", (200, jira_issue("UIPROJ-9", "UIPROJ", "Open")))


def test_main_with_jira_passes_an_approved_linked_gate(tmp_path, fake_api):
    _jira_world(fake_api)
    fake_api.issue("SREPROJ-7", jira_issue("SREPROJ-7", "SREPROJ", "Approved"))
    r, summary = run_main(tmp_path, BODY + "SRE: SREPROJ-7\n", api=fake_api, jira=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "checked" in summary and "Passes for KAN-315." in summary


@pytest.mark.parametrize("status, body", [
    (200, "<!DOCTYPE html><html><title>Log in with SSO</title></html>"),
    (500, {"errorMessages": ["boom"]}),
])
def test_main_with_jira_fails_closed_on_a_bad_answer(tmp_path, fake_api, status, body):
    _jira_world(fake_api)
    fake_api.issue("SREPROJ-7", body, status)
    r, _ = run_main(tmp_path, BODY + "SRE: SREPROJ-7\n", api=fake_api, jira=True)
    assert r.returncode == 1 and "::error::gate 'sre'" in r.stdout


@pytest.mark.parametrize("status, body", [
    (200, "<!DOCTYPE html><html><title>Log in with SSO</title></html>"),
    (200, {"key": "KAN-315"}),  # JSON, but not an issue: its labels are unknown, not empty
])
def test_main_with_jira_fails_closed_when_the_work_ticket_cannot_be_read(tmp_path, fake_api, status, body):
    # credentials are set, so the ticket check (status, execution label, blocking decisions) must not be skipped
    _jira_world(fake_api)
    fake_api.routes["/rest/api/3/issue/KAN-315?fields=status,labels,issuetype,issuelinks"] = (status, body)
    r, _ = run_main(tmp_path, BODY + "SRE: SREPROJ-7\n", api=fake_api, jira=True)
    assert r.returncode == 1 and "::error::Jira was not reachable" in r.stdout and "KAN-315" in r.stdout
    r, _ = run_main(tmp_path, BODY + "SRE: SREPROJ-7\n", api=fake_api, jira=True,
                    extra_env={"INPUT_ALLOW_UNVERIFIED": "true"})
    # allow-unverified turns it into a warning; label gates still apply, since the labels are unknown
    assert "::warning::Jira was not reachable" in r.stdout and "::error::Jira was not reachable" not in r.stdout
    assert "::error::gate 'data'" in r.stdout


def test_main_applies_a_label_gate_from_the_work_tickets_labels(tmp_path, fake_api):
    _jira_world(fake_api, work_labels=("exec:pair", "DATA-change"))
    fake_api.issue("SREPROJ-7", jira_issue("SREPROJ-7", "SREPROJ", "Approved"))
    r, _ = run_main(tmp_path, BODY + "SRE: SREPROJ-7\n", api=fake_api, jira=True)
    assert r.returncode == 1 and "::error::gate 'data'" in r.stdout


def test_main_placeholder_org_passes_with_a_warning(tmp_path, fake_api):
    placeholder = ORG_YAML.replace("placeholder: false", "placeholder: true")
    fake_api.files(["README.md"])
    fake_api.base_org(placeholder)
    r, summary = run_main(tmp_path, BODY, placeholder, api=fake_api)
    assert r.returncode == 0 and "::warning::the org overlay 'test-co' is a placeholder" in r.stdout
    assert "not enforced" in summary


def test_main_invalid_org_file_fails_without_a_crash(tmp_path, fake_api):
    fake_api.files(["README.md"])
    fake_api.base_org("schema: [unclosed\n")
    r, _ = run_main(tmp_path, BODY, api=fake_api)
    assert r.returncode == 1 and f"::error::org-file {ORG_PATH}" in r.stdout and "Traceback" not in r.stderr
    r, _ = run_main(tmp_path, BODY, org_file="orgs/none/org.yaml", api=fake_api)
    assert r.returncode == 1 and "could not be read" in r.stdout and "Traceback" not in r.stderr


# --- rule 7, team-harness.org/v2 (KAN-373): stages, the work ticket's type and project, approval on the work ticket,
# --- approval fields, GitHub reviews by a team, and gates filed for the record --------------------------------------

ORG_V2 = """\
schema: team-harness.org/v2
name: test-co
placeholder: false
reviewers:
  sre: {name: SRE, github_team: test-org/sre}
  infosec: {name: Infosec}
  ess: {name: ESS}
  board: {name: Architecture board}
stages:
  - {name: dev, branches: [main]}
  - {name: prod}
ticket_types:
  - {id: work, project: KAN, issue_type: Story, role: work}
  - {id: infosec-review, project: SECPROJ, issue_type: Task, role: approval}
  - {id: ess-request, project: ESSPROJ, issue_type: Task, role: approval}
  - {id: arch-review, project: ARCHPROJ, issue_type: Task, role: approval}
  - {id: change-request, project: CHGPROJ, issue_type: Change, role: approval}
gates:
  - {id: sre, approved_on: work, approvers: sre, stage: dev, when: always, links: [pr],
     approved_statuses: [SRE Approved], github_review: true}
  - {id: infosec, ticket: infosec-review, scope: repo, approvers: infosec, stage: dev, when: always,
     pr_line: Infosec, links: [repo], filed_by: agent, approved_statuses: [Approved]}
  - {id: ess, ticket: ess-request, approvers: ess, stage: dev, when: {issue_types: [Change Request]}, pr_line: ESS,
     filed_by: person, approved_field: {field: customfield_10050, values: [Approved]}}
  - {id: architecture, ticket: arch-review, approvers: board, when: {labels: [architecture], projects: [OPS]},
     pr_line: Architecture, filed_by: agent, needs_approval: false}
  - {id: release, ticket: change-request, approvers: sre, stage: prod, when: always, pr_line: Release,
     filed_by: person, approved_statuses: [Approved]}
review_request:
  room: "the team's review room"
  template: |
    Review please: {pr_url}
"""


@pytest.fixture
def org2(tmp_path):
    p = tmp_path / "org2.yaml"
    p.write_text(ORG_V2)
    return wsp.load_org(str(p))


def review(login, state="APPROVED", commit=HEAD_SHA):
    return {"user": {"login": login}, "state": state, "commit_id": commit}


def gh(reviews=(), members=("sre-1",), *, reviews_error=None, member_error=None):
    def list_reviews():
        if reviews_error:
            raise reviews_error
        return list(reviews)

    def member(team, login):
        assert team == "test-org/sre"
        if member_error:
            raise member_error
        return login in members
    return {"reviews": list_reviews, "team_member": member}


def work_issue(status="SRE Approved", description=PR_URL, **extra):
    issue = jira_issue("KAN-315", "KAN", status, issue_type="Story", links=(), description=description)
    issue["fields"].update(extra)
    return issue


def v2(org2, body="Infosec: SECPROJ-8\n", issues=None, files=(), **kw):
    """check_gates on the v2 org, with Jira holding an approved work ticket and infosec ticket unless told otherwise."""
    issues = {"KAN-315": work_issue(), "SECPROJ-8": jira_issue("SECPROJ-8", "SECPROJ", "Approved",
                                                                description="https://github.com/o/r"),
              **(issues or {})}
    kw.setdefault("work_key", "KAN-315")
    kw.setdefault("work_issue_type", "Story")
    for k, v in gh([review("sre-1")]).items():
        kw.setdefault(k, v)
    p = kw.pop("pr", None) or gated(lines=body)
    return wsp.check_gates(p, list(files), org2, fetch=fake_jira(issues), remote_links=lambda key: [], **kw)


def test_v2_passes_with_the_work_ticket_approved_and_a_team_review(org2):
    gates, errs, warns = v2(org2)
    g = by_id(gates)
    assert errs == [] and warns == [], errs
    assert g["sre"].state == "checked" and g["sre"].key == "KAN-315" and g["sre"].on == "work"
    assert g["infosec"].state == "checked"
    assert [g[i].state for i in ("ess", "architecture", "release")] == ["not required"] * 3


def test_v2_a_review_only_work_gate_reads_checked_once_approved(org2):
    """R2's note: a work gate with only github_review (nothing in Jira) shows checked, not linked, once approved."""
    gate = org2["gates"][0]
    for k in ("approved_statuses", "links"):
        gate.pop(k)
    gates, errs, _ = v2(org2)
    assert errs == [] and by_id(gates)["sre"].state == "checked"
    gates, errs, _ = v2(org2, **gh([]))
    assert by_id(gates)["sre"].state == "not approved" and errs


def test_v2_a_later_stage_is_not_held_at_merge(org2):
    gates, _, _ = v2(org2)
    assert "stage prod is a later step" in by_id(gates)["release"].why


@pytest.mark.parametrize("base, applies", [("main", True), ("release/1.2", False), (None, True)])
def test_v2_stage_follows_the_prs_base_branch(org2, base, applies):
    p = gated(lines="Infosec: SECPROJ-8\n")
    p["base"]["ref"] = base
    gates, _, _ = v2(org2, pr=p)
    assert by_id(gates)["infosec"].applies is applies and by_id(gates)["sre"].applies is applies
    if base is None:
        assert "base branch is unknown, so the gate applies" in by_id(gates)["infosec"].why


@pytest.mark.parametrize("itype, applies", [("Change Request", True), ("change request", True), ("Story", False),
                                            (None, True)])
def test_v2_issue_types_gate_reads_the_work_tickets_type(org2, itype, applies):
    gates, errs, _ = v2(org2, work_issue_type=itype)
    assert by_id(gates)["ess"].applies is applies
    assert any("'ess'" in e and "a person files that ticket" in e for e in errs) is applies
    if itype is None:
        assert "issue type is unknown" in by_id(gates)["ess"].why


def test_v2_projects_gate_reads_the_work_keys_project(org2):
    gates, _, _ = v2(org2)
    assert not by_id(gates)["architecture"].applies
    gates, _, _ = v2(org2, pr=gated(title="OPS-4: tune", lines=""), work_key="OPS-4")
    assert by_id(gates)["architecture"].applies and "work ticket project OPS" in by_id(gates)["architecture"].why
    gates, _, _ = v2(org2, work_key=None)
    assert by_id(gates)["architecture"].applies  # no work ticket: its project is unknown, so the gate applies


def test_v2_record_only_gate_needs_its_line_and_no_approval(org2):
    issues = {"ARCHPROJ-3": jira_issue("ARCHPROJ-3", "ARCHPROJ", "Open", links=())}
    gates, errs, _ = v2(org2, pr=gated(lines="Infosec: SECPROJ-8\n", labels=["architecture"]), issues=issues)
    assert by_id(gates)["architecture"].applies and by_id(gates)["architecture"].record_only
    assert any("'architecture'" in e and "Architecture: <KEY>" in e for e in errs)
    gates, errs, _ = v2(org2, pr=gated(lines="Infosec: SECPROJ-8\nArchitecture: ARCHPROJ-3\n",
                                       labels=["architecture"]), issues=issues)
    assert errs == [] and by_id(gates)["architecture"].state == "checked"
    assert "for the record" in "\n".join(wsp.gate_summary(gates))


def test_v2_work_gate_fails_when_the_work_ticket_is_not_approved(org2):
    gates, errs, _ = v2(org2, issues={"KAN-315": work_issue("In Progress")})
    assert by_id(gates)["sre"].state == "not approved"
    assert any("'sre': KAN-315 is In Progress; it must be SRE Approved" in e for e in errs)


def test_v2_work_gate_needs_the_work_ticket_to_link_the_pr(org2):
    _, errs, _ = v2(org2, issues={"KAN-315": work_issue(description=None)})
    assert any("'sre': KAN-315 does not link this PR" in e for e in errs)


def test_v2_work_gate_needs_a_work_key_in_a_work_project(org2):
    gates, errs, _ = v2(org2, work_key=None)
    assert by_id(gates)["sre"].state == "invalid" and any("names no work ticket" in e for e in errs)
    gates, errs, _ = v2(org2, pr=gated(title="OPS-4: tune", lines="Infosec: SECPROJ-8\n"), work_key="OPS-4")
    assert any("OPS-4 is not in KAN, where work tickets are filed" in e for e in errs)


def test_v2_work_gate_fails_closed_without_jira(org2):
    gates, errs, _ = wsp.check_gates(gated(lines="Infosec: SECPROJ-8\n"), [], org2, work_key="KAN-315",
                                     **gh([review("sre-1")]))
    assert by_id(gates)["sre"].state == "unverified"
    assert any("'sre': KAN-315 could not be verified as SRE Approved" in e for e in errs)
    gates, errs, warns = wsp.check_gates(gated(lines="Infosec: SECPROJ-8\n"), [], org2, work_key="KAN-315",
                                         allow_unverified=True, **gh([review("sre-1")]))
    assert errs == [] and by_id(gates)["sre"].state == "not checked" and any("unverified" in w for w in warns)


def test_v2_work_gate_with_jira_unreachable_fails_closed(org2):
    def down(key):
        raise urllib.error.URLError("timed out")
    gates, errs, _ = wsp.check_gates(gated(lines=""), [], org2, work_key="KAN-315", fetch=down,
                                     remote_links=lambda k: [], **gh([review("sre-1")]))
    assert by_id(gates)["sre"].state == "unverified" and any("'sre'" in e for e in errs)


@pytest.mark.parametrize("reviews, words", [
    ([], "needs an approving review on the PR's latest commit from a member of @test-org/sre;"),
    ([review("sre-1", commit="0" * 40)], "sre-1 approved an earlier commit"),
    ([review("dev-2")], "dev-2 approved but is not on @test-org/sre"),
    ([review("sean")], "needs an approving review"),  # the PR's author never counts
    ([review("sre-1"), review("sre-1", "CHANGES_REQUESTED")], "sre-1 of @test-org/sre requested changes"),
    ([review("sre-1"), review("sre-1", "DISMISSED")], "needs an approving review"),
])
def test_v2_github_review_must_come_from_the_team_on_the_head_commit(org2, reviews, words):
    gates, errs, _ = v2(org2, **gh(reviews, members=("sre-1", "sean")))
    assert by_id(gates)["sre"].state == "not approved"
    assert any("'sre'" in e and words in e for e in errs), errs


def test_v2_github_review_comment_after_approval_keeps_it(org2):
    _, errs, _ = v2(org2, **gh([review("sre-1"), review("sre-1", "COMMENTED", "0" * 40)]))
    assert errs == []


@pytest.mark.parametrize("reviews, members, blocked", [
    ([review("sre-1"), review("sre-2", "CHANGES_REQUESTED")], ("sre-1", "sre-2"), True),
    ([review("sre-1"), review("sre-2", "CHANGES_REQUESTED", "0" * 40)], ("sre-1", "sre-2"), True),  # any commit
    ([review("sre-1"), review("dev-2", "CHANGES_REQUESTED")], ("sre-1",), False),  # not on the team
    ([review("sre-1"), review("sre-2", "CHANGES_REQUESTED"), review("sre-2", "DISMISSED")], ("sre-1", "sre-2"),
     False),
    ([review("sre-1"), review("sean", "CHANGES_REQUESTED")], ("sre-1", "sean"), False),  # the author
])
def test_v2_github_review_a_members_request_for_changes_holds_it(org2, reviews, members, blocked):
    """KAN-373 review: as on GitHub, one member's approval doesn't outweigh another member's request for changes."""
    gates, errs, _ = v2(org2, **gh(reviews, members=members))
    assert bool(errs) is blocked, errs
    if blocked:
        assert by_id(gates)["sre"].state == "not approved"
        assert any("sre-2 of @test-org/sre requested changes" in e for e in errs), errs


def test_v2_no_work_key_applies_issue_type_and_project_gates(org2):
    """KAN-373 review: an exempt PR has no key, so the work ticket's type and project are unknown, not "no match"."""
    gates, _, _ = v2(org2, work_key=None, work_issue_type=None)
    g = by_id(gates)
    assert g["ess"].applies and "issue type is unknown" in g["ess"].why
    assert g["architecture"].applies and "PR names no work ticket" in g["architecture"].why


def test_v2_github_reviews_reader_pages_and_reads_membership(fake_api):
    page1 = [review(f"u{i}", "COMMENTED") for i in range(100)]
    fake_api.routes["/repos/o/r/pulls/7/reviews?per_page=100&page=1"] = (200, page1)
    fake_api.routes["/repos/o/r/pulls/7/reviews?per_page=100&page=2"] = (200, [review("sre-1")])
    fake_api.routes["/orgs/test-org/teams/sre"] = (200, {"slug": "sre"})
    fake_api.routes["/orgs/test-org/teams/sre/memberships/sre-1"] = (200, {"state": "active"})
    fake_api.routes["/orgs/test-org/teams/sre/memberships/sre-2"] = (200, {"state": "pending"})
    fake_api.routes["/orgs/test-org/teams/sre/memberships/sre-3"] = (500, {"message": "boom"})
    reviews, member = wsp._github_reviews("o/r", 7, "t", fake_api.url)
    assert len(reviews()) == 101
    assert member("test-org/sre", "sre-1") is True
    assert member("test-org/sre", "sre-2") is False  # invited, not yet on the team
    assert member("test-org/sre", "nobody") is False  # 404
    with pytest.raises(OSError, match="HTTP 500"):
        member("test-org/sre", "sre-3")


def test_v2_github_review_one_member_is_enough(org2):
    _, errs, _ = v2(org2, **gh([review("dev-2"), review("sre-1")]))
    assert errs == []


@pytest.mark.parametrize("kw, words", [
    ({"reviews_error": urllib.error.URLError("down")}, "the PR's reviews could not be read"),
    ({"member_error": OSError("the team could not be read (HTTP 404)")}, "whether sre-1 is on @test-org/sre"),
])
def test_v2_github_review_unreadable_fails_closed(org2, kw, words):
    gates, errs, _ = v2(org2, **gh([review("sre-1")], **kw))
    assert by_id(gates)["sre"].state == "unverified" and any(words in e for e in errs), errs
    gates, errs, warns = v2(org2, allow_unverified=True, **gh([review("sre-1")], **kw))
    assert errs == [] and by_id(gates)["sre"].state == "not checked" and any(words in w for w in warns)


def test_v2_github_review_without_a_reader_fails_closed(org2):
    gates, errs, _ = v2(org2, reviews=None, team_member=None)
    assert by_id(gates)["sre"].state == "unverified" and any("no way to read the PR's reviews" in e for e in errs)


ESS = "Infosec: SECPROJ-8\nESS: ESSPROJ-2\n"


@pytest.mark.parametrize("value, ok", [
    ({"value": "Approved", "id": "1"}, True), ([{"value": "Pending"}, {"value": "approved"}], True), ("Approved", True),
    ({"value": "Pending"}, False), (None, False),
])
def test_v2_approved_field_reads_the_jira_field(org2, value, ok):
    ess = jira_issue("ESSPROJ-2", "ESSPROJ", "Open", links=())
    ess["fields"]["customfield_10050"] = value
    gates, errs, _ = v2(org2, body=ESS, work_issue_type="Change Request", issues={"ESSPROJ-2": ess})
    assert (by_id(gates)["ess"].state == "checked") is ok
    if not ok:
        assert any("ESSPROJ-2's customfield_10050 is" in e and "it must be Approved" in e for e in errs)


def test_v2_approved_field_missing_from_jira_fails(org2):
    gates, errs, _ = v2(org2, body=ESS, work_issue_type="Change Request",
                        issues={"ESSPROJ-2": jira_issue("ESSPROJ-2", "ESSPROJ", "Open", links=())})
    assert by_id(gates)["ess"].state == "not approved" and any("returned no customfield_10050" in e for e in errs)


def test_v2_approved_field_needs_jira(org2):
    gates, errs, _ = wsp.check_gates(gated(lines=ESS), [], org2, work_key="KAN-315",
                                     work_issue_type="Change Request", **gh([review("sre-1")]))
    assert by_id(gates)["ess"].state == "unverified"
    assert any("'ess': ESSPROJ-2 could not be verified as customfield_10050 Approved" in e for e in errs)


def test_v2_gate_summary_shows_the_work_ticket_and_approvers(org2):
    gates, _, _ = v2(org2)
    table = "\n".join(wsp.gate_summary(gates))
    assert "| sre | - | the work ticket KAN-315; approvers SRE |" in table
    assert "| infosec | `Infosec: SECPROJ-8` | Task in SECPROJ; approvers Infosec |" in table


def test_v2_example_org_loads_in_the_check():
    org = wsp.load_org(str(ROOT / "orgs/example-co/org.yaml"))
    assert org["schema"] == "team-harness.org/v2" and org["gates"][0]["approved_on"] == "work"


def test_v1_org_files_still_load_and_refuse_v2_keys(tmp_path):
    p = tmp_path / "org.yaml"
    p.write_text(ORG_YAML.replace("    approved_statuses: [Approved, Done]\n",
                                  "    approved_statuses: [Approved, Done]\n    stage: dev\n", 1))
    with pytest.raises(wsp.OrgError, match="unknown key"):
        wsp.load_org(str(p))


@pytest.mark.parametrize("old, new, words", [
    ("approved_on: work, approvers: sre,", "on: work, approvers: sre,", "write approved_on"),
    ("approved_on: work,", "approved_on: board,", "approved_on must be ticket or work"),
    ("github_team: test-org/sre", "github_team: sre", "github_team must be"),
    ("approvers: infosec, stage: dev", "approvers: nobody, stage: dev", "is not a reviewers id"),
    ("stage: prod, when", "stage: staging, when", "is not one of the stages"),
    ("needs_approval: false", "needs_approval: false, approved_statuses: [Done]", "takes no approved_statuses"),
    ("scope: repo,", "scope: org,", "scope must be pr or repo"),
    ("links: [repo], filed_by: agent", "links: [repo, pr], filed_by: agent", "links repo only"),
    ("when: always, links: [pr],\n", "when: always, links: [pr, work],\n", "approved_on: work is per PR"),
    # KAN-373 review: a work gate approved in Jira must tie the work ticket to this PR
    ("when: always, links: [pr],\n", "when: always,\n", "needs links:"),
    ("branches: [main]", "branches: [' ']", "branches must be"),
    ("values: [Approved]}}", "values: [' ']}}", "approved_field"),
    ("approvers: ess, stage: dev", "approvers: infosec, github_review: true, stage: dev",
     "github_review needs approvers with a github_team"),
    ("customfield_10050", "custom field 10050", "approved_field must be"),
    ("when: {issue_types: [Change Request]}", "when: {issue_types: []}", "when.issue_types must be"),
])
def test_v2_org_errors_in_the_check_match_sync_shared(tmp_path, old, new, words):
    assert old in ORG_V2
    p = tmp_path / "org.yaml"
    p.write_text(ORG_V2.replace(old, new, 1))
    with pytest.raises(wsp.OrgError, match=words.replace("(", r"\(")):
        wsp.load_org(str(p))
    # the renderer's validator refuses the same file
    sys.path.insert(0, str(ROOT / "scripts"))
    import sync_shared
    import yaml
    assert sync_shared.validate_org(yaml.safe_load(p.read_text()), "org.yaml") != []


# main() with a v2 org: the work ticket read with the approval field, the reviews and the team through the API

def _v2_world(api, *, approved=True, reviewer="sre-1", member=True):
    api.files(["README.md"])
    api.base_org(ORG_V2)
    api.routes["/rest/api/3/issue/KAN-315?fields=status,labels,issuetype,issuelinks"] = (200, {
        "key": "KAN-315", "fields": {"status": {"name": "SRE Approved", "statusCategory": {"key": "indeterminate"}},
                                     "labels": ["exec:pair"], "issuetype": {"name": "Change Request"},
                                     "issuelinks": []}})
    gate_fields = "status,project,issuetype,issuelinks,description,customfield_10050"
    work = work_issue("SRE Approved" if approved else "In Progress")
    api.routes[f"/rest/api/3/issue/KAN-315?fields={gate_fields}"] = (200, work)
    api.routes[f"/rest/api/3/issue/SECPROJ-8?fields={gate_fields}"] = (
        200, jira_issue("SECPROJ-8", "SECPROJ", "Approved", description="https://github.com/o/r"))
    ess = jira_issue("ESSPROJ-2", "ESSPROJ", "Open", links=())
    ess["fields"]["customfield_10050"] = {"value": "Approved"}
    api.routes[f"/rest/api/3/issue/ESSPROJ-2?fields={gate_fields}"] = (200, ess)
    api.routes["/rest/api/3/issue/KAN-315/remotelink"] = (200, [])
    api.routes["/rest/api/3/issue/SECPROJ-8/remotelink"] = (200, [])
    api.routes["/rest/api/3/issue/ESSPROJ-2/remotelink"] = (200, [])
    api.routes["/repos/o/r/pulls/7/reviews?per_page=100&page=1"] = (200, [review(reviewer)])
    api.routes["/orgs/test-org/teams/sre"] = (200, {"slug": "sre"})
    if member:
        api.routes[f"/orgs/test-org/teams/sre/memberships/{reviewer}"] = (200, {"state": "active"})


def test_main_v2_passes_with_every_approval(tmp_path, fake_api):
    _v2_world(fake_api)
    r, summary = run_main(tmp_path, BODY + ESS, ORG_V2, api=fake_api, jira=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "| sre | - | the work ticket KAN-315; approvers SRE |" in summary and "| ess |" in summary
    assert "work ticket type Change Request" in summary and "Passes for KAN-315." in summary


@pytest.mark.parametrize("kw, words", [
    ({"approved": False}, "::error::gate 'sre': KAN-315 is In Progress"),
    ({"member": False}, "sre-1 approved but is not on @test-org/sre"),
])
def test_main_v2_holds_the_merge(tmp_path, fake_api, kw, words):
    _v2_world(fake_api, **kw)
    r, _ = run_main(tmp_path, BODY + ESS, ORG_V2, api=fake_api, jira=True)
    assert r.returncode == 1 and words in r.stdout, r.stdout


def test_main_v2_an_unreadable_team_fails_closed(tmp_path, fake_api):
    _v2_world(fake_api)
    del fake_api.routes["/orgs/test-org/teams/sre"]
    r, _ = run_main(tmp_path, BODY + ESS, ORG_V2, api=fake_api, jira=True)
    assert r.returncode == 1 and "the team could not be read (HTTP 404)" in r.stdout
    assert "/orgs/test-org/teams/sre/memberships/sre-1" not in fake_api.seen
