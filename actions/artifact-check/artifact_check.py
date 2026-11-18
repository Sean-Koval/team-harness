#!/usr/bin/env python3
"""The artifact check (KAN-517): one eval gate a scaffolded repository runs on every PR, before SRE and infosec see it.

mcp-server: start the server over stdio, list its tools, check each input schema (JSON Schema 2020-12, an object) and
run every golden call in `evals/golden/*.json` (`tool`, `arguments`, and `structured_content` or `"is_error": true`).
The client speaks the protocol itself, so a server in any language can be checked.

agent or bot: run `evals/tasks/*.yaml` (`id`, `input`, `expect.contains`) through the repository's own command, one
task at a time, under a budget priced from the usage hook's price table and checked between tasks. The command reads
the task as JSON on stdin and prints `{"output": ..., "usage": {...} or [{...}, ...]}`. No task starts once the budget
is spent; the rest are reported `not_run`. One task can overrun the budget, and a run that did fails. A model the table
doesn't price is refused, since its budget couldn't be held.

Either way it writes a receipt (receipt.schema.json beside this file) and, on Actions, a job summary. It exits 1 when
the check fails and 2 when it can't run. Needs only the repository's own model key, in the agent command's environment.
"""

from __future__ import annotations

import argparse
import json
import os
import queue
import shlex
import signal
import subprocess
import sys
import threading
import time
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
HOOK = HERE.parents[1] / "shared" / "work-system" / "hooks" / "usage_session_end.py"
SCHEMA_ID = "team-harness.artifact-check/v1"
PROTOCOL = "2025-06-18"
MAX_PAGES = 100


class CantRun(Exception):
    """The check could not run (bad inputs, a server that won't start): exit 2, not a failed case."""


def case(cid: str, status: str, detail: str = "", **extra: Any) -> dict:
    return {"id": cid, "status": status, "detail": detail, **extra}


# ---------------------------------------------------------------- processes


def spawn(command: str | list[str], cwd: Path, **kw: Any) -> subprocess.Popen:
    """Start a command in a process group of its own, so the check can stop everything it started."""
    group: dict[str, Any] = ({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt"
                             else {"start_new_session": True})
    try:  # stderr is inherited: it goes to the job log, where the command's own errors help
        return subprocess.Popen(command, cwd=cwd, text=True, encoding="utf-8", errors="replace", **group, **kw)
    except (OSError, ValueError) as e:
        raise CantRun(f"the command could not start: {e}") from e


def stop(proc: subprocess.Popen) -> None:
    """Kill the command's whole process group (wrappers such as `uv run` or `npx` leave children) and reap it."""
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True, timeout=30)
        else:
            os.killpg(proc.pid, signal.SIGKILL)
    except (OSError, subprocess.SubprocessError):
        pass  # the group is already gone
    if proc.poll() is None:
        proc.kill()
    proc.wait()


# ---------------------------------------------------------------- mcp-server


class StdioServer:
    """A minimal MCP client over stdio: newline-delimited JSON-RPC, one request at a time."""

    def __init__(self, command: str | list[str], cwd: Path, timeout: float, end: float):
        self.timeout, self.end, self.next_id = timeout, end, 0
        self.proc = spawn(command, cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, bufsize=1)
        # lines arrive through a queue, so a server that hangs without writing still hits the timeout
        self.lines: queue.Queue[str] = queue.Queue()
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self) -> None:
        assert self.proc.stdout is not None
        for line in self.proc.stdout:
            self.lines.put(line)
        self.lines.put("")  # end of output: the server exited

    def _send(self, msg: dict) -> None:
        assert self.proc.stdin is not None
        try:
            self.proc.stdin.write(json.dumps(msg) + "\n")
            self.proc.stdin.flush()
        except OSError as e:
            raise CantRun("the server stopped reading its input") from e

    def request(self, method: str, params: dict) -> dict:
        self.next_id += 1
        self._send({"jsonrpc": "2.0", "id": self.next_id, "method": method, "params": params})
        deadline = min(time.monotonic() + self.timeout, self.end)
        while (left := deadline - time.monotonic()) > 0:
            try:
                line = self.lines.get(timeout=left)
            except queue.Empty:
                break
            if not line:
                self.lines.put("")
                raise CantRun(f"the server exited during {method}")
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue  # stdout noise is the server's bug, but not this check's to judge
            if isinstance(msg, dict) and msg.get("id") == self.next_id and "method" not in msg:
                return msg
        raise CantRun(f"no answer to {method} in time")

    def result(self, method: str, params: dict) -> dict:
        r = self.request(method, params)
        if not isinstance(r.get("result"), dict):
            raise CantRun(f"{method} failed: {(r.get('error') or {}).get('message', 'no result')}")
        return r["result"]

    def start(self) -> None:
        self.result("initialize", {"protocolVersion": PROTOCOL, "capabilities": {},
                                   "clientInfo": {"name": "artifact-check", "version": "1"}})
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def tools(self) -> list[dict]:
        found: list[dict] = []
        cursor, seen = None, set()
        for _ in range(MAX_PAGES):
            r = self.result("tools/list", {"cursor": cursor} if cursor else {})
            found += [t for t in r.get("tools") or [] if isinstance(t, dict)]
            cursor = r.get("nextCursor")
            if not cursor:
                return found
            if cursor in seen:
                raise CantRun("tools/list repeated a page cursor")
            seen.add(cursor)
        raise CantRun(f"tools/list ran past {MAX_PAGES} pages")

    def close(self) -> None:
        try:
            if self.proc.stdin:
                self.proc.stdin.close()
            self.proc.wait(5)  # a well-behaved server exits when its input closes
        except (OSError, subprocess.TimeoutExpired):
            pass
        stop(self.proc)


