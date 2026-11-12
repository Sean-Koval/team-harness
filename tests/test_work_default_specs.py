"""flightdeck/specs/work-default.yaml: the approval-flow specs pass and fail on small hangar.trace/v1 exports.

Each case is evaluated by both of flightdeck's evaluators (Python and the nightly SQL), which must agree.
"""

import json
from pathlib import Path

import pytest

lang = pytest.importorskip("flightdeck.specs.lang")
flatten = pytest.importorskip("flightdeck.dataplane.flatten")

SPECS = {s["id"]: s for s in lang.load(
    (Path(__file__).resolve().parents[1] / "flightdeck" / "specs" / "work-default.yaml").read_text())}
T0 = 1_760_700_000


def _v(x):
    if isinstance(x, list):
        return {"arrayValue": {"values": [_v(y) for y in x]}}
    return {"intValue": str(x)} if isinstance(x, int) else {"stringValue": x}


def _attrs(d):
    return [{"key": k, "value": _v(v)} for k, v in d.items() if v is not None]


def trace(steps, job="job-1", harness="work-default"):
    """steps: ("turn",) | ("shell", input, ops) | ("mcp", server, tool, input) | ("pr.open",), one second apart.
    Without a job, an export of session ses-1 (source session)."""
    tid = "ab" * 16
    root = {"traceId": tid, "spanId": "root0000", "name": "invoke_workflow hangar.job", "kind": 1,
            "startTimeUnixNano": str(T0 * 10**9), "endTimeUnixNano": str((T0 + 999) * 10**9), "events": [],
            "attributes": _attrs({"hangar.kind": "job", "hangar.repo": "https://example.invalid/svc.git"})}
    spans, turns, seq = [root] if job else [], [], 0
    for n, (kind, *rest) in enumerate(steps if steps[:1] == [("turn",)] else [("turn",), *steps]):
        t = str((T0 + n) * 10**9)
        if kind == "turn":
            turns.append({"traceId": tid, "spanId": f"turn{len(turns):04d}", "parentSpanId": root["spanId"] if job
                          else None, "name": "invoke_agent claude-code", "kind": 1, "startTimeUnixNano": t,
                          "endTimeUnixNano": t, "events": [], "attributes": _attrs({
                              "hangar.kind": "turn", "hangar.run.id": f"run-{len(turns) + 1}",
                              "hangar.turn.number": len(turns) + 1, "hangar.session.id": "ses-1",
                              "hangar.harness": harness})})
            spans.append(turns[-1])
        elif kind == "pr.open":
            root["events"].append({"timeUnixNano": t, "name": "pr.open",
                                   "attributes": _attrs({"hangar.kind": "pr.open", "hangar.pr.number": 7})})
        else:
            seq += 1
            a = ({"hangar.tool.kind": "shell", "hangar.tool.input": rest[0], "hangar.shell.ops": rest[1] or None}
                 if kind == "shell" else {"hangar.tool.kind": "mcp", "hangar.mcp.server": rest[0],
                                          "hangar.mcp.tool": rest[1], "hangar.tool.input": rest[2]})
            spans.append({"traceId": tid, "spanId": f"tool{n:04d}", "parentSpanId": turns[-1]["spanId"],
                          "name": "execute_tool x", "kind": 1, "startTimeUnixNano": t, "endTimeUnixNano": t,
                          "attributes": _attrs({"hangar.kind": "tool.call", "hangar.seq": seq, **a})})
    res = {"hangar.trace.schema": "hangar.trace/v1", "hangar.job.id": job, "hangar.session.id": "ses-1"}
    return {"resourceSpans": [{"resource": {"attributes": _attrs(res)},
                               "scopeSpans": [{"scope": {"name": "hangar.trace", "version": "1"}, "spans": spans}]}]}


def results(spec_id, otlp):
    """The set of unit results, which both evaluators must agree on."""
    tables = flatten.flatten_trace(json.loads(json.dumps(otlp)))
    py = lang.evaluate(SPECS[spec_id], tables)
    assert py == lang.evaluate_sql(SPECS[spec_id], lang.connect_tables(tables))
    return set(py.values())


