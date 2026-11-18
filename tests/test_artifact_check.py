"""KAN-517: the artifact check. An MCP server passes when every tool's input schema is valid and every golden call
returns what it says, over stdio; an agent eval stops at its budget and reports partial results; the receipt always
validates against actions/artifact-check/receipt.schema.json.

The fixtures (tests/fixtures/artifact-check/) are a standard-library MCP server and a fake agent command, so nothing
here calls a model. With SCAFFOLD_PYTHON set (check.yml's Linux job), the scaffold template's own server is checked too.
"""

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
CHECK = ROOT / "actions" / "artifact-check" / "artifact_check.py"
SCHEMA = json.loads((ROOT / "actions" / "artifact-check" / "receipt.schema.json").read_text(encoding="utf-8"))
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "artifact-check"
TEMPLATE = ROOT / "shared" / "work-system" / "skills" / "scaffold-artifact"


def run(repo: Path, *args: str, env: dict | None = None) -> tuple[int, dict | None, str]:
    out = repo / "artifact-check.json"
    r = subprocess.run([sys.executable, str(CHECK), "--repo", str(repo), "--out", str(out), *args],
                       capture_output=True, text=True, timeout=120, env={**os.environ, **(env or {})})
    receipt = json.loads(out.read_text(encoding="utf-8")) if out.exists() else None
    if receipt is not None:
        Draft202012Validator(SCHEMA).validate(receipt)  # every receipt the check writes fits its schema
    return r.returncode, receipt, r.stdout + r.stderr


def statuses(receipt: dict) -> dict[str, str]:
    return {c["id"]: c["status"] for c in receipt["cases"]}


def detail(receipt: dict, cid: str) -> str:
    return next(c["detail"] for c in receipt["cases"] if c["id"] == cid)


@pytest.fixture
def mcp_repo(tmp_path: Path) -> Path:
    golden = tmp_path / "evals" / "golden"
    golden.mkdir(parents=True)
    (golden / "echo.json").write_text(json.dumps(
        {"tool": "echo", "arguments": {"text": "hi"}, "structured_content": {"result": "hi"}}), encoding="utf-8")
    (golden / "echo-empty.json").write_text(json.dumps(
        {"tool": "echo", "arguments": {"text": ""}, "is_error": True}), encoding="utf-8")
    return tmp_path


def server(mode: str) -> str:
    return f'"{sys.executable}" "{FIXTURES / "mcp_server.py"}" {mode}'


def test_the_receipt_schema_is_valid_json_schema():
    Draft202012Validator.check_schema(SCHEMA)


def test_a_good_mcp_server_passes(mcp_repo):
    code, receipt, out = run(mcp_repo, "--kind", "mcp-server", "--command", server("ok"))
    assert code == 0, out
    assert receipt["passed"] and receipt["pass_rate"] == 1
    assert statuses(receipt) == {"tool:echo": "pass", "golden:echo": "pass", "golden:echo-empty": "pass"}
    assert receipt["model"] is None and receipt["cost_usd"] == 0


def test_a_broken_schema_fails_with_the_tool_named(mcp_repo):
    (mcp_repo / "evals" / "golden" / "broken.json").write_text(json.dumps(
        {"tool": "broken", "arguments": {"n": 1}}), encoding="utf-8")
    code, receipt, out = run(mcp_repo, "--kind", "mcp-server", "--command", server("broken-schema"))
    assert code == 1, out
    assert not receipt["passed"]
    assert statuses(receipt)["tool:broken"] == "fail" and statuses(receipt)["tool:echo"] == "pass"
    assert "input schema is invalid" in detail(receipt, "tool:broken")
    assert "| tool:broken | fail |" in out  # the summary names it too
    assert detail(receipt, "golden:broken") == "broken failed its tool check"  # a broken tool's goldens aren't called


def test_a_tool_listed_twice_fails(mcp_repo):
    code, receipt, _ = run(mcp_repo, "--kind", "mcp-server", "--command", server("duplicate"))
    details = [c["detail"] for c in receipt["cases"] if c["id"] == "tool:echo"]
    assert code == 1 and details == ["", "the server lists it twice"]


def test_a_tool_without_a_description_or_a_golden_case_fails(mcp_repo):
    code, receipt, _ = run(mcp_repo, "--kind", "mcp-server", "--command", server("no-description"))
    assert code == 1 and "no description" in detail(receipt, "tool:echo")
    for p in (mcp_repo / "evals" / "golden").glob("*.json"):
        p.unlink()
    code, receipt, _ = run(mcp_repo, "--kind", "mcp-server", "--command", server("ok"))
    assert code == 1 and "no golden case" in detail(receipt, "coverage:echo")