def check_tool(tool: dict) -> str | None:
    """What is wrong with a listed tool, or None."""
    from jsonschema import Draft202012Validator
    from jsonschema.exceptions import SchemaError

    if not str(tool.get("description") or "").strip():
        return "it has no description"
    schema = tool.get("inputSchema")
    if not isinstance(schema, dict) or schema.get("type") != "object":
        return "its input schema is not an object"
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as e:
        return f"its input schema is invalid: {e.message}"
    if not set(schema.get("required", [])) <= set(schema.get("properties", {})):
        return "its input schema requires a property it doesn't define"
    return None


def golden(server: StdioServer, spec: dict, schemas: dict[str, dict], listed: set[str]) -> str | None:
    from jsonschema import Draft202012Validator, ValidationError

    tool, arguments = spec.get("tool"), spec.get("arguments", {})
    if tool not in schemas:
        return f"{tool} failed its tool check" if tool in listed else f"the server lists no tool {tool!r}"
    try:
        Draft202012Validator(schemas[tool]).validate(arguments)
    except ValidationError as e:
        return f"its arguments don't fit {tool}'s input schema: {e.message}"
    r = server.request("tools/call", {"name": tool, "arguments": arguments})
    if "error" in r:  # a JSON-RPC error is the server failing, never the tool error a case expects
        return f"{tool} gave a protocol error: {(r['error'] or {}).get('message')}"
    result = r.get("result")
    if not isinstance(result, dict):
        return f"{tool} answered with neither a result nor an error"
    if spec.get("is_error"):
        return None if result.get("isError") else f"{tool} succeeded, but the case expects a tool error"
    if result.get("isError"):
        return f"{tool} returned a tool error"
    if "structured_content" in spec and result.get("structuredContent") != spec["structured_content"]:
        return f"{tool} returned {json.dumps(result.get('structuredContent'))[:200]}"
    return None


def check_mcp(repo: Path, command: str | list[str], timeout: float, end: float) -> list[dict]:
    goldens = sorted((repo / "evals" / "golden").glob("*.json"))
    server = StdioServer(command, repo, timeout, end)
    try:
        server.start()
        tools = server.tools()
        if not tools:
            return [case("tools", "fail", "the server lists no tools")]
        cases, schemas, listed = [], {}, set()
        for i, t in enumerate(tools):
            name = t.get("name")
            if not isinstance(name, str) or not name:
                cases.append(case(f"tool:#{i + 1}", "fail", "it has no name"))
                continue
            why = "the server lists it twice" if name in listed else check_tool(t)
            listed.add(name)
            if why is None:
                schemas[name] = t["inputSchema"]
            cases.append(case(f"tool:{name}", "fail" if why else "pass", why or ""))
        covered, dead = set(), None
        for path in goldens:
            cid = f"golden:{path.stem}"
            try:
                spec = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
                cases.append(case(cid, "fail", f"{path.name} can't be read as JSON: {e}"))
                continue
            if not isinstance(spec, dict):
                cases.append(case(cid, "fail", f"{path.name} is not a JSON object"))
                continue
            if not isinstance(spec.get("tool"), str) or not isinstance(spec.get("arguments", {}), dict):
                cases.append(case(cid, "fail", f"{path.name} needs a tool name and an arguments object"))
                continue
            covered.add(spec["tool"])
            if not dead and time.monotonic() >= end:
                dead = "not run: the run's time limit was reached"
            if dead:
                cases.append(case(cid, "not_run", dead))
                continue
            try:
                why = golden(server, spec, schemas, listed)
            except CantRun as e:  # the server died or hung on this call: that is this case's failure
                why, dead = str(e), f"not run after an earlier call failed: {e}"
            cases.append(case(cid, "fail" if why else "pass", why or ""))
        for name in sorted(listed - covered):
            cases.append(case(f"coverage:{name}", "fail", f"no golden case under evals/golden/ calls {name}"))
        return cases
    finally:
        server.close()