SRE = ("mcp", "jira", "createJiraIssue", '{"projectKey": "OPS", "summary": "SRE approval: SVC-1 add the queue"}')
INFOSEC = ("mcp", "jira", "createJiraIssue", '{"projectKey": "SEC", "summary": "Infosec review: svc SVC-1"}')
GH_PR = ("shell", "gh pr create --draft --title 'SVC-1: add the queue' --body-file pr.md", ["pr.open"])

CASES = [
    ("work-nothing-filed-to-placeholders", [SRE], "pass"),
    ("work-nothing-filed-to-placeholders",
     [("mcp", "jira", "createJiraIssue", '{"projectKey": "SREPROJ", "summary": "SRE approval: SVC-1"}')], "fail"),
    ("work-nothing-filed-to-placeholders",
     [("mcp", "jira", "createConfluenceContent", '{"spaceKey": "COMPANY-SPACE"}')], "fail"),
    ("work-approvals-filed-after-the-pr", [("pr.open",), ("turn",), SRE, INFOSEC], "pass"),
    ("work-approvals-filed-after-the-pr", [SRE, ("pr.open",), INFOSEC], "fail"),
    ("work-approvals-filed-after-the-pr", [("shell", "pytest -q", ["test"]), ("pr.open",)], "not_applicable"),
    ("work-review-request-never-posted", [("mcp", "slack", "slack_post_message", '{"text": "Review please"}')], "fail"),
    ("work-review-request-never-posted", [("mcp", "symphony", "send_message", '{"room": "review"}')], "fail"),
    ("work-review-request-never-posted", [("mcp", "slack", "conversations_history", "{}"), SRE], "pass"),
    ("work-never-merges-in-shell", [("shell", "gh pr merge 12 --squash --auto", [])], "fail"),
    ("work-never-merges-in-shell", [("shell", "gh pr review 12 --approve", [])], "fail"),
    ("work-never-merges-in-shell", [("shell", "gh api -X PUT repos/o/svc/pulls/12/merge", [])], "fail"),
    ("work-never-merges-in-shell", [("shell", "gh pr view 12 --json state", []),
                                    ("shell", "gh pr review 12 --comment -b 'see the SRE ticket'", [])], "pass"),
    ("work-never-merges-through-mcp", [("mcp", "github", "merge_pull_request", '{"pullNumber": 12}')], "fail"),
    ("work-never-merges-through-mcp", [("mcp", "github", "enable_pr_auto_merge", '{"pullNumber": 12}')], "fail"),
    ("work-never-merges-through-mcp", [("mcp", "github", "pull_request_read", '{"pullNumber": 12}'),
                                       ("mcp", "github", "disable_pr_auto_merge", '{"pullNumber": 12}')], "pass"),
    ("work-never-approves-through-mcp",
     [("mcp", "github", "pull_request_review_write", '{"method": "create", "event": "APPROVE"}')], "fail"),
    ("work-never-approves-through-mcp",
     [("mcp", "github", "pull_request_review_write", '{"method": "create", "event": "COMMENT"}')], "pass"),
]


@pytest.mark.parametrize(("spec_id", "steps", "want"), CASES, ids=lambda x: x if isinstance(x, str) else "")
def test_job_exports(spec_id, steps, want):
    assert results(spec_id, trace(steps)) == {want}


def test_a_local_session_files_the_approvals_after_its_own_pr():
    spec = "work-approvals-filed-after-own-pr"
    assert results(spec, trace([GH_PR, SRE, INFOSEC], job=None)) == {"pass"}
    assert results(spec, trace([SRE, GH_PR, INFOSEC], job=None)) == {"fail"}
    assert results(spec, trace([GH_PR], job=None)) == {"not_applicable"}
    assert results(spec, trace([SRE, GH_PR])) == {"not_applicable"}  # a job's session is judged by the job spec


def test_other_harnesses_are_not_judged():
    assert results("work-never-merges-in-shell", trace([("shell", "gh pr merge 12", [])], harness="suite-default")) \
        == {"not_applicable"}
