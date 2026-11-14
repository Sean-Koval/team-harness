"""Skill intake (KAN-511): scripts/add_skill.py checks a team work skill and copies it into the shared layer.

The sample skill in tests/fixtures/add-skill/ passes; each bad variant is the sample with one line or field changed,
built here, so no secret-shaped string is committed. `test_every_shared_skill_passes_intake` is the CI check.
"""

import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import add_skill  # noqa: E402
import sync_shared  # noqa: E402

SAMPLE = ROOT / "tests" / "fixtures" / "add-skill" / "team-deploy-notes"


@pytest.fixture
def repo(tmp_path):
    """A copy of the parts of the repository intake reads and writes."""
    root = tmp_path / "repo"
    shutil.copytree(ROOT / "shared", root / "shared")
    shutil.copytree(ROOT / "orgs", root / "orgs")
    (root / "changes").mkdir()
    return root


@pytest.fixture
def skill(tmp_path):
    d = tmp_path / "in" / SAMPLE.name
    shutil.copytree(SAMPLE, d)
    return d


def _append(skill: Path, line: str) -> None:
    md = skill / "SKILL.md"
    md.write_text(md.read_text(encoding="utf-8") + line + "\n", encoding="utf-8")


def test_every_shared_skill_passes_intake():
    assert add_skill.check() == []


def test_the_tool_pattern_is_the_tool_name_tests():
    import test_skill_tool_names
    assert add_skill.ATLASSIAN_TOOL.pattern == test_skill_tool_names.ATLASSIAN_TOOL.pattern


def test_sample_is_added_registered_and_logged(repo, skill):
    (skill / "SKILL.md").write_bytes(b"\xef\xbb\xbf" + (skill / "SKILL.md").read_bytes().replace(b"\n", b"\r\n"))
    assert add_skill.add(skill, ["work-default"], "KAN-1", [], root=repo) == []
    dst = repo / "shared/work-system/skills/team-deploy-notes"
    md = (dst / "SKILL.md").read_bytes()
    assert b"\r" not in md and not md.startswith(b"\xef\xbb\xbf")
    assert (dst / "reference" / "format.md").is_file()
    assert sync_shared._skill_harnesses(dst / "SKILL.md") == ["work-default"]
    assert sync_shared._skill_name(dst / "SKILL.md") == "team-deploy-notes"
    frag = (repo / "changes" / "KAN-1.added.md").read_text(encoding="utf-8")
    assert frag.startswith("- work-default: + `team-deploy-notes` skill.")
    # the shared layer now ships it to work-default only
    targets = sync_shared.yaml.safe_load((repo / "shared/work-system/targets.yaml").read_text(encoding="utf-8"))
    common = sync_shared.shared_skills(repo / "shared/work-system", targets, targets["harnesses"], [])
    assert "team-deploy-notes" in common["work-default"] and "team-deploy-notes" not in common["suite-default"]
    # and the added skill still passes the CI check
    assert add_skill.check(root=repo) == []


def test_cli_adds_the_sample(repo, skill, monkeypatch, capsys):
    monkeypatch.setattr(add_skill, "ROOT", repo)
    assert add_skill.main([str(skill), "--harness", "work-default", "--key", "KAN-2"]) == 0
    assert "stable moves only by scripts/promote.py" in capsys.readouterr().out
    assert (repo / "changes/KAN-2.added.md").is_file()


BAD_LINES = {
    "vendor tool": ("Create it with `createJiraIssue`.", "vendor tool"),
    "server-qualified tool": ("Call mcp__atlassian__getJiraIssue first.", "vendor tool"),
    "github token": ("Use ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4 to push.", "GitHub token"),
    "credential value": ("password = " + "hunter2hunter2hunter2", "credential value"),
    "private key": ("-----BEGIN RSA " + "PRIVATE KEY-----", "private key"),
    "email": ("Ask jane.doe@" + "acme-corp.com.", "e-mail address"),
    "site": ("Pages live on acme-corp.atlassian.net.", "the host acme-corp.atlassian.net"),
    "profile person": ("Ask Sean before you post.", "profile's person or site"),
    "profile site": ("See the space on seanmkoval.atlassian.net.", "the host"),
}


@pytest.mark.parametrize("case", sorted(BAD_LINES))
def test_a_bad_line_is_refused_and_nothing_is_copied(repo, skill, case):
    line, expected = BAD_LINES[case]
    _append(skill, line)
    problems = add_skill.add(skill, ["work-default"], "KAN-3", [], root=repo)
    assert any(expected in p for p in problems), problems
    assert not (repo / "shared/work-system/skills/team-deploy-notes").exists()
    assert not (repo / "changes/KAN-3.added.md").exists()


def test_deny_list_word_is_refused(repo, skill, tmp_path, monkeypatch):
    _append(skill, "Built for the Initech billing team.")
    deny = tmp_path / "deny.txt"
    deny.write_text("# company and customer names\nInitech\n", encoding="utf-8")
    monkeypatch.setenv("TEAM_HARNESS_DENY", str(deny))
    problems = add_skill.add(skill, ["work-default"], "KAN-4", add_skill.deny_words(), root=repo)
    assert any("'Initech' is on your deny list" in p for p in problems), problems


def test_unknown_placeholder_is_refused(repo, skill):
    _append(skill, "Post it in {{team_room}}.")
    problems = add_skill.add(skill, ["work-default"], "KAN-5", [], root=repo)
    assert any("{{team_room}} is not a parameter work-default's profile fills" in p for p in problems), problems


def test_frontmatter_is_required(repo, skill):
    md = skill / "SKILL.md"
    text = md.read_text(encoding="utf-8")
    md.write_text(text.replace("name: team-deploy-notes", "name: deploy-notes")
                  .split("description:")[0] + "---\n", encoding="utf-8")
    problems = add_skill.add(skill, ["work-default"], "KAN-6", [], root=repo)
    assert any("frontmatter name must be 'team-deploy-notes'" in p for p in problems), problems
    assert any("needs a description" in p for p in problems), problems


def test_a_taken_name_is_refused(repo, tmp_path):
    d = tmp_path / "in" / "jira-ticket"
    shutil.copytree(SAMPLE, d)
    md = d / "SKILL.md"
    md.write_text(md.read_text(encoding="utf-8").replace("team-deploy-notes", "jira-ticket"), encoding="utf-8")
    assert any("is taken" in p for p in add_skill.add(d, ["work-default"], "KAN-7", [], root=repo))


def test_unknown_harness_and_bad_key_are_refused(repo, skill):
    assert any("does not list it" in p for p in add_skill.add(skill, ["nope"], "KAN-8", [], root=repo))
    assert any("ticket key" in p for p in add_skill.add(skill, ["work-default"], "kan 8", [], root=repo))


def test_placeholders_and_example_hosts_pass():
    files = {"SKILL.md": "See https://docs.example.com/x, {{kb_site}} and git@github.com:org/repo.git.\n"}
    assert add_skill.content_problems(files, {"Sean"}, []) == []
