"""Rule 9 of the work-system PR check (KAN-558): the artifact check's receipt.

A repository that runs the artifact-check workflow (KAN-517) passes its receipt (artifact-check.json, schema
team-harness.artifact-check/v1, actions/artifact-check/receipt.schema.json) to this check with `artifact-receipt`.
The PR then needs that receipt, well formed, with `passed` true by the check's own rule. A missing receipt fails
unless allow-unverified is set; an unreadable or malformed one, one committed to the repository or the PR, a run over
its budget, or one whose numbers don't add up to a pass always fails. Stdlib only, like the rest of the check.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import PureWindowsPath
from typing import Any

SCHEMA = "team-harness.artifact-check/v1"
_KINDS = {"mcp-server", "agent", "bot"}
_STATUSES = {"pass", "fail", "not_run"}
_FIELDS = {"schema", "kind", "model", "budget_usd", "cost_usd", "tokens", "min_pass_rate", "pass_rate",
           "stopped_at_budget", "over_budget", "passed", "cases"}
_CASE_FIELDS = {"id", "status", "detail", "tokens", "cost_usd"}


def _num(v: Any, top: float | None = None) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0 and (top is None or v <= top)


def _count(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool) and v >= 0


def _tokens(v: Any) -> bool:
    return isinstance(v, dict) and set(v) == {"input", "output"} and _count(v["input"]) and _count(v["output"])


def problems(r: Any) -> list[str]:
    """What keeps `r` from being a v1 receipt: the checks of receipt.schema.json that this rule relies on."""
    if not isinstance(r, dict):
        return ["it is not a JSON object"]
    out = []
    if missing := sorted(_FIELDS - set(r)):
        out.append(f"it has no {', '.join(missing)}")
    if extra := sorted(set(r) - _FIELDS):
        out.append(f"it has fields the schema doesn't: {', '.join(extra)}")
    if r.get("schema") != SCHEMA:
        out.append(f"its schema is {r.get('schema')!r}, not {SCHEMA}")
    if r.get("kind") not in _KINDS:
        out.append(f"its kind {r.get('kind')!r} is not one of {', '.join(sorted(_KINDS))}")
    if r.get("model") is not None and not isinstance(r.get("model"), str):
        out.append("model is not a string or null")
    if r.get("budget_usd") is not None and not _num(r.get("budget_usd")):
        out.append("budget_usd is not a number of 0 or more, or null")
    if not _num(r.get("cost_usd")):
        out.append("cost_usd is not a number of 0 or more")
    for name in ("min_pass_rate", "pass_rate"):
        if not _num(r.get(name), 1):
            out.append(f"{name} is not a number from 0 to 1")
    if not _tokens(r.get("tokens")):
        out.append("tokens is not input and output counts")
    for name in ("stopped_at_budget", "over_budget", "passed"):
        if not isinstance(r.get(name), bool):
            out.append(f"{name} is not true or false")
    cases = r.get("cases")
    if not isinstance(cases, list) or not cases:
        return [*out, "cases is not a list of at least one case"]
    for i, c in enumerate(cases):
        if not (isinstance(c, dict) and set(c) <= _CASE_FIELDS and isinstance(c.get("id"), str) and c["id"]
                and c.get("status") in _STATUSES and isinstance(c.get("detail"), str)
                and ("tokens" not in c or _tokens(c["tokens"])) and ("cost_usd" not in c or _num(c["cost_usd"]))):
            out.append(f"case {i + 1} is not a case (id, status and detail; tokens and cost_usd if given)")
    return out


def _usd(v: Any) -> str:
    return f"${v:g}" if isinstance(v, (int, float)) else "no budget"


def _passes(r: dict[str, Any], min_pass_rate: float | None = None) -> str | None:
    """Why a well-formed receipt doesn't pass, or None. It follows the check's own rule (artifact_check.py): the
    share of cases that passed, with not_run cases counted as not passed, must reach min_pass_rate (all of them for
    an MCP server), and a run over its budget fails. So a run stopped at its budget passes only if the cases it ran
    already carry the rate. A receipt whose `passed` or pass_rate disagrees with its own cases is refused, as a
    hand-edited or broken one. `min_pass_rate`, when the caller sets one, is a floor the receipt can't lower."""
    cases = r["cases"]
    n_pass = sum(c["status"] == "pass" for c in cases)
    rate = n_pass / len(cases)
    if abs(round(rate, 4) - r["pass_rate"]) > 5e-5:
        return f"its cases pass {rate:.0%} but it reports {r['pass_rate']:.0%}"
    need = 1.0 if r["kind"] == "mcp-server" else max(r["min_pass_rate"], min_pass_rate or 0.0)
    ok = rate >= need and not r["over_budget"]
    if r["passed"] and not ok:
        if r["over_budget"]:
            return f"it says passed, but it spent ${r['cost_usd']:.4f}, over its budget of {_usd(r['budget_usd'])}"
        if r["kind"] == "mcp-server":
            return "it says passed, but an MCP server's cases must all pass"
        if min_pass_rate is not None and r["min_pass_rate"] < min_pass_rate:
            return (f"its cases pass {rate:.0%}; it asked for {r['min_pass_rate']:.0%}, but this repository needs "
                    f"{min_pass_rate:.0%}")
        return f"it says passed, but its cases pass {rate:.0%}, against {need:.0%} needed"
    if ok and r["passed"]:
        return None
    if r["over_budget"]:
        return f"it spent ${r['cost_usd']:.4f}, over its budget of {_usd(r['budget_usd'])}"
    if r["stopped_at_budget"]:
        n = sum(c["status"] == "not_run" for c in cases)
        return (f"it stopped at its budget of {_usd(r['budget_usd'])} with {n} case(s) not run, and the cases it ran "
                f"pass {rate:.0%}, against {need:.0%} needed; raise the budget or trim the cases")
    failed = [c for c in cases if c["status"] != "pass"]
    named = "; ".join(f"{c['id']}: {c['detail']}" if c["detail"] else c["id"] for c in failed[:5])
    more = f" (and {len(failed) - 5} more)" if len(failed) > 5 else ""
    return f"pass rate {rate:.0%}, needs {need:.0%}" + (f": {named}{more}" if named else "")


