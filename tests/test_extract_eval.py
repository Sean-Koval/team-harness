"""The extraction eval (KAN-464): its grader on the eval's own cases, a broken extractor failing, and the recorded run.

The eval's own cases (08 to 12) live in evals/extract-records/cases/ and run everywhere. The recorded run over all
cases needs the skill's example cases from KAN-435 and is skipped while they are not on the branch.
"""

import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import extract_eval
import extract_grade as grade

EVAL = ROOT / "evals/extract-records"


def own_cases() -> dict:
    """The eval's own cases, readable without the included manifest."""
    import yaml

    data = yaml.safe_load((EVAL / "cases.yaml").read_text())
    return {c["id"]: {**c, "root": EVAL / "cases" / c["id"]} for c in data["cases"]}


def proposal(tmp_path: Path, case: dict, files: "dict[str, str | None] | None" = None, copy_expected=True) -> Path:
    """A proposal directory: the expected files from after/, plus or minus `files` (None content deletes)."""
    out = tmp_path / case["id"]
    if copy_expected:
        for rel in case["expect"]:
            (out / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(case["root"] / "after" / rel, out / rel)
    for rel, text in (files or {}).items():
        if text is None:
            (out / rel).unlink()
        else:
            (out / rel).parent.mkdir(parents=True, exist_ok=True)
            (out / rel).write_text(text)
    out.mkdir(parents=True, exist_ok=True)
    return out


def no_check(_tree: Path):
    return None


@pytest.mark.parametrize(
    "case_id",
    ["08-restated-rules", "09-restated-unrecorded", "10-long-decision-record", "11-messy-meeting", "12-chat-thread"],
)
def test_expected_records_grade_perfect(tmp_path, case_id):
    case = own_cases()[case_id]
    result = grade.grade_case(case, case["root"], proposal(tmp_path, case), check=no_check)
    summary = grade.summarize([result])
    assert (summary["precision"], summary["recall"], summary["edit_or_drop_rate"]) == (1.0, 1.0, 0.0)
    assert result["source_filed"] and not result["limits"] and not result["broken_links"]


def _convention(rule_id: str, title: str) -> str:
    return f"""---
id: {rule_id}
type: convention
scope: team
status: active
date: '2026-11-12'
owner: lead-example
sources: []
links:
- {{type: derived_from, target: records-in-git-decision}}
- {{type: implements, target: records-in-git-wiki-rendered}}
title: {title}
description: Restated rule
---
# {title}

> - {title}.
"""


def test_broken_extractor_fails_the_gates(tmp_path):
    """A skill that turns each restated rule into a convention and drops the owed action fails the eval."""
    case = own_cases()["08-restated-rules"]
    broken = {
        "team/actions/render-job-service-account.md": None,
        "team/conventions/never-edit-wiki.md": _convention("never-edit-wiki", "Never edit the wiki by hand"),
        "team/conventions/reviewed-pr-only.md": _convention(
            "reviewed-pr-only", "Records change only through a reviewed PR"
        ),
        "team/conventions/one-file-per-record.md": _convention("one-file-per-record", "One file per record"),
    }
    result = grade.grade_case(case, case["root"], proposal(tmp_path, case, broken), check=no_check)
    summary = grade.summarize([result])
    assert result["limits"] == ["other: produced 3, allowed 0..2"]
    assert result["missed"] == ["team/actions/render-job-service-account.md"]
    summary.update(cost_usd=0.0, blind=None)
    config = {"thresholds": {"recall_min": 0.8, "edit_or_drop_max": 0.25, "baseline_drop_max": 0.05, "cost_usd_max": 5}}
    failures = extract_eval.gates(summary, config, {"precision": 1.0, "recall": 1.0}, [])
    assert any("recall" in f for f in failures) and any("edit or deletion" in f for f in failures)
    assert any("limit failures" in f for f in failures)


def test_existing_records_count_only_when_changed(tmp_path):
    """Case 09's before/ holds records: re-proposing one unchanged is nothing; editing it is a produced record."""
    case = own_cases()["09-restated-unrecorded"]
    existing = "team/conventions/one-file-per-record.md"
    text = (case["root"] / "before" / existing).read_text()
    same = grade.grade_case(case, case["root"], proposal(tmp_path / "a", case, {existing: text}), check=no_check)
    assert same["produced"] == 2 and not same["limits"]
    edited = text.replace("links:\n", "links:\n- {type: derived_from, target: records-merge-thread}\n")
    changed = grade.grade_case(case, case["root"], proposal(tmp_path / "b", case, {existing: edited}), check=no_check)
    assert changed["produced"] == 3 and changed["extra"] == [existing]
    assert changed["limits"] == [f"{existing} must stay unchanged"]


def test_restated_rule_without_a_record_is_a_miss_when_dropped(tmp_path):
    """The KAN-435 rule 'restated rules produce nothing' loses case 09's convention; the grader reports the miss."""
    case = own_cases()["09-restated-unrecorded"]
    dropped = {"team/conventions/raw-sources-expire-30-days.md": None}
    result = grade.grade_case(case, case["root"], proposal(tmp_path, case, dropped), check=no_check)
    assert result["missed"] == ["team/conventions/raw-sources-expire-30-days.md"]
    assert grade.summarize([result])["recall"] == 0.5


def test_field_edits_and_broken_links_are_reported(tmp_path):
    case = own_cases()["08-restated-rules"]
    rel = "team/actions/render-job-service-account.md"
    text = (case["root"] / "after" / rel).read_text()
    bad = (
        text.replace("owner: unknown", "owner: lead-example")
        .replace("target: records-in-git-decision}", "target: no-such-record}")
        .replace("> - Prerequisite", "> - A paraphrase, not a quote")
    )
    result = grade.grade_case(case, case["root"], proposal(tmp_path, case, {rel: bad}), check=no_check)
    edits = next(m["edits"] for m in result["matched"] if m["produced"] == rel)
    assert edits == ["owner", "links", "quote"]
    assert result["broken_links"] == [f"{rel}: derived_from -> no-such-record does not resolve"]


def test_matching_is_by_type_and_similar_title(tmp_path):
    case = own_cases()["08-restated-rules"]
    rel = "team/decisions/records-in-git-wiki-rendered.md"
    text = (case["root"] / "after" / rel).read_text()
    renamed = {
        rel: None,
        "team/decisions/records-in-git.md": text.replace("id: records-in-git-wiki-rendered", "id: records-in-git"),
    }
    result = grade.grade_case(case, case["root"], proposal(tmp_path, case, renamed), check=no_check)
    assert len(result["matched"]) == 2 and not result["extra"]
    as_question = {rel: text.replace("type: decision", "type: question")}
    other = grade.grade_case(case, case["root"], proposal(tmp_path / "q", case, as_question), check=no_check)
    assert other["missed"] == [rel] and other["extra"] == [rel]


def test_recorded_run_meets_the_gates(tmp_path):
    if not (ROOT / "tests/fixtures/extract-records/cases.yaml").is_file():
        pytest.skip("the skill's example cases (KAN-435) are not on this branch")
    assert extract_eval.main(["--out", str(tmp_path)]) == 0
    result = json.loads((tmp_path / "result.json").read_text())
    assert result["summary"]["recall"] >= 0.8 and result["summary"]["edit_or_drop_rate"] < 0.25
    assert (tmp_path / "summary.md").read_text().startswith("# Extraction eval: fixture")


def test_live_mode_needs_a_key(monkeypatch):
    if not (ROOT / "tests/fixtures/extract-records/cases.yaml").is_file():
        pytest.skip("the skill's example cases (KAN-435) are not on this branch")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(SystemExit, match="ANTHROPIC_API_KEY"):
        extract_eval.main(["--live"])


def test_live_extractor_never_reads_after(tmp_path, monkeypatch):
    """The live extractor's prompt is built from before/ only; the expected records never reach it."""
    case = own_cases()["09-restated-unrecorded"]
    sent = {}

    class Reply:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return json.dumps(
                {
                    "content": [{"type": "text", "text": '<file path="team/x.md">\nhi\n</file>'}],
                    "usage": {"input_tokens": 3, "output_tokens": 2},
                }
            ).encode()

    def fake_urlopen(request, timeout):
        sent["body"] = request.data.decode()
        return Reply()

    monkeypatch.setattr(extract_eval.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(extract_eval, "render_skill", lambda config, scope_map: "SKILL")
    usage = extract_eval.extract_live({}, case, "m", "k", tmp_path)
    assert usage == {"input": 3, "output": 2, "estimated": False}
    assert (tmp_path / "team/x.md").read_text() == "hi\n"
    assert "raw-sources-expire-30-days" not in sent["body"] and "reviewer-merges-records-pr" not in sent["body"]
    assert "records-merge-thread" in sent["body"]
