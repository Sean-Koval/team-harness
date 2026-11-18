"""The artifact check (KAN-517): the runner, its receipt and schema, the PR check's rule 9, and the workflow."""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import jsonschema
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
ACTION = ROOT / "actions" / "artifact-check"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "artifact-check"
SCHEMA = json.loads((ACTION / "receipt.schema.json").read_text(encoding="utf-8"))
sys.path.insert(0, str(ACTION))
sys.path.insert(0, str(ROOT / "actions" / "work-system-pr"))

import artifact_check
import receipt


def cmd(*parts: str) -> str:
    """A command line in the form the platform's shell splitting reads back."""
    return subprocess.list2cmdline(list(parts)) if os.name == "nt" else shlex.join(parts)


def run(tmp_path: Path, *args: str) -> tuple[int, dict]:
    out = tmp_path / "artifact-check.json"
    code = artifact_check.main([*args, "--out", str(out)])
    r = json.loads(out.read_text(encoding="utf-8"))
    jsonschema.validate(r, SCHEMA)
    assert receipt.problems(r) == []
    return code, r


def mcp(tmp_path: Path, *flags: str, root: Path = FIXTURES / "mcp") -> tuple[int, dict]:
    server = cmd(sys.executable, str(FIXTURES / "mcp" / "server.py"), *flags)
    return run(tmp_path, "mcp-server", "--root", str(root), "--server", server)


def failed(r: dict) -> dict[str, str]:
    return {c["name"]: c["detail"] for c in r["cases"] if c["result"] == "fail"}


# --- mcp-server -------------------------------------------------------------------------------------------------------

def test_a_sound_mcp_server_passes(tmp_path):
    code, r = mcp(tmp_path)
    assert code == 0 and r["result"] == "pass" and r["kind"] == "mcp-server"
    assert {c["name"] for c in r["cases"]} == {"tools/list", "tool:search", "golden:search", "golden:search-empty-query"}


def test_a_broken_input_schema_fails_and_names_the_tool(tmp_path):
    code, r = mcp(tmp_path, "--broken")
    assert code == 1 and r["result"] == "fail"
    assert "tool search has an invalid input schema" in failed(r)["tool:search"]


def test_a_tool_without_a_description_fails(tmp_path):
    _, r = mcp(tmp_path, "--undocumented")
    assert r["result"] == "fail" and "tool search has no description" in failed(r)["tool:search"]


def test_a_wrong_golden_answer_fails_the_case(tmp_path):
    _, r = mcp(tmp_path, "--wrong")
    assert list(failed(r)) == ["golden:search"] and "search returned" in failed(r)["golden:search"]


def test_a_tool_no_golden_case_calls_fails(tmp_path):
    root = tmp_path / "repo"
    (root / "evals" / "golden").mkdir(parents=True)
    _, r = mcp(tmp_path, root=root)
    assert r["result"] == "fail" and "no golden case" in failed(r)["golden-for:search"]


def test_golden_arguments_that_break_the_schema_fail_before_the_call(tmp_path):
    root = tmp_path / "repo"
    shutil.copytree(FIXTURES / "mcp" / "evals", root / "evals")
    (root / "evals" / "golden" / "bad.json").write_text('{"tool": "search", "arguments": {"limit": 2}, "is_error": true}')
    _, r = mcp(tmp_path, root=root)
    assert "don't fit search's input schema" in failed(r)["golden:bad"]


def test_a_server_that_does_not_start_fails(tmp_path):
    _, r = run(tmp_path, "mcp-server", "--root", str(FIXTURES / "mcp"),
               "--server", cmd(sys.executable, "-c", "pass"))
    assert r["result"] == "fail" and "exited before answering initialize" in failed(r)["server"]


# --- agent, bot -------------------------------------------------------------------------------------------------------

def agent(tmp_path: Path, budget: str, *, root: Path = FIXTURES / "agent", pass_rate: str = "1") -> tuple[int, dict]:
    runner = cmd(sys.executable, str(FIXTURES / "agent" / "runner.py"))
    return run(tmp_path, "agent", "--root", str(root), "--runner", runner, "--model", "cheap-model",
               "--budget-usd", budget, "--pass-rate", pass_rate)


def test_an_agent_eval_within_its_budget_passes(tmp_path):
    code, r = agent(tmp_path, "5")
    assert code == 0 and r["result"] == "pass" and r["pass_rate"] == 1
    assert r["tokens"] == 4000 and r["cost_usd"] == pytest.approx(1.6) and not r["stopped_at_budget"]


def test_an_agent_eval_stops_at_its_budget_and_reports_partial_results(tmp_path):
    code, r = agent(tmp_path, "1")
    assert code == 1 and r["result"] == "incomplete" and r["stopped_at_budget"]
    results = {c["name"]: c["result"] for c in r["cases"]}
    assert results == {"task:task-1": "pass", "task:task-2": "pass", "task:task-3": "fail", "task:task-4": "skipped"}
    assert r["cost_usd"] <= 1.0 and r["budget_usd"] == 1.0
    assert r["pass_rate"] == pytest.approx(2 / 3, abs=1e-4)


