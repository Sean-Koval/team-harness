"""KAN-481: two PRs that each add a feature and a changelog entry merge one after the other with no conflict."""

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import collect_changes  # noqa: E402

GIT = ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false",
       "-c", "init.defaultBranch=main"]


def git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run([*GIT, *args], cwd=repo, check=check, capture_output=True, text=True)


def write(repo: Path, rel: str, text: str) -> None:
    (repo / rel).parent.mkdir(parents=True, exist_ok=True)
    (repo / rel).write_text(text)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    git(tmp_path, "init", "-q")
    write(tmp_path, "CHANGELOG.md", (ROOT / "CHANGELOG.md").read_text())
    write(tmp_path, "changes/README.md", "fragments\n")
    write(tmp_path, "shared/work-system/skills/one/SKILL.md", "one\n")
    write(tmp_path, "shared/work-system/skills/two/SKILL.md", "two\n")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-qm", "base")
    return tmp_path


def branch(repo: Path, name: str, files: dict[str, str]) -> None:
    git(repo, "checkout", "-qb", name, "main")
    for rel, text in files.items():
        write(repo, rel, text)
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", name)
    git(repo, "checkout", "-q", "main")


def merge_both(repo: Path) -> list[int]:
    return [git(repo, "merge", "--no-ff", "-qm", f"merge {b}", b, check=False).returncode for b in ("a", "b")]


def test_two_prs_with_fragments_merge_cleanly_and_collect(repo):
    branch(repo, "a", {"shared/work-system/skills/one/SKILL.md": "one, better\n",
                       "changes/KAN-1.added.md": "- Skill one does more (KAN-1).\n"})
    branch(repo, "b", {"shared/work-system/skills/two/SKILL.md": "two, fixed\n",
                       "changes/KAN-2.fixed.md": "- Skill two stops failing (KAN-2).\n"})
    assert merge_both(repo) == [0, 0]
    assert collect_changes.problems(repo) == []
    assert collect_changes.main(["--root", str(repo), "--write"]) == 0
    text = (repo / "CHANGELOG.md").read_text()
    assert "### Added\n\n- Skill one does more (KAN-1).\n" in text
    assert "### Fixed\n\n- Skill two stops failing (KAN-2).\n" in text
    assert text.index("## Unreleased") < text.index("### Added") < text.index("### Fixed")
    assert [p.name for p in (repo / "changes").iterdir()] == ["README.md"]


def test_the_old_way_conflicts(repo):
    """Why the fragments: both PRs adding a line at the top of Unreleased is a conflict."""
    log = (repo / "CHANGELOG.md").read_text()
    branch(repo, "a", {"CHANGELOG.md": log + "\n- Skill one does more.\n"})
    branch(repo, "b", {"CHANGELOG.md": log + "\n- Skill two stops failing.\n"})
    assert merge_both(repo)[1] != 0


def test_fold_joins_an_existing_list():
    text = "# C\n\n## Unreleased\n\nIntro.\n\n### Added\n\n- old\n\n## v1\n"
    out = collect_changes.fold(text, {"Added": ["- new"], "Removed": ["- gone\n  wrapped"]})
    assert out == "# C\n\n## Unreleased\n\nIntro.\n\n### Added\n\n- new\n- old\n\n### Removed\n\n- gone\n  wrapped\n\n## v1\n"


def test_bad_fragments_are_named(tmp_path):
    write(tmp_path, "changes/KAN-1.feature.md", "- x\n")
    write(tmp_path, "changes/KAN-2.md", "prose, no bullet\n")
    write(tmp_path, "changes/KAN-3.md", "### Added\n- x\n")
    got = collect_changes.problems(tmp_path)
    assert {p.split(":")[0] for p in got} == {"changes/KAN-1.feature.md", "changes/KAN-2.md", "changes/KAN-3.md"}


def test_this_repository_fragments_are_valid():
    assert collect_changes.problems(ROOT) == []
