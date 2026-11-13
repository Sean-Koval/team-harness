#!/usr/bin/env python3
"""Deterministic grader for the extraction eval (KAN-464).

Grades what an extractor proposed for one case against the case's expected records. The extractor never runs here
and never sees after/: this module only reads a case's before/ and after/ trees and a directory holding the files the
extractor proposed (an overlay on before/).

A produced record is a proposed file, not of type source, whose bytes differ from before/ (new, or an existing
record edited). Expected records are the case's `expect` files that are not of type source. Records pair by id when
both sides edit the same existing record, otherwise by type plus fuzzy title or id similarity. Validity comes from
ai-dlc's `knowledge check` on before/ with the proposal laid over it; this module does not restate the schema.
"""

from __future__ import annotations

import difflib
import json
import re
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml

MATCH_MIN = 0.5
FIELDS = ("status", "scope", "owner", "date", "valid_to", "links", "quote")
TICKET = re.compile(r"^[A-Z][A-Z0-9]+-\d+$")
Check = Callable[[Path], "list[str] | None"]


def header(text: str) -> dict[str, Any]:
    if not text.startswith("---\n"):
        return {}
    try:
        data = yaml.safe_load(text.split("---\n", 2)[1])
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


def body(text: str) -> str:
    parts = text.split("---\n", 2)
    return parts[2] if text.startswith("---\n") and len(parts) == 3 else text


def files(root: Path) -> dict[str, bytes]:
    if not root.is_dir():
        return {}
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def records(tree: dict[str, bytes]) -> dict[str, dict[str, Any]]:
    """Markdown files with a typed header, by path: header, body and path."""
    out = {}
    for path, raw in tree.items():
        if path.endswith(".md"):
            text = raw.decode("utf-8", "replace")
            head = header(text)
            if head.get("type"):
                out[path] = {"path": path, "head": head, "body": body(text)}
    return out


def _norm(text: Any) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", str(text or "").lower()).split())


def similarity(a: dict[str, Any], b: dict[str, Any]) -> float:
    """Best of title similarity and id-slug similarity, both normalized; 0 across types."""
    if a["head"].get("type") != b["head"].get("type"):
        return 0.0
    ratio = lambda x, y: difflib.SequenceMatcher(None, _norm(x), _norm(y)).ratio()
    return max(ratio(a["head"].get("title"), b["head"].get("title")), ratio(a["head"].get("id"), b["head"].get("id")))


def pair(produced: dict[str, dict], expected: dict[str, dict]) -> list[tuple[str, str, float]]:
    """Pair produced and expected paths: same id first, then greedy by similarity at or above MATCH_MIN."""
    pairs: list[tuple[str, str, float]] = []
    left, right = dict(produced), dict(expected)
    by_id = {r["head"].get("id"): p for p, r in right.items()}
    for path, rec in sorted(produced.items()):
        hit = by_id.get(rec["head"].get("id"))
        if hit in right and right[hit]["head"].get("type") == rec["head"].get("type"):
            pairs.append((path, hit, 1.0))
            left.pop(path)
            right.pop(hit)
    scored = sorted(
        ((similarity(left[p], right[e]), p, e) for p in left for e in right), key=lambda t: (-t[0], t[1], t[2])
    )
    for score, p, e in scored:
        if score >= MATCH_MIN and p in left and e in right:
            pairs.append((p, e, round(score, 3)))
            left.pop(p)
            right.pop(e)
    return sorted(pairs)


def _links(rec: dict, rename: dict[str, str]) -> set[tuple[str, str]]:
    out = set()
    for link in rec["head"].get("links") or []:
        if isinstance(link, dict):
            target = str(link.get("target"))
            out.add((str(link.get("type")), rename.get(target, target)))
    return out


def _quotes(rec: dict) -> list[str]:
    return [line[1:].strip() for line in rec["body"].splitlines() if line.startswith(">") and line[1:].strip()]


def _quoted_from(rec: dict, source_text: str) -> bool:
    """Every quote line is verbatim from the Source (after whitespace folding); a record needs at least one."""
    quotes = _quotes(rec)
    folded = " ".join(source_text.split())
    return bool(quotes) and all(" ".join(q.split()) in folded for q in quotes)


def compare(got: dict, want: dict, rename: dict[str, str], source_text: str) -> list[str]:
    """Fields of `got` a reviewer would edit to reach `want`."""
    edits = []
    for field in ("status", "scope", "owner", "date", "valid_to"):
        if str(got["head"].get(field) or "") != str(want["head"].get(field) or ""):
            edits.append(field)
    if _links(got, {}) != _links(want, rename):
        edits.append("links")
    if _quotes(want) and not _quoted_from(got, source_text):
        edits.append("quote")
    return edits


def broken_links(produced: dict[str, dict], known: dict[str, dict]) -> list[str]:
    """Record-shaped link targets that resolve to no record; derived_from that names a non-source."""
    ids = {r["head"].get("id"): r for r in known.values()}
    out = []
    for path, rec in produced.items():
        for link in rec["head"].get("links") or []:
            target = str((link or {}).get("target", ""))
            external = "/" in target or ":" in target or TICKET.match(target)
            if not external and target not in ids:
                out.append(f"{path}: {link.get('type')} -> {target} does not resolve")
            elif link.get("type") == "derived_from" and ids.get(target, {}).get("head", {}).get("type") != "source":
                out.append(f"{path}: derived_from -> {target} is not a source record")
    return out


