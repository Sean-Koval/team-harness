#!/usr/bin/env python3
"""Deterministic grader for the extraction eval (KAN-464).

Grades what an extractor proposed for one case against the case's expected records. The extractor never runs here
and never sees after/: this module only reads a case's before/ and after/ trees and a directory holding the files the
extractor proposed (an overlay on before/).

A produced record is a proposed file, not of type source, whose bytes differ from before/ (new, or an existing
record edited). Expected records are the case's `expect` files that are not of type source. Records pair by id when
both sides edit the same existing record, otherwise by type plus fuzzy title or id similarity. Validity comes from
ai-dlc's `knowledge check` on before/ with the proposal laid over it; this module does not restate the schema.

Each edit is classified by severity (KAN-474): substantive when it makes the record wrong, cosmetic when it only
costs the reviewer wording. `classify_pr_edit` applies the same rules to one proposed and one merged record, for
`knowledge stats` on live records PRs.
"""

from __future__ import annotations

import difflib
import itertools
import json
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml

QUOTE_MIN = 0.6  # share of the shorter quote that must appear verbatim in the other
TITLE_MIN = 0.6  # below this title similarity, a reviewer rewrites the title
FIELDS = (
    "type", "title", "statement", "status", "scope", "boundary", "owner", "date", "valid_to", "links", "quote", "evidence",
)  # fmt: skip
# Severity of an edited field (KAN-474). Anything not cosmetic is substantive, so a new field fails safe.
# `check`: knowledge check refuses the record; `contradiction`: it claims another day, number or a negated verb;
# `drop`: the reviewer deletes it. Whether a description gives the why is `needs_human` (run.json), never graded here.
COSMETIC = frozenset({"title", "statement"})
SEVERITIES = ("substantive", "cosmetic", "needs_human")
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


SPEAKER = re.compile(r"^(\[[^\]]*\]\s*)?([\w.-]+:\s+)?([-*]|\d+\.)?\s*")
WEEKDAY = re.compile(r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday)s?\b")
NUMBER = re.compile(r"\d+(?:[.-]\d+)*")
NEGATION = {"not", "never", "no", "dont", "don", "without", "nobody", "none"}


def _quote_text(line: str) -> str:
    """A quote line without its timestamp, speaker or list marker; lower case, whitespace folded."""
    return " ".join(SPEAKER.sub("", _quote_core(line)).lower().split())


def quote_overlap(a: dict, b: dict) -> float:
    """Best share of the shorter quote line found verbatim in the other; 0 when either record has no quote."""
    best = 0.0
    for x in map(_quote_text, _quotes(a)):
        for y in map(_quote_text, _quotes(b)):
            short = min(len(x), len(y))
            if short:
                hit = difflib.SequenceMatcher(None, x, y, autojunk=False).find_longest_match(0, len(x), 0, len(y))
                best = max(best, hit.size / short)
    return best


def _ratio(x: Any, y: Any) -> float:
    a, b = _norm(x), _norm(y)
    words_a, words_b = set(a.split()), set(b.split())
    overlap = len(words_a & words_b) / min(len(words_a), len(words_b)) if words_a and words_b else 0.0
    return max(difflib.SequenceMatcher(None, a, b).ratio(), overlap)


def similarity(a: dict[str, Any], b: dict[str, Any]) -> float:
    """Title similarity of two records of one type; 0 across types. Only a tie-break: pairing rests on the quote."""
    if a["head"].get("type") != b["head"].get("type"):
        return 0.0
    return _ratio(a["head"].get("title"), b["head"].get("title"))


def contradiction(got: dict, want: dict) -> str | None:
    """A claim that says something else: another day, another number or a negated verb in the title.

    Titles hold the claim; descriptions explain it and may name other days or numbers in passing.
    """

    def text(rec: dict) -> str:
        return _norm(rec["head"].get("title"))

    days = [{d for d in WEEKDAY.findall(text(r))} for r in (got, want)]
    if all(days) and not days[0] & days[1]:
        return f"day: {sorted(days[0])} against {sorted(days[1])}"
    numbers = [set(NUMBER.findall(text(r))) for r in (got, want)]
    if all(numbers) and not numbers[0] & numbers[1]:
        return f"number: {sorted(numbers[0])} against {sorted(numbers[1])}"
    words = [_norm(r["head"].get("title")).split() for r in (got, want)]
    negated = [{w for n, w in itertools.pairwise(t) if n in NEGATION} for t in words]
    for mine, other, other_neg in ((0, 1, 1), (1, 0, 0)):
        flipped = {w for w in negated[mine] if w in words[other] and w not in negated[other_neg]}
        if flipped:
            return f"negated: {sorted(flipped)}"
    return None


