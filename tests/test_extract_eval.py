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
    config = {"thresholds": {"recall_min": 0.8, "edit_or_drop_max": 0.25, "cost_usd_max": 5}}
    failures = extract_eval.gates(summary, config, [])
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


def test_matching_is_by_type_and_quote(tmp_path):
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
        extract_eval.main(["--live", "--runner", "api"])


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
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    usage = extract_eval.extract_api({}, case, "m", tmp_path)
    assert usage == {"input": 3, "output": 2, "estimated": False}
    assert (tmp_path / "team/x.md").read_text() == "hi\n"
    assert "raw-sources-expire-30-days" not in sent["body"] and "reviewer-merges-records-pr" not in sent["body"]
    assert "records-merge-thread" in sent["body"]


def test_same_title_with_another_quote_is_not_a_match(tmp_path):
    """Title only breaks ties: a record quoting another line of the Source does not pair, whatever its title."""
    case = own_cases()["08-restated-rules"]
    rel = "team/actions/render-job-service-account.md"
    text = (case["root"] / "after" / rel).read_text()
    other = text.replace(
        "> - Prerequisite: the render job needs its own service account before go-live.",
        "> - Agents propose records only as a draft PR that a person merges.",
    )
    result = grade.grade_case(case, case["root"], proposal(tmp_path, case, {rel: other}), check=no_check)
    assert result["missed"] == [rel] and result["extra"] == [rel]


def _meeting_case(tmp_path: Path, produced_title: str) -> tuple[dict, Path, Path]:
    """A one-decision case built in tmp_path: the expected record says Thursdays."""
    root = tmp_path / "case"
    source = "[00:02:10] lead-example: Decision one: we release on Thursdays from now on."
    record = """---
id: release-day
type: decision
scope: team
status: accepted
date: '2026-11-10'
owner: lead-example
sources: []
links: []
title: {title}
description: Moves releases off Tuesday
---
# {title}

> {quote}
"""
    for side in ("before", "after"):
        (root / side / "inbox").mkdir(parents=True)
        (root / side / "inbox/sync.md").write_text(f"---\nid: sync\ntype: source\nstatus: raw\n---\n{source}\n")
    (root / "after/team/decisions").mkdir(parents=True)
    (root / "after/team/decisions/release-day.md").write_text(record.format(title="Release on Thursdays", quote=source))
    out = tmp_path / "proposal/team/decisions"
    out.mkdir(parents=True)
    (out / "release-day.md").write_text(record.format(title=produced_title, quote=source))
    case = {"id": "tmp", "source": "inbox/sync.md", "expect": ["team/decisions/release-day.md"]}
    return case, root, tmp_path / "proposal"


@pytest.mark.parametrize(
    "title", ["Release on Fridays", "Do not release on Thursdays", "Release on Thursdays from release 2"]
)
def test_contradicting_claim_is_a_miss(tmp_path, title):
    """Same quote, but the claim says another day, a negated verb or another number: wrong, not an edit."""
    if title.endswith("2"):
        pytest.skip("the expected title holds no number, so a number alone cannot contradict it")
    case, root, out = _meeting_case(tmp_path, title)
    result = grade.grade_case(case, root, out, check=no_check)
    assert result["matched"] == [] and result["missed"] == ["team/decisions/release-day.md"]
    assert len(result["wrong"]) == 1
    assert grade.summarize([result])["recall"] == 0.0


def test_reworded_title_is_an_edit_not_a_miss(tmp_path):
    case, root, out = _meeting_case(tmp_path, "Weekly deploys move to a new weekday slot")
    result = grade.grade_case(case, root, out, check=no_check)
    assert [m["edits"] for m in result["matched"]] == [["title"]]


def _repo(tmp_path: Path, *, listed: bool, skill: bool) -> Path:
    repo = tmp_path / "repo"
    (repo / "evals/extract-records").mkdir(parents=True)
    shutil.copy(EVAL / "config.yaml", repo / "evals/extract-records/config.yaml")
    (repo / "shared/work-system").mkdir(parents=True)
    skills = ["github-pr"] + (["extract-records"] if listed else [])
    (repo / "shared/work-system/targets.yaml").write_text(json.dumps({"skills": skills, "harnesses": []}))
    if skill:
        (repo / "shared/work-system/skills/extract-records").mkdir(parents=True)
        (repo / "shared/work-system/skills/extract-records/SKILL.md").write_text("# skill\n")
    return repo


def test_preflight_fails_when_the_skill_is_registered_but_missing(tmp_path):
    verdict, reason = extract_eval.preflight(_repo(tmp_path, listed=True, skill=False))
    assert verdict == "fail" and "targets.yaml registers extract-records" in reason


def test_preflight_fails_when_a_harness_copy_exists_without_the_shared_skill(tmp_path):
    repo = _repo(tmp_path, listed=False, skill=False)
    (repo / "harnesses/suite-default/skills/extract-records").mkdir(parents=True)
    (repo / "harnesses/suite-default/skills/extract-records/SKILL.md").write_text("# copy\n")
    assert extract_eval.preflight(repo)[0] == "fail"


def test_preflight_skips_with_a_reason_before_the_skill_lands(tmp_path):
    verdict, reason = extract_eval.preflight(_repo(tmp_path, listed=False, skill=False))
    assert verdict == "skip" and "#20" in reason


