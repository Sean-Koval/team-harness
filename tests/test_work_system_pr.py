"""The work-system PR check (actions/work-system-pr): rules over the PR payload and the Jira ticket."""

import importlib.util
import json
import os
import subprocess
import sys
import urllib.error
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


def test_present_gate_line_passes(org):
    gates, errs, _ = wsp.check_gates(gated(), [], org)
    assert errs == [] and by_id(gates)["sre"].state == "linked" and by_id(gates)["sre"].key == "SREPROJ-7"


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
    gates, errs, _ = wsp.check_gates(gated("SRE: SREPROJ-7\nInfosec: SECPROJ-8\n"), files, org)
    assert errs == [] and by_id(gates)["infosec"].state == "linked"


def test_paths_gate_matches_a_rename_source(org):
    gates, _, _ = wsp.check_gates(gated(), [{"filename": "lib/x.py", "previous_filename": "src/auth/x.py"}], org)
    assert by_id(gates)["infosec"].applies


def test_paths_gate_skips_other_files_and_applies_when_files_are_unknown(org):
    gates, errs, _ = wsp.check_gates(gated(), [{"filename": "README.md"}], org)
    assert not by_id(gates)["infosec"].applies and errs == []
    gates, errs, _ = wsp.check_gates(gated(), None, org)
    assert by_id(gates)["infosec"].applies and any("'infosec'" in e for e in errs)


def test_labels_gate_and_person_filed_message(org):
    gates, errs, _ = wsp.check_gates(gated(labels=["data-change"]), [], org)
    assert by_id(gates)["data"].applies
    msg = next(e for e in errs if "'data'" in e)
    assert "a person files that ticket" in msg and "DATAPROJ" in msg
    _, errs, _ = wsp.check_gates(gated("SRE: SREPROJ-7\nData: DATAPROJ-3\n", labels=["data-change"]), [], org)
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
])
def test_invalid_org_file_is_a_clear_error(tmp_path, text, words):
    p = tmp_path / "org.yaml"
    p.write_text(text)
    with pytest.raises(wsp.OrgError) as e:
        wsp.load_org(str(p))
    assert words in str(e.value)


def test_missing_org_file_is_a_clear_error(tmp_path):
    with pytest.raises(wsp.OrgError, match="could not be read"):
        wsp.load_org(str(tmp_path / "nope.yaml"))


def jira_issue(key, project, status):
    return {"key": key, "fields": {"project": {"key": project}, "status": {"name": status},
                                   "issuetype": {"name": "Task"}}}


def fake_jira(issues):
    def fetch(key):
        if key not in issues:
            raise urllib.error.HTTPError(f"https://jira/{key}", 404, "Not Found", {}, None)
        return issues[key]
    return fetch


def test_jira_gate_ticket_approved_passes(org):
    fetch = fake_jira({"SREPROJ-7": jira_issue("SREPROJ-7", "SREPROJ", "Approved")})
    gates, errs, _ = wsp.check_gates(gated(), [], org, fetch=fetch)
    assert errs == [] and by_id(gates)["sre"].state == "checked"


def test_jira_gate_ticket_not_yet_approved_fails(org):
    fetch = fake_jira({"SREPROJ-7": jira_issue("SREPROJ-7", "SREPROJ", "In Review")})
    gates, errs, _ = wsp.check_gates(gated(), [], org, fetch=fetch)
    assert any("SREPROJ-7 is In Review" in e and "Approved or Done" in e for e in errs)
    assert by_id(gates)["sre"].state == "not approved"


def test_jira_gate_ticket_in_another_project_fails(org):
    fetch = fake_jira({"SREPROJ-7": jira_issue("SECPROJ-12", "SECPROJ", "Approved")})  # moved since it was linked
    _, errs, _ = wsp.check_gates(gated(), [], org, fetch=fetch)
    assert any("is in SECPROJ, not SREPROJ" in e for e in errs)