_MISSING = (FileNotFoundError, NotADirectoryError)


def _tracked(workspace: str, path: str) -> bool:
    """Whether git tracks `path` in the checkout: a receipt that is part of the repository came from a commit, not
    from this run. False when git can't say."""
    try:
        out = subprocess.run(["git", "-C", workspace, "ls-files", "--", path], capture_output=True, text=True,
                             timeout=30, check=False)
    except (OSError, subprocess.SubprocessError):
        return False
    return out.returncode == 0 and bool(out.stdout.strip())


def check(path: str, workspace: str, *, allow_unverified: bool = False, changed: list[str] | None = None,
          min_pass_rate: float | None = None) -> tuple[list[str], list[str], list[str]]:
    """(errors, warnings, summary lines) for the receipt at `path`, relative to the checkout at `workspace`.
    `changed` is the PR's changed paths: a receipt the PR itself adds or edits is refused, since the PR's author
    could write any verdict into it."""
    win = PureWindowsPath(path)
    if os.path.isabs(path) or path.startswith(("/", "\\")) or win.drive or ".." in win.parts:
        return [f"artifact-receipt {path!r} must be a path inside the checkout"], [], []
    norm = path.replace("\\", "/").removeprefix("./")
    if norm in (changed or []) or _tracked(workspace, norm):
        why = (f"the artifact check's receipt {path} is a file in the repository or in this PR; it must be the one "
               "the artifact-check job wrote on this run, so keep it out of git")
        return [why], [], []
    full = os.path.join(workspace, path)
    root = os.path.realpath(workspace)
    if os.path.lexists(full) and os.path.commonpath([root, os.path.realpath(full)]) != root:
        return [f"the artifact check's receipt {path} links to a file outside the checkout"], [], []
    try:
        with open(full, encoding="utf-8") as fh:
            text = fh.read()
    except _MISSING:
        msg = (f"there is no artifact check receipt at {path}; did the artifact-check job run and hand its receipt "
               "to this job?")
        if allow_unverified:
            return [], [msg + " Passing it unverified because allow-unverified is set"], []
        return [msg], [], []
    except (OSError, ValueError) as e:
        return [f"the artifact check's receipt {path} could not be read ({type(e).__name__})"], [], []
    try:
        r = json.loads(text)
    except ValueError:
        return [f"the artifact check's receipt {path} is not JSON"], [], []
    if bad := problems(r):
        return [f"the artifact check's receipt {path} is not a {SCHEMA} receipt: {'; '.join(bad)}"], [], []
    why = _passes(r, min_pass_rate)
    errors = [f"the artifact check ({r['kind']}) didn't pass: {why}"] if why else []
    spent = f", ${r['cost_usd']:.4f} spent" if r["kind"] != "mcp-server" else ""
    passed = sum(c["status"] == "pass" for c in r["cases"])
    verdict = "pass" if why is None else "fail"
    lines = ["", "### Artifact check", "",
             f"{r['kind']}: {verdict}, {passed} of {len(r['cases'])} cases passed{spent}.", ""]
    return errors, [], lines
