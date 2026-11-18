#!/usr/bin/env python3
"""The artifact check (KAN-517): one cheap eval gate a scaffolded repository runs on each PR, before SRE and infosec
see it. It writes a receipt, artifact-check.json, that the work-system PR check reads when it is given one.

    mcp-server  start the server over stdio, list its tools, check each tool's description and input schema, and run
                the golden calls in evals/golden/*.json (tool, arguments, then structured_content or is_error).
    agent, bot  run each evals/tasks/*.yaml through the repository's own runner command, with a hard budget: the cap
                is checked between tasks, and the runner gets what is left in ARTIFACT_CHECK_BUDGET_USD so it can stop
                itself. A run stopped at the cap reports its partial results as `incomplete`, which never passes.

The runner command gets the task file as its last argument and the model in ARTIFACT_CHECK_MODEL, and prints one JSON
object as its last line of output: {"passed": bool, "tokens": int, "cost_usd": number, "detail": str}.
Needs jsonschema (the mcp-server kind) and PyYAML (the agent kinds). Makes no network call itself.
"""

from __future__ import annotations

import argparse
import json
import os
import queue
import shlex
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

SCHEMA = "team-harness.artifact-check/v1"
KINDS = ("mcp-server", "agent", "bot")
PROTOCOL = "2025-06-18"
TIMEOUT = 30.0


def _command(text: str) -> str | list[str]:
    """A command line as the platform reads it: split POSIX-style, or passed whole to Windows' CreateProcess."""
    return text if os.name == "nt" else shlex.split(text)


def _case(name: str, kind: str, ok: bool, detail: str = "", **extra: Any) -> dict[str, Any]:
    return {"name": name, "kind": kind, "result": "pass" if ok else "fail", "detail": detail, **extra}


# --- mcp-server -------------------------------------------------------------------------------------------------------

class Server:
    """An MCP server over stdio: newline-delimited JSON-RPC 2.0, one request at a time."""

    def __init__(self, command: str, cwd: Path):
        self.proc = subprocess.Popen(_command(command), cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL, text=True, encoding="utf-8")
        self.lines: queue.Queue[str | None] = queue.Queue()
        threading.Thread(target=self._read, daemon=True).start()
        self.next_id = 0

    def _read(self) -> None:
        assert self.proc.stdout is not None
        for line in self.proc.stdout:
            self.lines.put(line)
        self.lines.put(None)

    def _send(self, msg: dict[str, Any]) -> None:
        assert self.proc.stdin is not None
        self.proc.stdin.write(json.dumps(msg) + "\n")
        self.proc.stdin.flush()

    def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """The response to one request: {"result": ...} or {"error": ...}. Raises RuntimeError when none comes."""
        self.next_id += 1
        self._send({"jsonrpc": "2.0", "id": self.next_id, "method": method, "params": params or {}})
        while True:
            try:
                line = self.lines.get(timeout=TIMEOUT)
            except queue.Empty:
                raise RuntimeError(f"no answer to {method} within {TIMEOUT:.0f}s") from None
            if line is None:
                raise RuntimeError(f"the server exited before answering {method}")
            try:
                msg = json.loads(line)
            except ValueError:
                continue  # a stray log line on stdout
            if isinstance(msg, dict) and msg.get("id") == self.next_id:
                return msg

    def notify(self, method: str) -> None:
        self._send({"jsonrpc": "2.0", "method": method})

    def close(self) -> None:
        try:
            if self.proc.stdin:
                self.proc.stdin.close()
            self.proc.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            self.proc.kill()


def _tool_problems(tool: dict[str, Any]) -> list[str]:
    from jsonschema import Draft202012Validator
    from jsonschema.exceptions import SchemaError

    out = []
    if not str(tool.get("description") or "").strip():
        out.append("has no description")
    schema = tool.get("inputSchema")
    if not isinstance(schema, dict):
        return [*out, "has no input schema"]
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as e:
        out.append(f"has an invalid input schema ({e.message})")
    if schema.get("type") != "object":
        out.append("has an input schema that is not an object")
    elif not set(schema.get("required") or []) <= set(schema.get("properties") or {}):
        out.append("requires properties its input schema doesn't define")
    return out


