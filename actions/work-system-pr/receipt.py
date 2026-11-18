"""Rule 9 of the work-system PR check (KAN-517): the artifact check's receipt.

A repository that runs the artifact-check workflow passes its receipt (artifact-check.json, schema
team-harness.artifact-check/v1, actions/artifact-check/receipt.schema.json) to this check with `artifact-receipt`.
The PR then needs that receipt, well formed, with result `pass`. A missing or unreadable receipt fails, unless
allow-unverified is set; a run stopped at its budget (`incomplete`) never passes. Stdlib only, like the rest of the check.
"""

from __future__ import annotations

import json
import os
from pathlib import PureWindowsPath
from typing import Any

SCHEMA = "team-harness.artifact-check/v1"
_KINDS = {"mcp-server", "agent", "bot"}
_RESULTS = {"pass", "fail", "incomplete"}
_CASE_KINDS = {"server", "tool", "golden", "task"}
_CASE_RESULTS = {"pass", "fail", "skipped"}


def _num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0


def problems(r: Any) -> list[str]:
    """What keeps `r` from being a v1 receipt; the checks receipt.schema.json makes that this check relies on."""
    if not isinstance(r, dict):
        return ["it is not a JSON object"]
    out = []
    if r.get("schema") != SCHEMA:
        out.append(f"its schema is {r.get('schema')!r}, not {SCHEMA}")
    if r.get("kind") not in _KINDS:
        out.append(f"its kind {r.get('kind')!r} is not one of {', '.join(sorted(_KINDS))}")
    if r.get("result") not in _RESULTS:
        out.append(f"its result {r.get('result')!r} is not one of {', '.join(sorted(_RESULTS))}")
    if not isinstance(r.get("stopped_at_budget"), bool):
        out.append("stopped_at_budget is not true or false")
    for name in ("pass_rate", "required_pass_rate", "cost_usd"):
        if not _num(r.get(name)):
            out.append(f"{name} is not a number of 0 or more")
    cases = r.get("cases")
    if not isinstance(cases, list):
        return [*out, "cases is not a list"]
    for i, c in enumerate(cases):
        if not (isinstance(c, dict) and isinstance(c.get("name"), str) and c["name"]
                and c.get("kind") in _CASE_KINDS and c.get("result") in _CASE_RESULTS
                and isinstance(c.get("detail"), str)):
            out.append(f"case {i + 1} is not a case (name, kind, result and detail)")
    return out


def check(path: str, workspace: str, *, allow_unverified: bool = False) -> tuple[list[str], list[str], list[str]]:
    """(errors, warnings, summary lines) for the receipt at `path`, relative to the checkout at `workspace`."""
    errors: list[str] = []
    warnings: list[str] = []
    win = PureWindowsPath(path)
    if os.path.isabs(path) or path.startswith(("/", "\\")) or win.drive or ".." in win.parts:
        return [f"artifact-receipt {path!r} must be a path inside the checkout"], [], []
    try:
        with open(os.path.join(workspace, path), encoding="utf-8") as fh:
            r = json.load(fh)
    except (OSError, ValueError) as e:
        msg = (f"the artifact check's receipt {path} could not be read ({type(e).__name__}); did the artifact-check "
               "job run and hand its receipt to this job?")
        (warnings if allow_unverified else errors).append(
            msg + (" Passing it unverified because allow-unverified is set" if allow_unverified else ""))
        return errors, warnings, []
    bad = problems(r)
    if bad:
        return [f"the artifact check's receipt {path} is not a {SCHEMA} receipt: {'; '.join(bad)}"], [], []
    failed = [c for c in r["cases"] if c["result"] == "fail"]
    skipped = [c for c in r["cases"] if c["result"] == "skipped"]
    head = f"the artifact check ({r['kind']}) says {r['result']}"
    if r["result"] == "incomplete":
        errors.append(f"{head}: it stopped at its budget of ${r.get('budget_usd')} with {len(skipped)} task(s) not "
                      "run, so it can't pass; raise the budget or trim the tasks")
    elif r["result"] == "fail":
        named = "; ".join(f"{c['name']}: {c['detail']}" if c["detail"] else c["name"] for c in failed[:5])
        more = f" (and {len(failed) - 5} more)" if len(failed) > 5 else ""
        errors.append(f"{head}" + (f": {named}{more}" if named else f" (pass rate {r['pass_rate']:.0%})"))
    lines = ["", "### Artifact check", "",
             f"{r['kind']}: {r['result']}, {sum(c['result'] == 'pass' for c in r['cases'])} of "
             f"{len(r['cases'])} cases passed" + (f", ${r['cost_usd']:.4f} spent" if r["kind"] != "mcp-server" else "")
             + "."]
    return errors, warnings, lines