def knowledge_check(tree: Path) -> list[str] | None:
    """ai-dlc's knowledge check on a records tree: failure lines, or None when ai-dlc is not available."""
    try:
        from ai_dlc.documentation import knowledge_check as kc  # type: ignore[import-not-found]
    except ImportError:
        exe = shutil.which("ai-dlc")
        if not exe:
            return None
        run = subprocess.run([exe, "knowledge", "check", str(tree)], capture_output=True, text=True, check=False)
        lines = [ln for ln in run.stdout.splitlines() if ln and not ln.startswith("knowledge check:")]
        return lines if run.returncode else []
    return list(kc.failure_lines(kc.check_records(tree)))


def limits_broken(produced: dict[str, dict], limits: dict[str, Any]) -> list[str]:
    counts: dict[str, int] = {}
    for rec in produced.values():
        kind = rec["head"].get("type")
        counts[kind] = counts.get(kind, 0) + 1
        if kind != "decision":
            counts["other"] = counts.get("other", 0) + 1
    out = []
    for kind, bounds in limits.items():
        if kind == "unchanged":
            out += [f"{p} must stay unchanged" for p in bounds if p in produced]
            continue
        low, high = bounds
        if not low <= counts.get(kind, 0) <= high:
            out.append(f"{kind}: produced {counts.get(kind, 0)}, allowed {low}..{high}")
    return out


def grade_case(case: dict, root: Path, proposal: Path, check: Check | None = knowledge_check) -> dict[str, Any]:
    """Grade one case. `root` holds before/ and after/; `proposal` holds the files the extractor proposed."""
    before, after, proposed = files(root / "before"), files(root / "after"), files(proposal)
    changed = {p: b for p, b in proposed.items() if before.get(p) != b}
    produced = {p: r for p, r in records(changed).items() if r["head"].get("type") != "source"}
    expected = {p: r for p, r in records(after).items() if p in case["expect"] and r["head"].get("type") != "source"}
    source_text = (root / "before" / case["source"]).read_text()
    pairs = pair(produced, expected)
    rename = {expected[e]["head"].get("id"): produced[p]["head"].get("id") for p, e, _ in pairs}
    matched = []
    for p, e, score in pairs:
        edits = compare(produced[p], expected[e], rename, source_text)
        matched.append({"produced": p, "expected": e, "similarity": score, "edits": edits})
    filed = records(changed).get(case.get("filed_as", ""), {}).get("head", {})
    merged = {**records(before), **records(proposed)}
    validity = None
    if check is not None:
        with tempfile.TemporaryDirectory() as tmp:
            shutil.copytree(root / "before", tmp, dirs_exist_ok=True)
            shutil.copytree(proposal, tmp, dirs_exist_ok=True) if proposal.is_dir() else None
            validity = check(Path(tmp))
    return {
        "id": case["id"],
        "produced": len(produced),
        "expected": len(expected),
        "matched": matched,
        "extra": sorted(set(produced) - {m["produced"] for m in matched}),
        "missed": sorted(set(expected) - {m["expected"] for m in matched}),
        "source_filed": filed.get("type") == "source" and filed.get("status") == "processed",
        "broken_links": broken_links(produced, merged),
        "limits": limits_broken(produced, case.get("limits") or {}),
        "check": validity,
    }


def summarize(cases: list[dict[str, Any]]) -> dict[str, Any]:
    produced = sum(c["produced"] for c in cases)
    expected = sum(c["expected"] for c in cases)
    matched = [m for c in cases for m in c["matched"]]
    edited = sum(1 for m in matched if m["edits"])
    fields = len(matched) * len(FIELDS)
    check_ran = [c for c in cases if c["check"] is not None]
    return {
        "produced": produced,
        "expected": expected,
        "matched": len(matched),
        "precision": round(len(matched) / produced, 4) if produced else 0.0,
        "recall": round(len(matched) / expected, 4) if expected else 0.0,
        "field_edit_rate": round(sum(len(m["edits"]) for m in matched) / fields, 4) if fields else 0.0,
        "edit_or_drop_rate": round((produced - len(matched) + edited) / produced, 4) if produced else 0.0,
        "broken_links": sum(len(c["broken_links"]) for c in cases),
        "limit_failures": sum(len(c["limits"]) for c in cases),
        "unfiled_sources": sum(1 for c in cases if not c["source_filed"]),
        "check_failures": sum(len(c["check"]) for c in check_ran),
        "check_ran": f"{len(check_ran)}/{len(cases)}",
    }


def load_cases(manifest: Path, repo: Path) -> list[dict[str, Any]]:
    """The eval's cases with their roots: included manifests first, then the eval's own, with `limits` merged."""
    data = yaml.safe_load(manifest.read_text())
    out: list[dict[str, Any]] = []
    include = data.get("include")
    if include:
        inc = repo / include
        if not inc.is_file():
            raise FileNotFoundError(f"{include} is missing: the skill's example cases (KAN-435) are not on this branch")
        for case in yaml.safe_load(inc.read_text())["cases"]:
            out.append({**case, "root": inc.parent / case["id"]})
    for case in data.get("cases") or []:
        out.append({**case, "root": manifest.parent / "cases" / case["id"]})
    extra = data.get("limits") or {}
    for case in out:
        if case["id"] in extra:
            case["limits"] = {**extra[case["id"]], **(case.get("limits") or {})}
    return out


if __name__ == "__main__":  # pragma: no cover - convenience: grade one proposal directory
    import sys

    root, proposal, manifest = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
    case = next(c for c in load_cases(manifest, Path.cwd()) if c["id"] == root.name)
    print(json.dumps(grade_case(case, root, proposal), indent=2))
