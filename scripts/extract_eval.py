#!/usr/bin/env python3
"""Extraction eval for the extract-records skill (KAN-464).

    python scripts/extract_eval.py                    # fixture mode: grade the recorded proposals; no key, no network
    python scripts/extract_eval.py --require-fresh    # also fail when the recording predates the current SKILL.md
    python scripts/extract_eval.py --live             # live mode: Claude Code CLI on your login (--runner claude-cli)
    python scripts/extract_eval.py --live --runner api  # live mode through the API (ANTHROPIC_API_KEY)
    python scripts/extract_eval.py --live --record    # ...and replace evals/extract-records/recorded/ with the run
    python scripts/extract_eval.py --out DIR          # also write DIR/result.json and DIR/summary.md

The extractor and the grader are separate steps. The extractor sees a case's before/ tree and its scope map only,
never after/ or the expected list; scripts/extract_grade.py grades its proposal afterwards. Exit 1 when a gate fails.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path
from typing import Any

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import extract_grade as grade

REPO = Path(__file__).resolve().parents[1]
EVAL = REPO / "evals/extract-records"
API = "https://api.anthropic.com/v1"
FILE_BLOCK = re.compile(r'<file path="([^"]+)">\n(.*?)\n?</file>', re.DOTALL)
HARNESS_NOTE = """\
## Eval harness

You run inside an extraction eval, without a shell. The knowledge repository is given in full below, so steps that
call `ai-dlc knowledge records search` or `captured` are answered by reading it; `ai-dlc knowledge check` runs after
you. Do not open a pull request. Instead, output every file you would propose, each as
<file path="relative/path.md">full file content</file>, followed by the PR body you would write as
<pr_body>...</pr_body>. Output nothing else."""


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def render_skill(config: dict, scope_map: str | None) -> str:
    params = yaml.safe_load((REPO / config["profile"]).read_text())["params"]
    if scope_map:
        params = {**params, "scope_map": scope_map}
    return re.sub(
        r"\{\{(\w+)\}\}", lambda m: str(params.get(m.group(1), m.group(0))), (REPO / config["skill"]).read_text()
    )


def repository_text(before: Path) -> str:
    parts = [f'<file path="{p}">\n{b.decode("utf-8", "replace")}</file>' for p, b in grade.files(before).items()]
    return "\n".join(parts)


def estimate_tokens(config: dict, case: dict, proposal: Path) -> dict[str, Any]:
    """About four characters a token: the rendered skill and before/ in, the proposed files out."""
    skill = render_skill(config, case.get("scope_map")) if (REPO / config["skill"]).is_file() else ""
    tokens_in = (len(skill) + len(HARNESS_NOTE) + len(repository_text(case["root"] / "before"))) // 4
    tokens_out = sum(len(b) for b in grade.files(proposal).values()) // 4
    return {"input": tokens_in, "output": tokens_out, "estimated": True}


def latest_model(key: str) -> str:
    request = urllib.request.Request(f"{API}/models?limit=100", headers=_headers(key))
    with urllib.request.urlopen(request, timeout=60) as response:
        models = json.load(response)["data"]
    return models[0]["id"]  # the API lists the newest first


def _headers(key: str) -> dict[str, str]:
    return {"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"}


def prompt(config: dict, case: dict) -> tuple[str, str]:
    """(system, user) for one case: the rendered skill, and the case's before/ tree. Never after/."""
    system = render_skill(config, case.get("scope_map")) + "\n\n" + HARNESS_NOTE
    before = case["root"] / "before"
    user = f"The Source to process is `{case['source']}`.\n\n<repository>\n{repository_text(before)}\n</repository>"
    return system, user


def write_proposal(text: str, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    for path, content in FILE_BLOCK.findall(text):
        target = (dest / path).resolve()
        if dest.resolve() not in target.parents:
            continue  # a path outside the case is not a proposal
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content.rstrip("\n") + "\n")