def test_the_pass_rate_decides_an_agent_eval(tmp_path):
    root = tmp_path / "repo"
    shutil.copytree(FIXTURES / "agent" / "evals", root / "evals")
    (root / "evals" / "tasks" / "task-4.yaml").write_text("prompt: task 4\npasses: false\ncost: 0.1\n")
    assert agent(tmp_path, "5", root=root, pass_rate="0.75")[1]["result"] == "pass"
    assert agent(tmp_path, "5", root=root)[1]["result"] == "fail"


def test_a_runner_without_a_json_result_fails_the_task(tmp_path):
    root = tmp_path / "repo"
    (root / "evals" / "tasks").mkdir(parents=True)
    (root / "evals" / "tasks" / "t.yaml").write_text("prompt: x\n")
    _, r = run(tmp_path, "bot", "--root", str(root), "--runner", cmd(sys.executable, "-c", "print('hi')"),
               "--model", "m")
    assert r["result"] == "fail" and "without a JSON result" in failed(r)["task:t"]


def test_an_agent_eval_with_no_tasks_fails(tmp_path):
    (tmp_path / "repo").mkdir()
    _, r = agent(tmp_path, "1", root=tmp_path / "repo")
    assert r["result"] == "fail" and "no *.yaml task" in failed(r)["tasks"]


# --- the PR check's rule 9 --------------------------------------------------------------------------------------------

def write(tmp_path: Path, r: object) -> str:
    (tmp_path / "artifact-check.json").write_text(json.dumps(r), encoding="utf-8")
    return "artifact-check.json"


def test_rule_9_passes_a_passing_receipt(tmp_path):
    _, r = mcp(tmp_path)
    errors, warnings, lines = receipt.check(write(tmp_path, r), str(tmp_path))
    assert errors == [] and warnings == [] and "mcp-server: pass" in "\n".join(lines)


def test_rule_9_names_the_failing_cases(tmp_path):
    _, r = mcp(tmp_path, "--broken")
    errors, _, _ = receipt.check(write(tmp_path, r), str(tmp_path))
    assert len(errors) == 1 and "says fail" in errors[0] and "tool:search: tool search has an invalid" in errors[0]


def test_rule_9_never_passes_a_run_stopped_at_its_budget(tmp_path):
    _, r = agent(tmp_path, "1")
    errors, _, _ = receipt.check(write(tmp_path, r), str(tmp_path))
    assert len(errors) == 1 and "stopped at its budget" in errors[0] and "1 task(s) not run" in errors[0]


def test_rule_9_fails_a_missing_receipt_unless_allowed(tmp_path):
    errors, warnings, _ = receipt.check("artifact-check.json", str(tmp_path))
    assert "could not be read" in errors[0] and warnings == []
    errors, warnings, _ = receipt.check("artifact-check.json", str(tmp_path), allow_unverified=True)
    assert errors == [] and "allow-unverified" in warnings[0]


@pytest.mark.parametrize("bad", [[], {"schema": "other/v1"}, {"cases": [{"name": ""}]}])
def test_rule_9_fails_a_receipt_that_is_not_one(tmp_path, bad):
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(bad, SCHEMA)
    errors, _, _ = receipt.check(write(tmp_path, bad), str(tmp_path))
    assert "is not a team-harness.artifact-check/v1 receipt" in errors[0]


@pytest.mark.parametrize("path", ["../artifact-check.json", "/etc/passwd", "a/../../b.json", "C:/receipt.json", "\\\\host\\r.json",
                                  "a\\..\\..\\b.json"])
def test_rule_9_reads_only_inside_the_checkout(tmp_path, path):
    errors, _, _ = receipt.check(path, str(tmp_path), allow_unverified=True)
    assert "must be a path inside the checkout" in errors[0]


# --- the workflow -----------------------------------------------------------------------------------------------------

def test_the_workflow_is_reusable_pinned_and_read_only():
    wf = yaml.safe_load((ROOT / ".github" / "workflows" / "artifact-check.yml").read_text(encoding="utf-8"))
    call = wf[True]["workflow_call"]  # PyYAML reads the `on` key as True
    assert {"kind", "harness-repository", "harness-ref", "server", "runner", "model", "budget-usd"} <= set(call["inputs"])
    assert call["inputs"]["harness-ref"]["required"] and not call["secrets"]["model-api-key"]["required"]
    assert wf["permissions"] == {"contents": "read"}
    steps = wf["jobs"]["check"]["steps"]
    assert "[0-9a-f]{40}" in steps[0]["run"]
    assert all(s.get("with", {}).get("persist-credentials") is False for s in steps if "checkout" in s.get("uses", ""))
    upload = steps[-1]
    assert upload["if"] == "always()" and upload["with"]["name"] == "artifact-check"
    assert "artifact_check.py" in json.dumps(steps)