def pair(produced: dict[str, dict], expected: dict[str, dict]) -> tuple[list[tuple[str, str, float]], list[dict]]:
    """Pair produced and expected paths.

    An edit to an existing record pairs by its id. A new record pairs on its verbatim quote, matched against the
    expected record's quote of the same type; title similarity only breaks ties. A pair whose content contradicts
    the expected record (another day, number or a negated verb) is not a match: it is wrong.
    """
    pairs: list[tuple[str, str, float]] = []
    wrong: list[dict] = []
    left, right = dict(produced), dict(expected)
    by_id = {r["head"].get("id"): p for p, r in right.items() if not _quotes(r)}
    for path, rec in sorted(produced.items()):
        hit = by_id.get(rec["head"].get("id"))
        if hit in right and right[hit]["head"].get("type") == rec["head"].get("type"):
            pairs.append((path, hit, 1.0))
            left.pop(path)
            right.pop(hit)
    scored = sorted(
        (
            (quote_overlap(left[p], right[e]), similarity(left[p], right[e]), p, e)
            for p in left
            for e in right
            if left[p]["head"].get("type") == right[e]["head"].get("type")
        ),
        key=lambda t: (-t[0], -t[1], t[2], t[3]),
    )
    for quote, _title, p, e in scored:
        if quote >= QUOTE_MIN and p in left and e in right:
            left.pop(p)
            right.pop(e)
            why = contradiction(produced[p], expected[e])
            if why:
                wrong.append({"produced": p, "expected": e, "why": why})
            else:
                pairs.append((p, e, round(quote, 3)))
    return sorted(pairs), wrong


def _links(rec: dict, rename: dict[str, str]) -> set[tuple[str, str]]:
    out = set()
    for link in rec["head"].get("links") or []:
        if isinstance(link, dict):
            target = str(link.get("target"))
            out.add((str(link.get("type")), rename.get(target, target)))
    return out


def _quotes(rec: dict) -> list[str]:
    return [line[1:].strip() for line in rec["body"].splitlines() if line.startswith(">") and line[1:].strip()]


ATTRIBUTION = re.compile(r"""^["\u201c](?P<text>.*)["\u201d]\s*(\([^()]*\))?\s*$""")


def _quote_core(line: str) -> str:
    """The quoted words alone: no surrounding quote marks, no trailing (timestamp, speaker), whitespace folded."""
    line = " ".join(line.split())
    hit = ATTRIBUTION.match(line)
    return hit.group("text").strip() if hit else line


def _quoted_from(rec: dict, source_text: str) -> bool:
    """Every quote line is verbatim from the Source (whitespace folded; quote marks and attribution set aside)."""
    quotes = _quotes(rec)
    folded = " ".join(source_text.split())
    return bool(quotes) and all(_quote_core(q) in folded for q in quotes)


def _evidence(rec: dict) -> list[dict]:
    """The `sources` entries of a record that carry evidence: a quote, its speaker and `at` or `permalink` (KAN-485)."""
    return [e for e in rec["head"].get("sources") or [] if isinstance(e, dict) and e.get("quote")]


SAID = re.compile(r"^\[?(?:\d{1,3}:)?\d{1,2}:\d{2}\]?\s+(?P<who>[^:]+?):\s")


def speakers(source_text: str, quote: str) -> set[str]:
    """Who said `quote` in the Source: the speaker of each `[time] name:` line holding it, case folded."""
    quote = " ".join(quote.split())
    out = set()
    for line in source_text.splitlines():
        hit = SAID.match(line)
        if hit and quote in " ".join(line.split()):
            out.add(hit["who"].strip().casefold())
    return out


def evidence_ok(got: dict, want: dict, source_text: str) -> bool:
    """Whether `got` keeps evidence for each Source that `want` quotes in `sources`.

    ai-dlc's knowledge check refuses a link to an expiring Source without a quote, speaker and `at` or `permalink`
    in the citing entry. The grader also asks what the check cannot: that the quote is the Source's own words and its
    speaker is who said them, from the Source's `[time] name:` line, or the expected speaker where it has none.
    """
    folded = " ".join(source_text.split())
    entries = [e for e in got["head"].get("sources") or [] if isinstance(e, dict)]

    def kept(entry: dict, wanted: dict) -> bool:
        quote = " ".join(str(entry.get("quote") or "").split())
        if not quote or quote not in folded or not (entry.get("at") or entry.get("permalink")):
            return False
        said_by = speakers(source_text, quote) or {str(wanted.get("speaker") or "").casefold()}
        return str(entry.get("speaker") or "").casefold() in said_by

    for wanted in _evidence(want):
        keys = {wanted.get("id"), wanted.get("resource")} - {None}
        if not any(keys & {e.get("id"), e.get("resource")} and kept(e, wanted) for e in entries):
            return False
    return True


