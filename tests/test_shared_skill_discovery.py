"""A new shared skill ships to every harness with no edit to targets.yaml (KAN-433): sync_shared.py takes every
directory under shared/work-system/skills/, except one a harness names as its own extra."""

import shutil
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import sync_shared  # noqa: E402

TARGETS = yaml.safe_load((ROOT / "shared/work-system/targets.yaml").read_text())
HARNESSES = list(TARGETS["harnesses"])


def copy_repo(tmp_path: Path) -> Path:
    for d in ["shared", "orgs"] + [f"harnesses/{h}" for h in HARNESSES]:
        shutil.copytree(ROOT / d, tmp_path / d)
    return tmp_path


def add_skill(root: Path, name: str, frontmatter_name: str | None = None) -> None:
    d = root / "shared/work-system/skills" / name
    d.mkdir()
    (d / "SKILL.md").write_text(f"---\nname: {frontmatter_name or name}\ndescription: a test skill\n---\n\n# Test\n")


def test_every_listed_skill_is_a_shared_directory_and_the_list_is_complete():
    """The top-level list still records what ships today, and names nothing that isn't there."""
    problems: list[str] = []
    common = sync_shared.shared_skills(ROOT / "shared/work-system", TARGETS, TARGETS["harnesses"], problems)
    assert problems == []
    assert set(TARGETS["skills"]) <= set(common)


def test_a_new_skill_directory_ships_to_every_harness_without_a_targets_edit(tmp_path):
    root = copy_repo(tmp_path)
    before = (root / "shared/work-system/targets.yaml").read_bytes()
    add_skill(root, "brand-new-skill")
    stale, problems = sync_shared.plan(root)
    assert problems == [], problems
    sync_shared.write(stale, root)
    for h in HARNESSES:
        assert (root / "harnesses" / h / "skills/brand-new-skill/SKILL.md").is_file(), h
    assert (root / "shared/work-system/targets.yaml").read_bytes() == before
    stale, problems = sync_shared.plan(root)
    assert stale == [] and problems == []


def test_a_harness_only_skill_stays_in_that_harness(tmp_path):
    """release-approvals is work-default's own extra: suite-default never gets it."""
    root = copy_repo(tmp_path)
    stale, problems = sync_shared.plan(root)
    assert problems == [] and stale == []
    assert (root / "harnesses/work-default/skills/release-approvals").is_dir()
    assert not (root / "harnesses/suite-default/skills/release-approvals").exists()


def test_a_directory_without_skill_md_is_an_error_not_a_skill(tmp_path):
    root = copy_repo(tmp_path)
    (root / "shared/work-system/skills/half-made").mkdir()
    _, problems = sync_shared.plan(root)
    assert any("half-made: no SKILL.md" in p for p in problems), problems


def test_a_skill_whose_frontmatter_names_another_is_an_error(tmp_path):
    root = copy_repo(tmp_path)
    add_skill(root, "mislabelled", frontmatter_name="something-else")
    _, problems = sync_shared.plan(root)
    assert any("mislabelled/SKILL.md must have frontmatter name: mislabelled" in p for p in problems), problems


def test_the_list_may_not_name_a_missing_skill(tmp_path):
    root = copy_repo(tmp_path)
    t = root / "shared/work-system/targets.yaml"
    data = yaml.safe_load(t.read_text())
    data["skills"].append("no-such-skill")
    t.write_text(yaml.safe_dump(data, sort_keys=False))
    _, problems = sync_shared.plan(root)
    assert any("no-such-skill" in p for p in problems), problems