# ---------------------------------------------------------------- agent or bot


def load_prices() -> tuple[dict, Any]:
    spec = spec_from_file_location("artifact_check_usage_hook", HOOK)
    if spec is None or spec.loader is None:
        raise CantRun(f"the price table's hook is missing: {HOOK}")
    hook = module_from_spec(spec)
    spec.loader.exec_module(hook)
    return json.loads(hook.PRICES.read_text(encoding="utf-8")), hook


def run_task(command: str | list[str], repo: Path, task: dict, env: dict, timeout: float) -> tuple[int | None, str]:
    """The command's exit code (None when it ran out of time) and its stdout."""
    proc = spawn(command, repo, stdin=subprocess.PIPE, stdout=subprocess.PIPE, env=env)
    try:
        out, _ = proc.communicate(json.dumps(task), timeout=max(timeout, 0.1))
        return proc.returncode, out
    except subprocess.TimeoutExpired:
        return None, ""
    finally:
        stop(proc)  # also what it left running


def answer(stdout: str) -> dict | None:
    """The JSON object on the command's last stdout line (logs may come first)."""
    try:
        out = json.loads((stdout.strip().splitlines() or [""])[-1])
    except json.JSONDecodeError:
        return None
    return out if isinstance(out, dict) else None


def price(out: dict | None, model: str, prices: dict, hook: Any) -> tuple[float | None, dict]:
    """The answer's cost and tokens; None when its usage is missing or the price table can't price it."""
    usage = (out or {}).get("usage")
    usage = [usage] if isinstance(usage, dict) else usage
    if not isinstance(usage, list) or not usage or not all(
            isinstance(u, dict) and isinstance(u.get("input_tokens"), int) and isinstance(u.get("output_tokens"), int)
            for u in usage):
        return None, {"input": 0, "output": 0}
    used = {k: sum(hook._int(u.get(f"{k}_tokens")) for u in usage) for k in ("input", "output")}
    costs = [hook.request_cost(model, u, prices) for u in usage]
    return (None if None in costs else sum(costs)), used


def check_agent(repo: Path, command: str | list[str], model: str, budget: float, timeout: float,
                end: float) -> tuple[list[dict], dict]:
    import yaml

    prices, hook = load_prices()
    if model not in prices.get("models", {}):
        raise CantRun(f"the price table has no row for {model}, so its budget can't be held")
    tasks = sorted((repo / "evals" / "tasks").glob("*.yaml"))
    if not tasks:
        raise CantRun("no tasks under evals/tasks/")
    spent, tokens, cases, stopped, halt = 0.0, {"input": 0, "output": 0}, [], False, ""
    for path in tasks:
        try:
            task = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, yaml.YAMLError) as e:
            cases.append(case(path.stem, "fail", f"{path.name} can't be read as YAML: {e}"))
            continue
        if not isinstance(task, dict):
            cases.append(case(path.stem, "fail", f"{path.name} is not a mapping"))
            continue
        cid = str(task.get("id") or path.stem)
        expect = task.get("expect")
        wanted = expect.get("contains") if isinstance(expect, dict) else None
        if not isinstance(wanted, list) or not wanted or not all(isinstance(w, str) and w for w in wanted):
            cases.append(case(cid, "fail", f"{path.name} needs expect.contains, a non-empty list of strings"))
            continue
        if not halt and spent >= budget:
            halt, stopped = f"not run: the budget of ${budget:.2f} was spent", True
        if not halt and time.monotonic() >= end:
            halt = "not run: the run's time limit was reached"
        if halt:
            cases.append(case(cid, "not_run", halt))
            continue
        env = {**os.environ, "ARTIFACT_CHECK_MODEL": model, "ARTIFACT_CHECK_BUDGET_USD": f"{budget - spent:.6f}"}
        code, stdout = run_task(command, repo, task, env, min(timeout, end - time.monotonic()))
        out = answer(stdout)
        what = ("ran out of time" if code is None else f"exited {code}" if code
                else "printed no JSON object on its last line" if out is None else "")
        cost, used = price(out, model, prices, hook)
        if cost is None:  # what it spent is unknown, so the budget can't be held: start nothing more
            halt = "not run: an earlier task's cost couldn't be read"
            cases.append(case(cid, "fail", f"the agent command {what or 'answered'}, and its usage couldn't be "
                                           "priced (missing, malformed, or a rate the price table lacks)"))
            continue
        spent += cost
        tokens = {k: tokens[k] + used[k] for k in tokens}
        if what:
            cases.append(case(cid, "fail", f"the agent command {what}", tokens=used, cost_usd=round(cost, 6)))
            continue
        missing = [w for w in wanted if w not in str(out.get("output"))]
        detail = f"the output lacks {missing[0]!r}" if missing else ""
        cases.append(case(cid, "fail" if missing else "pass", detail, tokens=used, cost_usd=round(cost, 6)))
    if spent > budget:  # checked between tasks, so one task can overrun it: that never passes
        cases.append(case("budget", "fail", f"the run spent ${spent:.4f}, over its ${budget:.2f} budget"))
    return cases, {"cost_usd": round(spent, 6), "tokens": tokens, "stopped_at_budget": stopped}


