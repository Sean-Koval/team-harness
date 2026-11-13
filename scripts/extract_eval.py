#!/usr/bin/env python3
"""Extraction eval for the extract-records skill (KAN-464).

    python scripts/extract_eval.py                    # fixture mode: grade the recorded proposals; no key, no network
    python scripts/extract_eval.py --require-fresh    # also fail when the recording predates the current SKILL.md
    python scripts/extract_eval.py --live [--model M] # live mode: run the model on every case (ANTHROPIC_API_KEY)
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


def extract_live(config: dict, case: dict, model: str, key: str, dest: Path) -> dict[str, Any]:
    """Run the skill on one case's before/ tree and write the proposed files to dest. Never reads after/."""
    before = case["root"] / "before"
    system = render_skill(config, case.get("scope_map")) + "\n\n" + HARNESS_NOTE
    user = f"The Source to process is `{case['source']}`.\n\n<repository>\n{repository_text(before)}\n</repository>"
    payload = {"model": model, "max_tokens": 16000, "system": system, "messages": [{"role": "user", "content": user}]}
    request = urllib.request.Request(f"{API}/messages", json.dumps(payload).encode(), _headers(key))
    with urllib.request.urlopen(request, timeout=600) as response:
        reply = json.load(response)
    text = "".join(block.get("text", "") for block in reply["content"])
    for path, content in FILE_BLOCK.findall(text):
        target = (dest / path).resolve()
        if dest.resolve() not in target.parents:
            continue  # a path outside the case is not a proposal
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content.rstrip("\n") + "\n")
    usage = reply.get("usage", {})
    return {"input": usage.get("input_tokens", 0), "output": usage.get("output_tokens", 0), "estimated": False}


def gates(summary: dict, config: dict, baseline: dict | None, stale: list[str]) -> list[str]:
    t = config["thresholds"]
    out = []
    if summary["recall"] < t["recall_min"]:
        out.append(f"recall {summary['recall']:.0%} is below {t['recall_min']:.0%} (O3)")
    if summary["edit_or_drop_rate"] >= t["edit_or_drop_max"]:
        out.append(
            f"{summary['edit_or_drop_rate']:.0%} of records need an edit or deletion; O3 allows under "
            f"{t['edit_or_drop_max']:.0%}"
        )
    for key in ("broken_links", "limit_failures", "unfiled_sources", "check_failures"):
        if summary[key]:
            out.append(f"{key.replace('_', ' ')}: {summary[key]}")
    if summary["cost_usd"] > t["cost_usd_max"]:
        out.append(f"cost ${summary['cost_usd']:.2f} is over ${t['cost_usd_max']:.2f} a run")
    if baseline:
        # The baseline holds blind numbers, so compare the blind cases when there are any.
        current = summary.get("blind") or summary
        for key in ("precision", "recall"):
            if current[key] < baseline[key] - t["baseline_drop_max"]:
                out.append(
                    f"blind {key} {current[key]:.0%} fell more than {t['baseline_drop_max']:.0%} below the "
                    f"baseline {baseline[key]:.0%}"
                )
    return out + stale


def markdown(result: dict) -> str:
    s, run = result["summary"], result["run"]
    lines = [
        f"# Extraction eval: {result['mode']}",
        "",
        (
            f"Skill `{run.get('skill_sha256', '?')[:12]}` ({run.get('skill_ref', 'unknown ref')}); extractor: "
            f"{run.get('extractor', run.get('model'))}."
        ),
        "",
        "| Precision | Recall | Fields edited | Records to edit or drop | Tokens (in/out) | Cost |",
        "| --- | --- | --- | --- | --- | --- |",
        (
            f"| {s['precision']:.0%} | {s['recall']:.0%} | {s['field_edit_rate']:.0%} | {s['edit_or_drop_rate']:.0%} | "
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
                    f"{s['blind']['edit_or_drop_rate']:.0%} to edit or drop."
                ),
                "",
            ]
            if s.get("blind")
            else []
        ),
        "| Case | Blind | Produced | Expected | Matched | Edits | Extra | Missed | Problems |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for c in result["cases"]:
        edits = sorted({e for m in c["matched"] for e in m["edits"]})
        problems = (
            c["limits"] + c["broken_links"] + (c["check"] or []) + ([] if c["source_filed"] else ["source not filed"])
        )
        lines.append(
            f"| {c['id']} | {'yes' if c['blind'] else 'no'} | {c['produced']} | {c['expected']} | {len(c['matched'])} | "
            f"{', '.join(edits) or '-'} | {', '.join(c['extra']) or '-'} | {', '.join(c['missed']) or '-'} | "
            f"{'; '.join(problems) or '-'} |"
        )
    lines += ["", "**Result:** " + ("pass" if not result["failures"] else "fail")]
    lines += [f"- {f}" for f in result["failures"]]
    return "\n".join(lines) + "\n"


def run(args: argparse.Namespace) -> dict[str, Any]:
    config = yaml.safe_load((EVAL / "config.yaml").read_text())
    cases = grade.load_cases(EVAL / "cases.yaml", REPO)
    skill = REPO / config["skill"]
    if args.live:
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise SystemExit("live mode needs ANTHROPIC_API_KEY")
        model = latest_model(key) if args.model == "latest" else (args.model or config["model"])
        recorded = Path(tempfile.mkdtemp(prefix="extract-eval-"))
        meta = {"skill_sha256": sha256(skill), "model": model, "extractor": f"live: {model}", "blind": {}, "tokens": {}}
        for case in cases:
            meta["tokens"][case["id"]] = extract_live(config, case, model, key, recorded / case["id"])
            meta["blind"][case["id"]] = True
        (recorded / "run.json").write_text(json.dumps(meta, indent=2) + "\n")
        if args.record:
            shutil.rmtree(EVAL / "recorded", ignore_errors=True)
            shutil.copytree(recorded, EVAL / "recorded")
    else:
        recorded = EVAL / "recorded"
        meta = json.loads((recorded / "run.json").read_text())
    results = []
    tokens_in = tokens_out = 0
    estimated = False
    for case in cases:
        proposal = recorded / case["id"]
        result = grade.grade_case(case, case["root"], proposal)
        result["blind"] = bool(meta.get("blind", {}).get(case["id"]))
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
        stale.append(note) if args.require_fresh else print(f"warning: {note}", file=sys.stderr)
    if meta.get("model") != config["model"]:
        print(f"note: recorded with {meta.get('model')}; live runs use {config['model']}", file=sys.stderr)
    baseline_path = EVAL / "baseline.json"
    baseline = json.loads(baseline_path.read_text()) if baseline_path.is_file() else None
    run_meta = {k: v for k, v in meta.items() if k not in ("tokens", "blind")}
    failures = gates(summary, config, baseline, stale)
    return {
        "mode": "live" if args.live else "fixture",
        "run": run_meta,
        "summary": summary,
        "cases": results,
        "baseline": baseline,
        "failures": failures,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("--live", action="store_true", help="call the model (needs ANTHROPIC_API_KEY)")
    parser.add_argument("--model", help="model id for --live, or 'latest'; default: config.yaml's pin")
    parser.add_argument("--record", action="store_true", help="with --live, replace the recorded proposals")
    parser.add_argument("--require-fresh", action="store_true", help="fail when the recording predates SKILL.md")
    parser.add_argument("--out", type=Path, help="write result.json and summary.md here")
    args = parser.parse_args(argv)
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
