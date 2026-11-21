"""KAN-353, end to end: a laptop session that `hangar trace import` reads is judged by the work-default specs.

The transcript is synthetic: a made-up Claude Code session in a checkout with the work-default team harness installed
(`.claude/team-harness.json`, as install_local.py writes it)."""

import json
from pathlib import Path

import pytest

trace_import = pytest.importorskip("hangar.trace_import")
lang = pytest.importorskip("flightdeck.specs.lang")
flatten = pytest.importorskip("flightdeck.dataplane.flatten")
if not hasattr(trace_import, "find_manifest"):
    pytest.skip("this hangar's trace import stamps no team harness (KAN-353)", allow_module_level=True)

SPECS = {s["id"]: s for s in lang.load(
    (Path(__file__).resolve().parents[1] / "flightdeck" / "specs" / "work-default.yaml").read_text())}
SID = "5e1c9c3a-1f0b-4d7e-9b52-7a0e2c4d6f81"
READ = ("mcp__atlassian__getJiraIssue", {"cloudId": "c1", "issueIdOrKey": "SVC-1"})
# an approval ticket an agent files: the example org's ESS request (SRE approves the work ticket itself, KAN-373). The
# long description comes first in the call, so the spec matches only if the import keeps the summary in the preview
SRE = ("mcp__atlassian__createJiraIssue", {"cloudId": "c1", "projectKey": "OPS", "issueTypeName": "Task",
                                           "description": "Why the queue is safe to ship. " * 20,
                                           "summary": "ESS request: SVC-1 add the queue"})
PR = ("Bash", {"command": "gh pr create --draft --title 'SVC-1: add the queue' --body-file /tmp/pr.md"})


def _session(repo: Path, turns: list[list[tuple[str, dict]]]) -> Path:
    lines, n = [], 0
    for t, calls in enumerate(turns):
        n += 1
        lines.append({"type": "user", "sessionId": SID, "timestamp": f"2026-11-17T10:{t:02d}:00Z", "isSidechain": False,
                      "cwd": str(repo), "message": {"role": "user", "content": f"step {t + 1}"}})
        for i, (name, args) in enumerate(calls):
            tid, ts = f"toolu_{t}_{i}", f"2026-11-17T10:{t:02d}:{i + 1:02d}Z"
            lines.append({"type": "assistant", "sessionId": SID, "timestamp": ts, "isSidechain": False,
                          "version": "2.1.300", "cwd": str(repo),
                          "message": {"id": f"msg_{t}_{i}", "model": "claude-opus-5-5", "role": "assistant",
                                      "content": [{"type": "tool_use", "id": tid, "name": name, "input": args}],
                                      "stop_reason": "tool_use", "usage": {"input_tokens": 1, "output_tokens": 1}}})
            lines.append({"type": "user", "sessionId": SID, "timestamp": ts, "isSidechain": False,
                          "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": tid,
                                                                   "content": "ok", "is_error": False}]}})
    p = repo.parent / f"{SID}.jsonl"
    p.write_text("".join(json.dumps(x) + "\n" for x in lines))
    return p


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))  # never the real ~/.claude
    r = tmp_path / "svc"
    (r / ".claude").mkdir(parents=True)
    (r / ".claude" / "team-harness.json").write_text(json.dumps(
        {"schema": "team-harness.install/v1", "harness": "work-default", "channel": "stable", "revision": 3}))
    return r


def _judge(repo: Path, turns, spec_id: str) -> set[str]:
    tables = flatten.flatten_trace(trace_import.import_transcript(_session(repo, turns)).trace)
    py = lang.evaluate(SPECS[spec_id], tables)
    assert py == lang.evaluate_sql(SPECS[spec_id], lang.connect_tables(tables))
    return set(py.values())


def _edit(repo: Path, name: str = "src/app.py") -> tuple[str, dict]:
    return ("Edit", {"file_path": str(repo / name), "old_string": "a", "new_string": "b"})


def test_reading_the_ticket_then_editing_passes_across_turns(repo):
    spec = "work-reads-the-ticket-before-editing-in-a-session"
    assert _judge(repo, [[READ], [_edit(repo)]], spec) == {"pass"}
    assert _judge(repo, [[_edit(repo)], [READ]], spec) == {"fail"}
    outside = ("Write", {"file_path": "/tmp/pr.md", "content": "body"})
    assert _judge(repo, [[outside]], spec) == {"not_applicable"}


def test_approvals_are_filed_after_the_sessions_own_pr(repo):
    spec = "work-approvals-filed-after-own-pr"
    assert _judge(repo, [[READ, _edit(repo)], [PR, SRE]], spec) == {"pass"}
    assert _judge(repo, [[READ, SRE], [PR]], spec) == {"fail"}


def test_without_the_manifest_the_specs_do_not_apply(repo):
    (repo / ".claude" / "team-harness.json").unlink()
    assert _judge(repo, [[_edit(repo)], [READ]], "work-reads-the-ticket-before-editing-in-a-session") \
        == {"not_applicable"}