def extract_api(config: dict, case: dict, model: str, dest: Path) -> dict[str, Any]:
    """Runner `api`: one Messages API call with ANTHROPIC_API_KEY."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise SystemExit("--runner api needs ANTHROPIC_API_KEY")
    system, user = prompt(config, case)
    payload = {"model": model, "max_tokens": 16000, "system": system, "messages": [{"role": "user", "content": user}]}
    request = urllib.request.Request(f"{API}/messages", json.dumps(payload).encode(), _headers(key))
    with urllib.request.urlopen(request, timeout=600) as response:
        reply = json.load(response)
    write_proposal("".join(block.get("text", "") for block in reply["content"]), dest)
    usage = reply.get("usage", {})
    return {"input": usage.get("input_tokens", 0), "output": usage.get("output_tokens", 0), "estimated": False}


def cli_command(model: str) -> list[str]:
    """Headless Claude Code with every tool off and no MCP servers: it can only answer from the prompt."""
    exe = shutil.which("claude") or "claude"
    return [exe, "-p", "--model", model, "--output-format", "json", "--tools", "", "--allowedTools", "",
            "--strict-mcp-config", "--no-session-persistence"]  # fmt: skip


def extract_cli(config: dict, case: dict, model: str, dest: Path) -> dict[str, Any]:
    """Runner `claude-cli`: the Claude Code CLI on the user's own login (CLAUDE_CODE_OAUTH_TOKEN in CI).

    It runs in an empty temporary directory holding only the prompt, with no tools, so after/ and the case list are
    out of its reach.
    """
    system, user = prompt(config, case)
    with tempfile.TemporaryDirectory(prefix="extract-cli-") as work:
        run = subprocess.run(
            cli_command(model), input=f"{system}\n\n{user}", capture_output=True, text=True, cwd=work,
            timeout=900, check=False,
        )  # fmt: skip
    try:
        reply = json.loads(run.stdout)
    except json.JSONDecodeError:
        reply = {"is_error": True, "result": (run.stdout or run.stderr).strip()}
    if run.returncode or reply.get("is_error"):
        raise SystemExit(f"claude CLI failed ({run.returncode}): {str(reply.get('result'))[:500]}")
    write_proposal(str(reply.get("result", "")), dest)
    usage = reply.get("usage", {})
    tokens_in = sum(usage.get(k, 0) for k in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))
    return {"input": tokens_in, "output": usage.get("output_tokens", 0), "estimated": False}


RUNNERS = {"claude-cli": extract_cli, "api": extract_api}


def baseline_is_live(path: Path) -> bool:
    """True once a live run recorded the fixtures; until then a stale recording only warns."""
    return path.is_file() and json.loads(path.read_text()).get("live") is True


def mark_live(path: Path) -> None:
    data = json.loads(path.read_text()) if path.is_file() else {}
    data["live"] = True
    path.write_text(json.dumps(data, indent=2) + "\n")


def gates(summary: dict, config: dict, stale: list[str]) -> list[str]:
    """O3 gates (KAN-474): recall, and substantive edits under 10%. Cosmetic and total edits are reported only."""
    t = config["thresholds"]
    out = []
    if summary["recall"] < t["recall_min"]:
        out.append(f"recall {summary['recall']:.0%} is below {t['recall_min']:.0%} (O3)")
    if summary["substantive_rate"] >= t["substantive_max"]:
        named = "; ".join(f"{e['case']} {e['record']} ({', '.join(e['fields'])})" for e in summary["substantive_edits"])
        out.append(
            f"{summary['substantive_rate']:.0%} of records need a substantive edit or deletion; O3 allows under "
            f"{t['substantive_max']:.0%}: {named}"
        )
    for key in ("broken_links", "limit_failures", "unfiled_sources", "check_failures"):
        if summary[key]:
            out.append(f"{key.replace('_', ' ')}: {summary[key]}")
    if summary["cost_usd"] > t["cost_usd_max"]:
        out.append(f"cost ${summary['cost_usd']:.2f} is over ${t['cost_usd_max']:.2f} a run")
    return out + stale


def _fields(top: list) -> str:
    return ", ".join(f"{f} {n}" for f, n in top) or "-"


def preflight(repo: Path = REPO) -> tuple[str, str]:
    """Whether CI can measure: ("run" | "skip" | "fail", reason). Missing but registered skill fails."""
    config = yaml.safe_load((repo / "evals/extract-records/config.yaml").read_text())
    skill = repo / config["skill"]
    targets = repo / "shared/work-system/targets.yaml"
    listed = targets.is_file() and "extract-records" in (yaml.safe_load(targets.read_text()) or {}).get("skills", [])
    copies = sorted(p.parent.as_posix() for p in repo.glob("harnesses/*/skills/extract-records/SKILL.md"))
    if skill.is_file():
        return "run", f"{config['skill']} present"
    if listed or copies:
        where = "shared/work-system/targets.yaml" if listed else ", ".join(copies)
        return "fail", f"{where} registers extract-records but {config['skill']} is missing"
    return "skip", "extract-records is not on this branch yet (KAN-435, team-harness #20): nothing to measure"


def markdown(result: dict) -> str:
    s, run = result["summary"], result["run"]
    old = result.get("reported", {}).get("edit_or_drop_max", 0.25)
    lines = [
        f"# Extraction eval: {result['mode']}",
        "",
        (
            f"Skill `{run.get('skill_sha256', '?')[:12]}` ({run.get('skill_ref', 'unknown ref')}); extractor: "
            f"{run.get('extractor', run.get('model'))}."
        ),
        "",
        (
            "| Precision | Recall | Substantive (gate) | Cosmetic | Total edit or drop (old gate) | Needs human "
            "| Top fields | Tokens (in/out) | Cost |"
        ),
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
        (
            f"| {s['precision']:.0%} | {s['recall']:.0%} | {s['substantive_rate']:.0%} ({s['substantive']}) | "
            f"{s['cosmetic_rate']:.0%} ({s['cosmetic']}) | {s['edit_or_drop_rate']:.0%} (was gated under {old:.0%}) | "
            f"{s['needs_human']} | {_fields(s['top_fields'])} | "
            f"{s['tokens_in']:,}/{s['tokens_out']:,}{' (est.)' if s['tokens_estimated'] else ''} | ${s['cost_usd']:.2f} |"
        ),
        "",
        (
            f"{s['matched']} of {s['expected']} expected records found; {s['produced']} produced. "
            f"knowledge check ran on {s['check_ran']} cases with {s['check_failures']} failures."
        ),
        "",
        *(
            [
                (
                    f"Blind cases only: precision {s['blind']['precision']:.0%}, recall {s['blind']['recall']:.0%}, "
                    f"substantive {s['blind']['substantive_rate']:.0%}, cosmetic {s['blind']['cosmetic_rate']:.0%}, "
                    f"{s['blind']['edit_or_drop_rate']:.0%} to edit or drop in total."
                ),
                "",
            ]
            if s.get("blind")
            else []
        ),
        "| Case | Blind | Produced | Expected | Matched | Substantive | Cosmetic | Top fields | Extra | Missed | Problems |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for c in result["cases"]:
        sc = grade.severity_counts(c)
        problems = (
            [f"wrong: {w['produced']} ({w['why']})" for w in c["wrong"]]
            + c["limits"]
            + c["broken_links"]
            + (c["check"] or [])
            + ([] if c["source_filed"] else ["source not filed"])
        )
        lines.append(
            f"| {c['id']} | {'yes' if c['blind'] else 'no'} | {c['produced']} | {c['expected']} | {len(c['matched'])} | "
            f"{sc['substantive_rate']:.0%} | {sc['cosmetic_rate']:.0%} | {_fields(grade.top_fields(sc['fields']))} | "
            f"{', '.join(c['extra']) or '-'} | {', '.join(c['missed']) or '-'} | "
            f"{'; '.join(problems) or '-'} |"
        )
    if s["substantive_edits"]:
        lines += ["", "**Substantive edits** (case, record, fields):"]
        lines += [f"- {e['case']} `{e['record']}`: {', '.join(e['fields'])}" for e in s["substantive_edits"]]
    if result["pending"]:
        lines += ["", f"**Pending** (no recording yet, not graded): {', '.join(result['pending'])}"]
    if result["needs_human"]:
        lines += ["", "**Needs a human** (not graded; does the description give the why?):"]
        lines += [f"- {n['case']} `{n['record']}`: {n['why']}" for n in result["needs_human"]]
    lines += ["", "**Result:** " + ("pass" if not result["failures"] else "fail")]
    lines += [f"- {f}" for f in result["failures"]]
    return "\n".join(lines) + "\n"


def run(args: argparse.Namespace) -> dict[str, Any]:
    config = yaml.safe_load((EVAL / "config.yaml").read_text())
    cases = grade.load_cases(EVAL / "cases.yaml", REPO)
    if args.case:
        cases = [c for c in cases if c["id"] in args.case]
        if args.record:
            raise SystemExit("--record replaces every recording: run all cases")
    skill = REPO / config["skill"]
    if args.live:
        model = args.model or config["model"]
        if model == "latest":
            model = latest_model(os.environ.get("ANTHROPIC_API_KEY") or "")
        recorded = Path(tempfile.mkdtemp(prefix="extract-eval-"))
        meta = {
            "skill_sha256": sha256(skill),
            "model": model,
            "extractor": f"live: {args.runner} runner, {model}",
            "blind": {},
            "tokens": {},
        }
        for case in cases:
            meta["tokens"][case["id"]] = RUNNERS[args.runner](config, case, model, recorded / case["id"])
            meta["blind"][case["id"]] = True
        (recorded / "run.json").write_text(json.dumps(meta, indent=2) + "\n")
        if args.record:
            shutil.rmtree(EVAL / "recorded", ignore_errors=True)
            shutil.copytree(recorded, EVAL / "recorded")
            mark_live(EVAL / "baseline.json")
    else:
        recorded = EVAL / "recorded"
        meta = json.loads((recorded / "run.json").read_text())
    results = []
    tokens_in = tokens_out = 0
    estimated = False
    pending = set(meta.get("pending", []))
    waiting = []
    for case in cases:
        proposal = recorded / case["id"]
        if case["id"] in pending and not proposal.is_dir():
            waiting.append(case["id"])  # its blind recording is not in yet; graded once it is
            continue
        if not proposal.is_dir():
            raise FileNotFoundError(f"no recording for {case['id']} in {recorded}")
        result = grade.grade_case(case, case["root"], proposal)
        result["blind"] = bool(meta.get("blind", {}).get(case["id"]))
        result["needs_human"] = [n["record"] for n in meta.get("needs_human", []) if n.get("case") == case["id"]]
        usage = meta.get("tokens", {}).get(case["id"]) or estimate_tokens(config, case, proposal)
        tokens_in, tokens_out = tokens_in + usage["input"], tokens_out + usage["output"]
        estimated = estimated or usage.get("estimated", False)
        results.append(result)
    summary = grade.summarize(results)
    price = config["price_usd_per_mtok"]
    summary.update(
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        tokens_estimated=estimated,
        cost_usd=round((tokens_in * price["input"] + tokens_out * price["output"]) / 1e6, 4),
    )
    blind = [r for r in results if r["blind"]]
    summary["blind"] = grade.summarize(blind) if blind else None
    stale = []
    if skill.is_file() and sha256(skill) != meta.get("skill_sha256"):
        note = "the recording predates the current SKILL.md: rerun with --live --record"
        if args.require_fresh and baseline_is_live(EVAL / "baseline.json"):
            stale.append(note)
        else:  # no live recording yet: a hand-made recording is always behind, so only warn
            print(f"warning: {note}", file=sys.stderr)
    if meta.get("model") != config["model"]:
        print(f"note: recorded with {meta.get('model')}; live runs use {config['model']}", file=sys.stderr)
    run_meta = {k: v for k, v in meta.items() if k not in ("tokens", "blind", "pending", "needs_human")}
    failures = gates(summary, config, stale)
    return {
        "mode": "live" if args.live else "fixture",
        "run": run_meta,
        "summary": summary,
        "cases": results,
        "pending": waiting,
        "needs_human": meta.get("needs_human", []),
        "reported": config.get("reported", {}),
        "failures": failures,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("--live", action="store_true", help="run the model on every case")
    parser.add_argument("--runner", choices=sorted(RUNNERS), default="claude-cli",
                        help="live: claude-cli (your Claude Code login; default) or api (ANTHROPIC_API_KEY)")  # fmt: skip
    parser.add_argument("--model", help="model id for --live, or 'latest' (api); default: config.yaml's model")
    parser.add_argument("--case", action="append", help="only this case id (repeatable)")
    parser.add_argument("--record", action="store_true", help="with --live, replace the recorded proposals")
    parser.add_argument("--require-fresh", action="store_true", help="fail when the recording predates SKILL.md")
    parser.add_argument("--out", type=Path, help="write result.json and summary.md here")
    parser.add_argument("--preflight", action="store_true", help="say whether CI can measure; exit 1 on fail")
    args = parser.parse_args(argv)
    if args.preflight:
        verdict, reason = preflight()
        print(f"{verdict}: {reason}")
        if os.environ.get("GITHUB_OUTPUT"):
            with open(os.environ["GITHUB_OUTPUT"], "a") as out:
                out.write(f"run={'true' if verdict == 'run' else 'false'}\nreason={reason}\n")
        return 1 if verdict == "fail" else 0
    try:
        result = run(args)
    except FileNotFoundError as error:
        print(f"extract eval: {error}", file=sys.stderr)
        return 2
    summary = markdown(result)
    print(summary)
    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "result.json").write_text(json.dumps(result, indent=2, default=str) + "\n")
        (args.out / "summary.md").write_text(summary)
    return 1 if result["failures"] else 0


if __name__ == "__main__":
    sys.exit(main())