def test_jira_gate_ticket_missing_fails(org):
    _, errs, _ = wsp.check_gates(gated(), [], org, fetch=fake_jira({}))
    assert any("SREPROJ-7 could not be read from Jira (HTTP 404)" in e for e in errs)


def test_jira_status_not_required_without_approved_statuses(org):
    files = [{"filename": "src/auth/login.py"}]
    fetch = fake_jira({"SREPROJ-7": jira_issue("SREPROJ-7", "SREPROJ", "Done"),
                       "SECPROJ-8": jira_issue("SECPROJ-8", "SECPROJ", "Open")})
    _, errs, _ = wsp.check_gates(gated("SRE: SREPROJ-7\nInfosec: SECPROJ-8\n"), files, org, fetch=fetch)
    assert errs == []


def test_jira_unreachable_only_warns(org):
    def fetch(key):
        raise urllib.error.URLError("timed out")
    _, errs, warns = wsp.check_gates(gated(), [], org, fetch=fetch)
    assert errs == [] and any("not reachable" in w for w in warns)


def test_gate_summary_lists_every_gate(org):
    gates, _, _ = wsp.check_gates(gated(labels=["data-change"]), [], org)
    table = "\n".join(wsp.gate_summary(gates))
    for words in ("| sre | `SRE: SREPROJ-7` | Task in SREPROJ |", "| infosec |", "a person files it", "missing",
                  "not required"):
        assert words in table


def run_main(tmp_path, body, org_text=ORG_YAML, org_file="orgs/test-co/org.yaml"):
    (tmp_path / "orgs/test-co").mkdir(parents=True, exist_ok=True)
    (tmp_path / "orgs/test-co/org.yaml").write_text(org_text)
    ev = tmp_path / "event.json"
    ev.write_text(json.dumps({"pull_request": pr(body=body)}))
    summary = tmp_path / "summary.md"
    summary.write_text("")
    env = {**os.environ, "GITHUB_EVENT_PATH": str(ev), "GITHUB_REPOSITORY": "o/r", "GITHUB_API_URL": "http://127.0.0.1:9",
           "GITHUB_STEP_SUMMARY": str(summary), "GITHUB_WORKSPACE": str(tmp_path), "INPUT_ORG_FILE": org_file}
    r = subprocess.run([sys.executable, str(CHECK)], env=env, capture_output=True, text=True, check=False)
    return r, summary.read_text()


def test_main_enforces_gates_from_the_org_file(tmp_path):
    r, summary = run_main(tmp_path, BODY)
    assert r.returncode == 1 and "::error::gate 'sre'" in r.stdout
    assert "### Merge gates" in summary and "| sre |" in summary and "missing" in summary
    # the file list can't be fetched here, so the path gates apply too (fail closed)
    r, summary = run_main(tmp_path, BODY + "SRE: SREPROJ-7\nInfosec: SECPROJ-8\nUI: UIPROJ-9\n")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "::warning::could not list the PR's files" in r.stdout
    assert "linked" in summary and "Passes for KAN-315." in summary


def test_main_placeholder_org_passes_with_a_warning(tmp_path):
    r, summary = run_main(tmp_path, BODY, ORG_YAML.replace("placeholder: false", "placeholder: true"))
    assert r.returncode == 0 and "::warning::the org overlay 'test-co' is a placeholder" in r.stdout
    assert "not enforced" in summary


def test_main_invalid_org_file_fails_without_a_crash(tmp_path):
    r, _ = run_main(tmp_path, BODY, "schema: [unclosed\n")
    assert r.returncode == 1 and "::error::org-file orgs/test-co/org.yaml" in r.stdout and "Traceback" not in r.stderr
    r, _ = run_main(tmp_path, BODY, org_file="orgs/none/org.yaml")
    assert r.returncode == 1 and "could not be read" in r.stdout and "Traceback" not in r.stderr