def test_a_golden_call_that_returns_something_else_fails(mcp_repo):
    (mcp_repo / "evals" / "golden" / "echo.json").write_text(json.dumps(
        {"tool": "echo", "arguments": {"text": "hi"}, "structured_content": {"result": "bye"}}), encoding="utf-8")
    (mcp_repo / "evals" / "golden" / "wrong-args.json").write_text(json.dumps(
        {"tool": "echo", "arguments": {"text": 5}}), encoding="utf-8")
    code, receipt, _ = run(mcp_repo, "--kind", "mcp-server", "--command", server("ok"))
    assert code == 1
    assert "returned" in detail(receipt, "golden:echo")
    assert "don't fit" in detail(receipt, "golden:wrong-args")
    assert statuses(receipt)["golden:echo-empty"] == "pass"


def test_a_protocol_error_is_not_the_tool_error_a_case_expects(mcp_repo):
    code, receipt, _ = run(mcp_repo, "--kind", "mcp-server", "--command", server("protocol-error"))
    assert code == 1 and "protocol error" in detail(receipt, "golden:echo-empty")


def test_a_golden_file_that_isnt_json_fails_its_case(mcp_repo):
    (mcp_repo / "evals" / "golden" / "bad.json").write_text("{not json", encoding="utf-8")
    code, receipt, _ = run(mcp_repo, "--kind", "mcp-server", "--command", server("ok"))
    assert code == 1 and "can't be read as JSON" in detail(receipt, "golden:bad")
    assert statuses(receipt)["golden:echo"] == "pass"


@pytest.mark.parametrize("spec", [{"tool": ["echo"]}, {"tool": "echo", "arguments": ["hi"]}, {}])
def test_a_golden_file_without_a_tool_name_or_arguments_object_fails_its_case(mcp_repo, spec):
    (mcp_repo / "evals" / "golden" / "bad.json").write_text(json.dumps(spec), encoding="utf-8")
    code, receipt, _ = run(mcp_repo, "--kind", "mcp-server", "--command", server("ok"))
    assert code == 1 and "needs a tool name and an arguments object" in detail(receipt, "golden:bad")


@pytest.mark.parametrize("mode", ["crash-on-call", "hang-on-call"])
def test_a_server_that_dies_or_hangs_on_a_call_fails_that_case_and_skips_the_rest(mcp_repo, mode):
    code, receipt, out = run(mcp_repo, "--kind", "mcp-server", "--command", server(mode), "--timeout", "3")
    assert code == 1, out
    first, second = (c for c in receipt["cases"] if c["id"].startswith("golden:"))
    assert first["status"] == "fail" and second["status"] == "not_run"


def test_a_server_that_ignores_its_input_closing_is_killed_with_its_children(mcp_repo, tmp_path):
    pidfile = tmp_path / "child.pid"
    start = time.monotonic()
    code, receipt, out = run(mcp_repo, "--kind", "mcp-server", "--command", server("stuck-on-call"), "--timeout", "2",
                             env={"ARTIFACT_FIXTURE_PIDFILE": str(pidfile)})
    assert code == 1 and time.monotonic() - start < 60, out
    assert statuses(receipt)["golden:echo-empty"] == "fail"  # the first call, by file name
    if sys.platform == "linux":  # the server's own child went with it (a zombie left for init to reap is gone too)
        status = Path(f"/proc/{pidfile.read_text()}/status")
        assert not status.exists() or "\tZ" in status.read_text()


@pytest.mark.parametrize(("command", "why"), [("no-such-server-command-kan517", "could not start"),
                                              ("python 'unbalanced", "can't be split")])
def test_a_server_that_wont_start_cant_run(mcp_repo, command, why):
    if sys.platform == "win32" and "unbalanced" in command:
        pytest.skip("Windows passes the command whole to CreateProcess")
    code, receipt, out = run(mcp_repo, "--kind", "mcp-server", "--command", command)
    assert code == 2 and receipt is None and why in out


def test_a_server_whose_tool_pages_never_end_cant_run(mcp_repo):
    code, receipt, out = run(mcp_repo, "--kind", "mcp-server", "--command", server("same-cursor"))
    assert code == 2 and receipt is None and "repeated a page cursor" in out


def test_the_run_stops_at_its_time_limit(mcp_repo):
    code, receipt, out = run(mcp_repo, "--kind", "mcp-server", "--command", server("hang-on-call"), "--time-limit", "3")
    assert code == 1, out
    assert [c["status"] for c in receipt["cases"] if c["id"].startswith("golden:")] == ["fail", "not_run"]


@pytest.fixture
def agent_repo(tmp_path: Path) -> Path:
    tasks = tmp_path / "evals" / "tasks"
    tasks.mkdir(parents=True)
    usage = {"input_tokens": 20000, "output_tokens": 10000}  # $0.007 on claude-haiku-5-5
    for i in range(1, 5):
        (tasks / f"t{i}.yaml").write_text(yaml.safe_dump(
            {"id": f"task-{i}", "input": "say hi", "reply": "hi there", "usage": usage,
             "expect": {"contains": ["hi"]}}),
            encoding="utf-8")
    return tmp_path


