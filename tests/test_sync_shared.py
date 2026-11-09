"""scripts/sync_shared.py: the shared work-system layer is edited once and every target harness carries the same bytes."""

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import sync_shared  # noqa: E402


def copy_repo(tmp_path: Path) -> Path:
    for d in ("shared", "harnesses/suite-default", "harnesses/work-default"):
        shutil.copytree(ROOT / d, tmp_path / d)
    return tmp_path


def test_repository_is_in_sync():
    stale, problems = sync_shared.plan(ROOT)
    assert stale == [] and problems == []


def test_hand_edited_copy_is_caught(tmp_path):
    root = copy_repo(tmp_path)
    skill = root / "harnesses/work-default/skills/decision-ticket/SKILL.md"
    skill.write_text(skill.read_text() + "\nan edit made in the copy\n")
    stale, _ = sync_shared.plan(root)
    assert [dst for _, dst in stale] == [root / "harnesses/work-default/skills/decision-ticket"]


def test_unregistered_hook_is_a_problem(tmp_path):
    root = copy_repo(tmp_path)
    settings = root / "harnesses/suite-default/native/claude-code/settings.json"
    data = json.loads(settings.read_text())
    data["hooks"]["PreToolUse"] = []
    settings.write_text(json.dumps(data))
    _, problems = sync_shared.plan(root)
    assert any("does not register" in p for p in problems)


def test_hook_must_see_mcp_tools(tmp_path):
    root = copy_repo(tmp_path)
    settings = root / "harnesses/suite-default/native/claude-code/settings.json"
    data = json.loads(settings.read_text())
    data["hooks"]["PreToolUse"][0]["matcher"] = "Bash"
    settings.write_text(json.dumps(data))
    _, problems = sync_shared.plan(root)
    assert any("must match Bash and mcp__" in p for p in problems)
