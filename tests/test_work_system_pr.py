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
BODY = "## What and why\nAdds the gate.\n\nJira: KAN-315\nDocs: actions/work-system-pr/README.md\n"


def pr(title="KAN-315: add the PR gate", body=BODY, branch="KAN-315-work-system-layer", labels=(), author="sean"):
    return {"number": 7, "title": title, "body": body, "head": {"ref": branch}, "html_url": PR_URL,
            "base": {"sha": BASE_SHA},
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
    assert errs == [] and by_id(gates)["sre"].state == "linked" and by_id(gates)["sre"].key == "SREPROJ-7"
    assert any("passing it unverified" in w for w in warns)


def test_without_jira_an_approval_gate_fails_closed(org):
    # fork and Dependabot PRs get no secrets: the key prefix alone must not pass a gate that needs an approval
    gates, errs, _ = wsp.check_gates(gated(), [], org)
    assert by_id(gates)["sre"].state == "unverified"
    assert any("'sre'" in e and "no Jira credentials" in e and "allow-unverified" in e for e in errs)


def test_without_jira_a_gate_without_approved_statuses_checks_the_prefix_only(org):
    files = [{"filename": "deploy/x.yaml"}]
    gates, errs, _ = wsp.check_gates(gated("SRE: SREPROJ-7\nInfosec: SECPROJ-8\n"), files, org, allow_unverified=True)
    assert errs == [] and by_id(gates)["infosec"].state == "linked"


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
    assert errs == [] and by_id(gates)["infosec"].state == "linked"


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
    _, errs, warns = wsp.check_gates(gated(), [], org, fetch=fetch, work_key="KAN-315", allow_unverified=True)
    assert errs == [] and any("passing it unverified" in w for w in warns)


@pytest.mark.parametrize("answer", [["not", "an", "issue"], {"errorMessages": ["login required"]}, None])
def test_jira_answer_that_is_not_an_issue_fails_closed(org, answer):
    gates, errs, _ = wsp.check_gates(gated(), [], org, fetch=lambda key: answer, work_key="KAN-315")
    assert by_id(gates)["sre"].state == "unverified" and any("not an issue" in e for e in errs)


def test_jira_unreachable_only_warns_for_a_gate_without_approved_statuses(org):
    def fetch(key):
        raise urllib.error.URLError("timed out")
    files = [{"filename": "deploy/x.yaml"}]
    _, errs, warns = wsp.check_gates(gated("SRE: SREPROJ-7\nInfosec: SECPROJ-8\n"), files, org, fetch=fetch,
                                     work_key="KAN-315")
    assert not any("'infosec'" in e for e in errs) and any("'infosec'" in w for w in warns)
    assert any("'sre'" in e for e in errs)


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
             labels=()):
    (tmp_path / "orgs/test-co").mkdir(parents=True, exist_ok=True)
    (tmp_path / "orgs/test-co/org.yaml").write_text(org_text)
    ev = tmp_path / "event.json"
    ev.write_text(json.dumps({"pull_request": pr(body=body, labels=labels)}))
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