def agent() -> str:
    return f'"{sys.executable}" "{FIXTURES / "agent.py"}"'


def test_an_agent_eval_passes_and_prices_its_tokens(agent_repo):
    code, receipt, out = run(agent_repo, "--kind", "agent", "--command", agent(), "--budget-usd", "1")
    assert code == 0, out
    assert receipt["model"] == "claude-haiku-5-5" and receipt["cost_usd"] == pytest.approx(0.028)
    assert receipt["tokens"] == {"input": 80000, "output": 40000} and not receipt["stopped_at_budget"]


def test_an_agent_eval_stops_at_the_budget_and_reports_partial_results(agent_repo):
    code, receipt, out = run(agent_repo, "--kind", "agent", "--command", agent(), "--budget-usd", "0.012")
    assert code == 1, out
    assert statuses(receipt) == {"task-1": "pass", "task-2": "pass", "task-3": "not_run", "task-4": "not_run"}
    assert receipt["stopped_at_budget"] and receipt["pass_rate"] == 0.5
    assert receipt["over_budget"]  # task-2 took it to $0.014, over $0.012
    assert receipt["cost_usd"] == pytest.approx(0.014)  # the task that crossed the cap finished; none started after
    assert "Stopped at the budget" in out


def test_the_pass_rate_threshold_comes_from_the_inputs(agent_repo):
    t = yaml.safe_load((agent_repo / "evals/tasks/t4.yaml").read_text(encoding="utf-8"))
    (agent_repo / "evals/tasks/t4.yaml").write_text(yaml.safe_dump({**t, "reply": "nope"}), encoding="utf-8")
    code, receipt, _ = run(agent_repo, "--kind", "bot", "--command", agent(), "--min-pass-rate", "0.75")
    assert code == 0 and receipt["pass_rate"] == 0.75
    assert "lacks 'hi'" in detail(receipt, "task-4")
    code, _, _ = run(agent_repo, "--kind", "bot", "--command", agent(), "--min-pass-rate", "0.8")
    assert code == 1


def edit_task(repo: Path, name: str, **change) -> None:
    path = repo / "evals" / "tasks" / name
    task = {**yaml.safe_load(path.read_text(encoding="utf-8")), **change}
    path.write_text(yaml.safe_dump({k: v for k, v in task.items() if v is not None}), encoding="utf-8")


def test_a_failing_agent_command_fails_its_task_and_its_spend_still_counts(agent_repo):
    edit_task(agent_repo, "t1.yaml", exit=4, usage={"input_tokens": 0, "output_tokens": 30000})  # $0.015
    code, receipt, _ = run(agent_repo, "--kind", "agent", "--command", agent(), "--budget-usd", "0.012")
    assert code == 1 and "exited 4" in detail(receipt, "task-1")
    assert receipt["cost_usd"] == pytest.approx(0.015) and receipt["stopped_at_budget"]
    assert statuses(receipt) == {"task-1": "fail", "task-2": "not_run", "task-3": "not_run", "task-4": "not_run"}
    assert receipt["over_budget"]


def test_one_task_that_overruns_the_budget_fails_the_run_whatever_the_pass_rate(agent_repo):
    for i in range(5, 11):  # ten tasks, the last of which overruns: 9 of 10 pass
        edit_task(agent_repo, "t1.yaml")
        (agent_repo / "evals" / "tasks" / f"t{i:02}.yaml").write_text(
            (agent_repo / "evals" / "tasks" / "t1.yaml").read_text(encoding="utf-8").replace("task-1", f"task-{i}"),
            encoding="utf-8")
    (agent_repo / "evals" / "tasks" / "t99.yaml").write_text(yaml.safe_dump(
        {"id": "big", "input": "hi", "reply": "hi", "expect": {"contains": ["nope"]},
         "usage": {"input_tokens": 20_000_000, "output_tokens": 1_000_000}}), encoding="utf-8")
    code, receipt, out = run(agent_repo, "--kind", "agent", "--command", agent(), "--budget-usd", "1",
                             "--min-pass-rate", "0.9")
    assert receipt["pass_rate"] >= 0.9 and receipt["cost_usd"] > 1
    assert code == 1 and receipt["over_budget"] and not receipt["passed"]
    assert "Over the budget" in out


@pytest.mark.parametrize("expect", [None, ["hi"], {"contains": "hi"}, {"contains": []}, {"contains": [""]}])
def test_a_task_that_checks_nothing_fails(agent_repo, expect):
    edit_task(agent_repo, "t1.yaml", expect=expect)
    code, receipt, _ = run(agent_repo, "--kind", "agent", "--command", agent(), "--min-pass-rate", "0.75")
    assert code == 0 and "needs expect.contains" in detail(receipt, "task-1")