def compare(got: dict, want: dict, rename: dict[str, str], source_text: str | None) -> list[str]:
    """Fields of `got` a reviewer would edit to reach `want`. Without `source_text` quote and evidence are not graded."""
    edits = []
    if str(got["head"].get("type") or "") != str(want["head"].get("type") or ""):
        edits.append("type")
    if _ratio(got["head"].get("title"), want["head"].get("title")) < TITLE_MIN:
        edits.append("title")
    if _bad_statement(got):
        edits.append("statement")
    for field in ("status", "scope", "boundary", "owner", "date", "valid_to"):
        if str(got["head"].get(field) or "") != str(want["head"].get(field) or ""):
            edits.append(field)
    if _links(got, {}) != _links(want, rename):
        edits.append("links")
    if source_text is not None and _quotes(want) and not _quoted_from(got, source_text):
        edits.append("quote")
    if source_text is not None and not evidence_ok(got, want, source_text):
        edits.append("evidence")
    return edits


def severity(field: str) -> str:
    """`cosmetic` for title or description wording; `substantive` for every other field."""
    return "cosmetic" if field in COSMETIC else "substantive"


def classify(edits: list[str]) -> dict[str, list[str]]:
    """Edited fields split by severity, in their original order."""
    out: dict[str, list[str]] = {"substantive": [], "cosmetic": []}
    for field in edits:
        out[severity(field)].append(field)
    return out


def record_severity(edits: list[str], needs_human: bool = False) -> str | None:
    """One record's class: substantive wins over cosmetic; needs_human only when nothing gradable was edited."""
    split = classify(edits)
    if split["substantive"]:
        return "substantive"
    if split["cosmetic"]:
        return "cosmetic"
    return "needs_human" if needs_human else None


def classify_pr_edit(proposed: str, merged: str, source_text: str | None = None) -> list[dict[str, str]]:
    """Edits a reviewer made to one record in a records PR: [{field, severity}], for `knowledge stats`.

    `proposed` is the file as the extractor opened it, `merged` as it merged; `source_text` grades the quote.
    A record the reviewer deleted is `classify_pr_edit(proposed, "")`: one substantive `drop`.
    """
    if not merged.strip():
        return [{"field": "drop", "severity": "substantive"}]
    got, want = ({"head": header(t), "body": body(t)} for t in (proposed, merged))
    return [{"field": f, "severity": severity(f)} for f in compare(got, want, {}, source_text)]


def _bad_statement(rec: dict) -> bool:
    """A description needs an edit when it is empty or copies the title.

    Whether it gives the why cannot be graded deterministically: a reviewer flags that in run.json's needs_human.
    """
    description = _norm(rec["head"].get("description"))
    return not description or description == _norm(rec["head"].get("title"))


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


def _ai_dlc() -> str | None:
    """The `ai-dlc` executable: on PATH, or beside the running interpreter (a virtualenv not on PATH)."""
    beside = Path(sys.executable).with_name("ai-dlc")
    return shutil.which("ai-dlc") or (str(beside) if beside.is_file() else None)