def _golden(server: Server, path: Path, tools: dict[str, dict[str, Any]]) -> dict[str, Any]:
    from jsonschema import Draft202012Validator
    from jsonschema.exceptions import SchemaError, UnknownType, ValidationError

    name = f"golden:{path.stem}"
    try:
        spec = json.loads(path.read_text(encoding="utf-8"))
        tool, args = spec["tool"], spec.get("arguments", {})
    except (OSError, ValueError, KeyError, TypeError) as e:
        return _case(name, "golden", False, f"{path.name} is not a golden case ({e})")
    if tool not in tools:
        return _case(name, "golden", False, f"the server lists no tool {tool!r}")
    try:
        Draft202012Validator(tools[tool].get("inputSchema") or {}).validate(args)
    except ValidationError as e:
        return _case(name, "golden", False, f"its arguments don't fit {tool}'s input schema ({e.message})")
    except (SchemaError, UnknownType):
        return _case(name, "golden", False, f"not run: {tool}'s input schema is invalid")
    answer = server.request("tools/call", {"name": tool, "arguments": args})
    result = answer.get("result") if isinstance(answer.get("result"), dict) else {}
    failed = "error" in answer or bool(result.get("isError"))
    if spec.get("is_error"):
        return _case(name, "golden", failed, "" if failed else f"{tool} succeeded; the case expects a tool error")
    if failed:
        return _case(name, "golden", False, f"{tool} failed: {json.dumps(answer.get('error') or result)[:300]}")
    if "structured_content" in spec and result.get("structuredContent") != spec["structured_content"]:
        return _case(name, "golden", False, f"{tool} returned {json.dumps(result.get('structuredContent'))[:300]}")
    return _case(name, "golden", True)


def check_mcp_server(root: Path, command: str) -> list[dict[str, Any]]:
    server = Server(command, root)
    try:
        init = server.request("initialize", {"protocolVersion": PROTOCOL, "capabilities": {},
                                             "clientInfo": {"name": "artifact-check", "version": "1"}})
        if "error" in init:
            return [_case("initialize", "server", False, f"the server refused initialize: {init['error']}")]
        server.notify("notifications/initialized")
        tools: dict[str, dict[str, Any]] = {}
        cursor = None
        while True:
            page = server.request("tools/list", {"cursor": cursor} if cursor else {})
            listed = (page.get("result") or {}).get("tools")
            if not isinstance(listed, list):
                return [_case("tools/list", "server", False, f"tools/list answered {json.dumps(page)[:300]}")]
            tools.update({str(t.get("name")): t for t in listed if isinstance(t, dict)})
            cursor = (page.get("result") or {}).get("nextCursor")
            if not cursor:
                break
        cases = [_case("tools/list", "server", bool(tools), "" if tools else "the server lists no tools")]
        for name in sorted(tools):
            problems = _tool_problems(tools[name])
            cases.append(_case(f"tool:{name}", "tool", not problems,
                               f"tool {name} " + "; ".join(problems) if problems else ""))
        golden = sorted((root / "evals" / "golden").glob("*.json"))
        covered = set()
        for path in golden:
            case = _golden(server, path, tools)
            cases.append(case)
            try:
                covered.add(json.loads(path.read_text(encoding="utf-8")).get("tool"))
            except (OSError, ValueError, AttributeError):
                pass
        for name in sorted(set(tools) - covered):
            cases.append(_case(f"golden-for:{name}", "golden", False, f"no golden case in evals/golden/ calls {name}"))
        return cases
    except RuntimeError as e:
        return [_case("server", "server", False, str(e))]
    finally:
        server.close()


# --- agent, bot -------------------------------------------------------------------------------------------------------

def _run_task(root: Path, runner: str, task: Path, model: str, left: float) -> dict[str, Any]:
    name = f"task:{task.stem}"
    env = {**os.environ, "ARTIFACT_CHECK_MODEL": model, "ARTIFACT_CHECK_BUDGET_USD": f"{left:.6f}"}
    cmd = _command(runner)
    cmd = f"{cmd} {subprocess.list2cmdline([str(task)])}" if isinstance(cmd, str) else [*cmd, str(task)]
    try:
        done = subprocess.run(cmd, cwd=root, env=env, capture_output=True, text=True, encoding="utf-8",
                              timeout=1800, check=False)
    except (OSError, subprocess.TimeoutExpired) as e:
        return _case(name, "task", False, f"the runner did not finish ({e})", tokens=0, cost_usd=0.0)
    lines = [ln for ln in done.stdout.splitlines() if ln.strip()]
    try:
        out = json.loads(lines[-1])
        tokens, cost = int(out.get("tokens", 0)), float(out.get("cost_usd", 0.0))
        if tokens < 0 or cost < 0:
            raise ValueError("negative tokens or cost")
    except (IndexError, ValueError, TypeError, AttributeError) as e:
        return _case(name, "task", False, f"the runner exited {done.returncode} without a JSON result ({e})",
                     tokens=0, cost_usd=0.0)
    ok = out.get("passed") is True and done.returncode == 0
    return _case(name, "task", ok, str(out.get("detail") or ""), tokens=tokens, cost_usd=cost)