# ---------------------------------------------------------------- receipt


def summary(receipt: dict) -> str:
    head = "passed" if receipt["passed"] else "failed"
    lines = [f"### Artifact check ({receipt['kind']}): {head}", "",
             f"Pass rate {receipt['pass_rate']:.0%} (needs {receipt['min_pass_rate']:.0%})"
             + (f", ${receipt['cost_usd']:.4f} of ${receipt['budget_usd']:.2f} on {receipt['model']}"
                if receipt["model"] else "")
             + (". Stopped at the budget." if receipt["stopped_at_budget"] else "."), "",
             "| Case | Result | Detail |", "| --- | --- | --- |"]
    lines += [f"| {c['id']} | {c['status']} | {c['detail'].replace('|', '/')} |" for c in receipt["cases"]]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--kind", required=True, choices=["mcp-server", "agent", "bot"])
    p.add_argument("--repo", type=Path, default=Path.cwd())
    p.add_argument("--command", required=True, help="the server command (mcp-server) or agent command, as one string")
    p.add_argument("--model", default="claude-haiku-5-5")
    p.add_argument("--budget-usd", type=float, default=1.0)
    p.add_argument("--min-pass-rate", type=float, default=1.0)
    p.add_argument("--timeout", type=float, default=600, help="seconds per server answer or agent task")
    p.add_argument("--time-limit", type=float, default=2700, help="seconds for the whole run; later cases not_run")
    p.add_argument("--out", type=Path, default=Path("artifact-check.json"))
    a = p.parse_args(argv)
    try:
        if not a.command.strip():
            raise CantRun("--command is empty")
        # on Windows CreateProcess splits the string itself; shlex would eat a path's backslashes
        try:
            command = a.command if os.name == "nt" else shlex.split(a.command)
        except ValueError as e:
            raise CantRun(f"--command can't be split into words: {e}") from e
        if not 0 <= a.min_pass_rate <= 1 or a.budget_usd < 0 or a.timeout <= 0 or a.time_limit <= 0:
            raise CantRun("--min-pass-rate must be 0 to 1, --budget-usd at least 0 and the time limits above 0")
        end = time.monotonic() + a.time_limit
        if a.kind == "mcp-server":
            cases, spend = check_mcp(a.repo, command, a.timeout, end), {}
        else:
            cases, spend = check_agent(a.repo, command, a.model, a.budget_usd, a.timeout, end)
    except CantRun as e:
        print(f"artifact-check: {e}", file=sys.stderr)
        return 2
    rate = sum(c["status"] == "pass" for c in cases) / len(cases)
    agent = a.kind != "mcp-server"
    receipt = {
        "schema": SCHEMA_ID, "kind": a.kind, "model": a.model if agent else None,
        "budget_usd": a.budget_usd if agent else None, "cost_usd": spend.get("cost_usd", 0.0),
        "tokens": spend.get("tokens", {"input": 0, "output": 0}), "min_pass_rate": a.min_pass_rate if agent else 1.0,
        "pass_rate": round(rate, 4), "stopped_at_budget": spend.get("stopped_at_budget", False),
        "passed": rate >= a.min_pass_rate if agent else rate == 1.0, "cases": cases,
    }
    from jsonschema import Draft202012Validator

    Draft202012Validator(json.loads((HERE / "receipt.schema.json").read_text(encoding="utf-8"))).validate(receipt)
    a.out.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    text = summary(receipt)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(text)
    print(text)
    return 0 if receipt["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