def knowledge_check(tree: Path) -> list[str] | None:
    """`ai-dlc knowledge check` on a records tree: failure lines, or None when ai-dlc is not installed.

    It calls the CLI, the knowledge role's contract, never an ai-dlc module path. It runs inside the tree on `.`, so
    each failure line starts with the record's path relative to the tree. Exit 0 is clean and 1 lists failures;
    anything else means the check did not run, and that is an error, not a pass.
    """
    exe = _ai_dlc()
    if not exe:
        return None
    run = subprocess.run([exe, "knowledge", "check", "."], cwd=tree, capture_output=True, text=True, check=False)
    if run.returncode not in (0, 1):
        raise RuntimeError(f"ai-dlc knowledge check exited {run.returncode}: {(run.stderr or run.stdout).strip()}")
    lines = [ln.removeprefix("./") for ln in run.stdout.splitlines() if ln and not ln.startswith("knowledge check:")]
    return lines if run.returncode else []


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
    # A proposed record whose header does not parse is still a record the reviewer must fix: produced, never matched.
    unreadable = sorted(
        p for p, b in changed.items() if p.endswith(".md") and b.startswith(b"---\n") and p not in records(changed)
    )
    expected = {p: r for p, r in records(after).items() if p in case["expect"] and r["head"].get("type") != "source"}
    source_text = (root / "before" / case["source"]).read_text()
    pairs, wrong = pair(produced, expected)
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
    for m in matched:  # a record knowledge check refuses needs an edit, whatever else matches
        if any(line.startswith(f"{m['produced']}:") for line in validity or []):
            m["edits"].append("check")
    wrong_by = {w["produced"]: w for w in wrong}
    missed = sorted(set(expected) - {m["expected"] for m in matched})
    record_edits = [{"record": m["produced"], "fields": list(m["edits"])} for m in matched if m["edits"]]
    for path in sorted(set(produced) - {m["produced"] for m in matched}):
        if path in wrong_by:
            fields = ["contradiction"]
        else:  # the right claim filed as another type is a type edit; anything else is deleted
            kind = produced[path]["head"].get("type")
            retyped = any(
                expected[x]["head"].get("type") != kind and quote_overlap(produced[path], expected[x]) >= QUOTE_MIN
                for x in missed
            )
            fields = ["type"] if retyped else ["drop"]
        record_edits.append({"record": path, "fields": fields})
    record_edits += [{"record": path, "fields": ["check"]} for path in unreadable]
    for item in record_edits:
        item["severity"] = record_severity(item["fields"])
    return {
        "id": case["id"],
        "produced": len(produced) + len(unreadable),
        "expected": len(expected),
        "matched": matched,
        "wrong": wrong,
        "extra": sorted((set(produced) - {m["produced"] for m in matched}) | set(unreadable)),
        "missed": missed,
        "edits": sorted(record_edits, key=lambda e: e["record"]),
        "source_filed": filed.get("type") == "source" and filed.get("status") == "processed",
        "broken_links": broken_links(produced, merged),
        "limits": limits_broken(produced, case.get("limits") or {}),
        "check": validity,
    }


def severity_counts(case: dict[str, Any]) -> dict[str, Any]:
    """One case's records by severity class, with `needs_human` records (run.json) that have no graded edit."""
    edited = {e["record"]: e for e in case.get("edits", [])}
    counts = {k: 0 for k in SEVERITIES}
    for e in edited.values():
        counts[e["severity"]] += 1
    counts["needs_human"] += sum(1 for r in case.get("needs_human", []) if r not in edited)
    fields: dict[str, int] = {}
    for e in edited.values():
        for f in e["fields"]:
            fields[f] = fields.get(f, 0) + 1
    produced = case["produced"]
    return {
        **counts,
        "substantive_rate": round(counts["substantive"] / produced, 4) if produced else 0.0,
        "cosmetic_rate": round(counts["cosmetic"] / produced, 4) if produced else 0.0,
        "fields": fields,
    }


def top_fields(fields: dict[str, int], n: int = 3) -> list[list[Any]]:
    return [[f, c] for f, c in sorted(fields.items(), key=lambda t: (-t[1], t[0]))[:n]]


def summarize(cases: list[dict[str, Any]]) -> dict[str, Any]:
    produced = sum(c["produced"] for c in cases)
    expected = sum(c["expected"] for c in cases)
    matched = [m for c in cases for m in c["matched"]]
    edited = sum(1 for m in matched if m["edits"])
    fields = len(matched) * len(FIELDS)
    check_ran = [c for c in cases if c["check"] is not None]
    per_case = [severity_counts(c) for c in cases]
    fields_total: dict[str, int] = {}
    for sc in per_case:
        for f, n in sc["fields"].items():
            fields_total[f] = fields_total.get(f, 0) + n
    substantive = sum(sc["substantive"] for sc in per_case)
    cosmetic = sum(sc["cosmetic"] for sc in per_case)
    return {
        "produced": produced,
        "expected": expected,
        "matched": len(matched),
        "precision": round(len(matched) / produced, 4) if produced else 0.0,
        "recall": round(len(matched) / expected, 4) if expected else 0.0,
        "field_edit_rate": round(sum(len(m["edits"]) for m in matched) / fields, 4) if fields else 0.0,
        "edit_or_drop_rate": round((produced - len(matched) + edited) / produced, 4) if produced else 0.0,
        "substantive": substantive,
        "cosmetic": cosmetic,
        "needs_human": sum(sc["needs_human"] for sc in per_case),
        "substantive_rate": round(substantive / produced, 4) if produced else 0.0,
        "cosmetic_rate": round(cosmetic / produced, 4) if produced else 0.0,
        "top_fields": top_fields(fields_total),
        "substantive_edits": [
            {"case": c["id"], "record": e["record"], "fields": classify(e["fields"])["substantive"]}
            for c in cases
            for e in c.get("edits", [])
            if e["severity"] == "substantive"
        ],
        "wrong": sum(len(c["wrong"]) for c in cases),
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