def check_agent(root: Path, runner: str, model: str, budget: float) -> tuple[list[dict[str, Any]], bool]:
    """(cases, stopped at the budget). A task file that YAML can't read fails without spending."""
    import yaml  # type: ignore[import-untyped]

    tasks = sorted((root / "evals" / "tasks").glob("*.yaml"))
    if not tasks:
        return [_case("tasks", "task", False, "evals/tasks/ has no *.yaml task")], False
    cases: list[dict[str, Any]] = []
    spent, stopped = 0.0, False
    for task in tasks:
        if spent >= budget:
            stopped = True
            cases.append({"name": f"task:{task.stem}", "kind": "task", "result": "skipped",
                          "detail": f"not run: the budget of ${budget:.2f} was spent", "tokens": 0, "cost_usd": 0.0})
            continue
        try:
            if not isinstance(yaml.safe_load(task.read_text(encoding="utf-8")), dict):
                raise ValueError("not a mapping")
        except (OSError, ValueError, yaml.YAMLError) as e:
            cases.append(_case(f"task:{task.stem}", "task", False, f"{task.name} is not a task ({e})",
                               tokens=0, cost_usd=0.0))
            continue
        case = _run_task(root, runner, task, model, budget - spent)
        spent += case["cost_usd"]
        cases.append(case)
    return cases, stopped


# --- the receipt ------------------------------------------------------------------------------------------------------

def receipt(kind: str, cases: list[dict[str, Any]], *, model: str | None, budget: float | None,
            pass_rate: float, stopped: bool) -> dict[str, Any]:
    run = [c for c in cases if c["result"] != "skipped"]
    passed = sum(c["result"] == "pass" for c in run)
    rate = passed / len(run) if run else 0.0
    if kind == "mcp-server":
        result = "pass" if run and passed == len(run) else "fail"
    else:
        result = "incomplete" if stopped else "pass" if run and rate >= pass_rate else "fail"
    return {"schema": SCHEMA, "kind": kind, "result": result, "model": model, "budget_usd": budget,
            "pass_rate": round(rate, 4), "required_pass_rate": pass_rate if kind != "mcp-server" else 1.0,
            "stopped_at_budget": stopped, "tokens": sum(int(c.get("tokens", 0)) for c in cases),
            "cost_usd": round(sum(float(c.get("cost_usd", 0.0)) for c in cases), 6), "cases": cases}


def summary(r: dict[str, Any]) -> str:
    rows = [f"## Artifact check ({r['kind']}): {r['result']}", ""]
    if r["kind"] != "mcp-server":
        rows.append(f"Model {r['model']}, ${r['cost_usd']:.4f} of ${r['budget_usd']:.2f}, {r['tokens']} tokens, "
                    f"pass rate {r['pass_rate']:.0%} (needs {r['required_pass_rate']:.0%}).")
        rows.append("")
    rows += ["| Case | Result | Detail |", "| --- | --- | --- |"]
    rows += [f"| {c['name']} | {c['result']} | {c['detail'].replace('|', '/')[:200]} |" for c in r["cases"]]
    return "\n".join(rows) + "\n"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("kind", choices=KINDS)
    p.add_argument("--root", default=".", help="the repository to check")
    p.add_argument("--server", help="mcp-server: the command that starts the server over stdio")
    p.add_argument("--runner", help="agent, bot: the command that runs one task file")
    p.add_argument("--model", default="", help="agent, bot: the model the runner uses")
    p.add_argument("--budget-usd", type=float, default=1.0)
    p.add_argument("--pass-rate", type=float, default=1.0, help="agent, bot: the share of tasks that must pass")
    p.add_argument("--out", default="artifact-check.json")
    a = p.parse_args(argv)
    root = Path(a.root).resolve()
    if a.kind == "mcp-server":
        if not a.server:
            p.error("mcp-server needs --server")
        r = receipt(a.kind, check_mcp_server(root, a.server), model=None, budget=None, pass_rate=1.0, stopped=False)
    else:
        if not a.runner or not a.model:
            p.error(f"{a.kind} needs --runner and --model")
        if not (a.budget_usd > 0 and 0 < a.pass_rate <= 1):
            p.error("--budget-usd must be above 0 and --pass-rate between 0 and 1")
        cases, stopped = check_agent(root, a.runner, a.model, a.budget_usd)
        r = receipt(a.kind, cases, model=a.model, budget=a.budget_usd, pass_rate=a.pass_rate, stopped=stopped)
    Path(a.out).write_text(json.dumps(r, indent=2) + "\n", encoding="utf-8")
    text = summary(r)
    print(text)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as fh:
            fh.write(text)
    return 0 if r["result"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