def test_preflight_runs_when_the_skill_is_present(tmp_path):
    assert extract_eval.preflight(_repo(tmp_path, listed=True, skill=True))[0] == "run"


def test_preflight_cli_writes_the_skip_for_the_workflow(tmp_path, monkeypatch):
    out = tmp_path / "github_output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    monkeypatch.setattr(extract_eval, "preflight", lambda: ("skip", "not yet"))
    assert extract_eval.main(["--preflight"]) == 0
    assert out.read_text() == "run=false\nreason=not yet\n"
    monkeypatch.setattr(extract_eval, "preflight", lambda: ("fail", "missing"))
    assert extract_eval.main(["--preflight"]) == 1


def test_cli_runner_has_no_tools_and_sees_only_the_prompt(tmp_path, monkeypatch):
    """Runner claude-cli: headless, every tool off, in an empty directory; the prompt holds before/ only."""
    case = own_cases()["09-restated-unrecorded"]
    seen = {}

    def fake_run(cmd, input, capture_output, text, cwd, timeout, check):
        seen.update(cmd=cmd, prompt=input, files=sorted(p.name for p in Path(cwd).rglob("*")))
        result = '<file path="team/decisions/x.md">\nhi\n</file>'
        reply = {"type": "result", "is_error": False, "result": result,
                 "usage": {"input_tokens": 5, "cache_read_input_tokens": 7, "output_tokens": 2}}  # fmt: skip
        return extract_eval.subprocess.CompletedProcess(cmd, 0, json.dumps(reply), "")

    monkeypatch.setattr(extract_eval.subprocess, "run", fake_run)
    monkeypatch.setattr(extract_eval, "render_skill", lambda config, scope_map: "SKILL")
    usage = extract_eval.extract_cli({}, case, "claude-sonnet-5-5", tmp_path / "out")
    assert usage == {"input": 12, "output": 2, "estimated": False}
    assert (tmp_path / "out/team/decisions/x.md").read_text() == "hi\n"
    cmd = seen["cmd"]
    assert cmd[1:5] == ["-p", "--model", "claude-sonnet-5-5", "--output-format"]
    assert cmd[cmd.index("--tools") + 1] == "" and "--strict-mcp-config" in cmd
    assert seen["files"] == []
    assert "raw-sources-expire-30-days" not in seen["prompt"] and "records-merge-thread" in seen["prompt"]


def test_one_model_setting():
    import yaml

    config = yaml.safe_load((EVAL / "config.yaml").read_text())
    assert config["model"] == "claude-sonnet-5-5"
    assert "claude-sonnet-5-5" not in (ROOT / "scripts/extract_eval.py").read_text()


@pytest.mark.parametrize(("description", "edited"), [("", True), ("Release on Thursdays", True), ("Any why", False)])
def test_description_is_an_edit_only_when_empty_or_the_title(tmp_path, description, edited):
    case, root, out = _meeting_case(tmp_path, "Release on Thursdays")
    rel = out / "team/decisions/release-day.md"
    rel.write_text(rel.read_text().replace("description: Moves releases off Tuesday", f"description: '{description}'"))
    result = grade.grade_case(case, root, out, check=no_check)
    assert ("statement" in result["matched"][0]["edits"]) is edited


def _recorded(tmp_path: Path, monkeypatch, pending: list[str]) -> Path:
    """A recorded/ copy whose run.json lists `pending`, with that case's recording removed."""
    recorded = tmp_path / "recorded"
    shutil.copytree(EVAL / "recorded", recorded)
    meta = json.loads((recorded / "run.json").read_text())
    meta["pending"] = pending
    (recorded / "run.json").write_text(json.dumps(meta))
    shutil.rmtree(recorded / "08-restated-rules")
    eval_dir = tmp_path / "eval"
    shutil.copytree(EVAL, eval_dir, ignore=shutil.ignore_patterns("recorded"))
    shutil.copytree(recorded, eval_dir / "recorded")
    monkeypatch.setattr(extract_eval, "EVAL", eval_dir)
    return eval_dir


def test_pending_case_is_reported_not_graded(tmp_path, monkeypatch):
    if not (ROOT / "tests/fixtures/extract-records/cases.yaml").is_file():
        pytest.skip("the skill's example cases (KAN-435) are not on this branch")
    _recorded(
        tmp_path, monkeypatch, ["08-restated-rules", "10-long-decision-record", "11-messy-meeting", "12-chat-thread"]
    )
    assert extract_eval.main(["--out", str(tmp_path / "out")]) in (0, 1)
    result = json.loads((tmp_path / "out/result.json").read_text())
    assert "08-restated-rules" in result["pending"]
    assert "08-restated-rules" not in [c["id"] for c in result["cases"]]


def test_missing_recording_not_marked_pending_fails(tmp_path, monkeypatch):
    if not (ROOT / "tests/fixtures/extract-records/cases.yaml").is_file():
        pytest.skip("the skill's example cases (KAN-435) are not on this branch")
    _recorded(tmp_path, monkeypatch, ["10-long-decision-record", "11-messy-meeting", "12-chat-thread"])
    assert extract_eval.main([]) == 2