@pytest.mark.parametrize("change", [{"garbage": True}, {"usage": None}, {"usage": {"output_tokens": 5}}])
def test_an_answer_whose_cost_cant_be_read_stops_the_run(agent_repo, change):
    edit_task(agent_repo, "t2.yaml", **change)
    code, receipt, _ = run(agent_repo, "--kind", "agent", "--command", agent(), "--min-pass-rate", "0.25")
    assert code == 0  # task-1 passed: 1 of 4 meets 0.25
    assert statuses(receipt) == {"task-1": "pass", "task-2": "fail", "task-3": "not_run", "task-4": "not_run"}
    assert "couldn't be priced" in detail(receipt, "task-2") and not receipt["stopped_at_budget"]
    assert receipt["cost_usd"] == pytest.approx(0.007)


def test_a_task_file_that_isnt_a_mapping_fails(agent_repo):
    (agent_repo / "evals" / "tasks" / "t0.yaml").write_text("- just\n- a list\n", encoding="utf-8")
    code, receipt, _ = run(agent_repo, "--kind", "agent", "--command", agent())
    assert code == 1 and detail(receipt, "t0") == "t0.yaml is not a mapping"


def test_a_model_the_price_table_doesnt_list_is_refused(agent_repo):
    code, receipt, out = run(agent_repo, "--kind", "agent", "--command", agent(), "--model", "some-unpriced-model")
    assert code == 2 and receipt is None and "no row for some-unpriced-model" in out


def test_the_summary_goes_to_the_job_summary(mcp_repo, tmp_path):
    summary = tmp_path / "summary.md"
    run(mcp_repo, "--kind", "mcp-server", "--command", server("ok"), env={"GITHUB_STEP_SUMMARY": str(summary)})
    assert summary.read_text(encoding="utf-8").startswith("### Artifact check (mcp-server): passed")


def steps_of(wf: dict) -> list[dict]:
    return wf["jobs"]["artifact-check"]["steps"]


def test_the_workflow_is_reusable_read_only_and_pinned():
    wf = yaml.safe_load((ROOT / ".github/workflows/artifact-check.yml").read_text(encoding="utf-8"))
    call = wf[True]["workflow_call"]  # YAML 1.1 reads the key `on` as True
    assert {"kind", "harness-ref", "command", "budget-usd", "model", "min-pass-rate", "setup", "timeout",
            "time-limit", "artifact-name"} <= set(call["inputs"])
    assert call["inputs"]["model"]["default"] == "claude-haiku-5-5" and call["inputs"]["budget-usd"]["default"] == 1
    assert wf["permissions"] == {"contents": "read"} and set(call["secrets"]) == {"model-api-key", "harness-token"}
    # the check's code comes from the copy the caller names (a company's own, KAN-559), at the pinned commit
    harness = next(s for s in steps_of(wf) if s.get("with", {}).get("path") == ".artifact-check/team-harness")
    assert harness["with"]["repository"] == "${{ inputs.harness-repo }}"
    assert harness["with"]["ref"] == "${{ inputs.harness-ref }}"
    steps = wf["jobs"]["artifact-check"]["steps"]
    assert "[0-9a-f]{40}" in steps[0]["run"]
    for step in steps:  # inputs reach scripts through env, never pasted into the script
        assert not re.search(r"\$\{\{\s*(inputs|secrets)\.", step.get("run", "")), step.get("name")
        if "checkout" in step.get("uses", ""):
            assert step["with"]["persist-credentials"] is False


def test_the_scaffold_template_passes_over_stdio(tmp_path):
    py = os.environ.get("SCAFFOLD_PYTHON")
    if not py:
        if os.environ.get("SCAFFOLD_REQUIRED") == "1":
            pytest.fail("SCAFFOLD_PYTHON is not set: this job must check the template's server over stdio")
        pytest.skip("set SCAFFOLD_PYTHON to a venv's python to check the template's server over stdio")
    dest = tmp_path / "weather-tools"
    r = subprocess.run([sys.executable, str(TEMPLATE / "scaffold.py"), "mcp-server", str(dest), "--name",
                        "weather-tools", "--ticket", "PROJ-12", "--description", "Weather lookups"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    install = subprocess.run([py, "-m", "pip", "install", "--quiet", "-e", "."], cwd=dest, capture_output=True,
                             text=True, timeout=900)
    assert install.returncode == 0, install.stdout + install.stderr
    code, receipt, out = run(dest, "--kind", "mcp-server", "--command", f'"{py}" tests/serve_fake.py')
    assert code == 0, out
    assert statuses(receipt) == {"tool:search": "pass", "golden:search": "pass", "golden:search-empty-query": "pass"}
