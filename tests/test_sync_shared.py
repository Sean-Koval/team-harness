"""scripts/sync_shared.py: the shared work-system layer is edited once and every target harness carries the same bytes."""

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import sync_shared  # noqa: E402


def copy_repo(tmp_path: Path) -> Path:
    for d in ("shared", "orgs", "harnesses/suite-default", "harnesses/work-default"):
        shutil.copytree(ROOT / d, tmp_path / d)
    return tmp_path


def test_repository_is_in_sync():
    stale, problems = sync_shared.plan(ROOT)
    assert stale == [] and problems == []


def test_hand_edited_copy_is_caught(tmp_path):
    root = copy_repo(tmp_path)
    skill = root / "harnesses/work-default/skills/decision-ticket/SKILL.md"
    skill.write_text(skill.read_text(encoding="utf-8") + "\nan edit made in the copy\n", encoding="utf-8", newline="\n")
    stale, _ = sync_shared.plan(root)
    assert [dst for _, dst, _ in stale] == [root / "harnesses/work-default/skills/decision-ticket"]


def test_unregistered_hook_is_a_problem(tmp_path):
    root = copy_repo(tmp_path)
    settings = root / "harnesses/suite-default/native/claude-code/settings.json"
    data = json.loads(settings.read_text(encoding="utf-8"))
    data["hooks"]["PreToolUse"] = []
    settings.write_text(json.dumps(data), encoding="utf-8")
    _, problems = sync_shared.plan(root)
    assert any("does not register" in p for p in problems)


def test_hook_must_see_mcp_tools(tmp_path):
    root = copy_repo(tmp_path)
    settings = root / "harnesses/suite-default/native/claude-code/settings.json"
    data = json.loads(settings.read_text(encoding="utf-8"))
    data["hooks"]["PreToolUse"][0]["matcher"] = "Bash|PowerShell"
    settings.write_text(json.dumps(data), encoding="utf-8")
    _, problems = sync_shared.plan(root)
    assert any("must match Bash, PowerShell and mcp__" in p for p in problems)


def test_hook_must_see_powershell_calls(tmp_path):
    """On Windows without Git Bash, Claude Code's shell tool is PowerShell (KAN-482)."""
    root = copy_repo(tmp_path)
    settings = root / "harnesses/suite-default/native/claude-code/settings.json"
    data = json.loads(settings.read_text(encoding="utf-8"))
    data["hooks"]["PreToolUse"][0]["matcher"] = "Bash|mcp__.*"
    settings.write_text(json.dumps(data), encoding="utf-8")
    _, problems = sync_shared.plan(root)
    assert any("must match Bash, PowerShell and mcp__" in p for p in problems)


def test_unfilled_placeholder_is_a_problem(tmp_path):
    root = copy_repo(tmp_path)
    skill = root / "shared/work-system/skills/work-docs/SKILL.md"
    skill.write_text(skill.read_text(encoding="utf-8") + "\nAsk {{nobody_defined_this}}.\n", encoding="utf-8", newline="\n")
    _, problems = sync_shared.plan(root)
    assert any("nobody_defined_this" in p for p in problems)


def test_no_copy_keeps_a_placeholder():
    for h in ("suite-default", "work-default"):
        for p in (ROOT / "harnesses" / h).rglob("*"):
            if p.is_file() and p.suffix in (".md", ".py"):
                assert not sync_shared.PLACEHOLDER.search(p.read_text(encoding="utf-8")), p


def test_work_default_carries_no_personal_rules():
    """The hard wall: the company harness names no person, no personal label and no personal knowledge base."""
    for p in (ROOT / "harnesses/work-default").rglob("*"):
        if p.is_file():
            text = p.read_text(encoding="utf-8").lower()
            for word in ("sean", "needs-sean", "human-decision", "second brain", "seanmkoval", "kan-"):
                assert word not in text, f"{p.relative_to(ROOT)} mentions {word!r}"


def test_suite_default_decisions_carry_the_human_decision_label():
    """Sean's decisions view filters on `human-decision` (KAN-484): a Decision filed by the skill must carry it."""
    skill = (ROOT / "harnesses/suite-default/skills/decision-ticket/SKILL.md").read_text(encoding="utf-8")
    labels = next((line for line in skill.splitlines() if line.startswith("| Labels |")), "")
    assert labels, "the decision-ticket skill has no Labels row"
    for label in ("`decision`", "`human-decision`", "assign it to Sean"):
        assert label in labels, label


def test_merge_rules_differ_by_harness():
    suite = (ROOT / "harnesses/suite-default/skills/github-pr/SKILL.md").read_text(encoding="utf-8")
    work = (ROOT / "harnesses/work-default/skills/github-pr/SKILL.md").read_text(encoding="utf-8")
    assert "you may merge" in suite and "Merging: never." in work
    assert (ROOT / "harnesses/work-default/skills/release-approvals/SKILL.md").is_file()
    assert not (ROOT / "harnesses/suite-default/skills/release-approvals").exists()


def test_ticket_template_is_the_one_the_skill_ships():
    assert (ROOT / "templates/ticket.md").read_bytes() == \
        (ROOT / "shared/work-system/skills/jira-ticket/ticket-template.md").read_bytes()
