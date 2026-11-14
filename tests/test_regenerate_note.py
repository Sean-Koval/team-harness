"""KAN-509: the post-merge regeneration notes each moved `candidate` with the merged change's changelog fragments,
never an empty "r17: ."."""

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from test_parallel_prs import _clone, _run, git, write  # noqa: E402


@pytest.fixture
def build_generated():
    pytest.importorskip("hangar")
    sys.path.insert(0, str(ROOT / "scripts"))
    import build_generated

    return build_generated


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    git(tmp_path, "init", "-q")
    write(tmp_path, "changes/README.md", "fragments\n")
    write(tmp_path, "changes/KAN-1.md", "- an older change, already on main.\n")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-qm", "base")
    return tmp_path


def _merge(repo: Path, files: dict[str, str]) -> str:
    """Commit `files` as a merged change; return the commit before it."""
    base = git(repo, "rev-parse", "HEAD").stdout.strip()
    for rel, text in files.items():
        write(repo, rel, text)
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "merge")
    return base


def test_regenerate_note_from_one_fragment(repo, build_generated):
    base = _merge(repo, {"changes/KAN-509.fixed.md": "- The regeneration notes candidate with the fragments.\n",
                         "shared/x.md": "x\n"})
    assert build_generated.fragment_note(repo, base) == "KAN-509: The regeneration notes candidate with the fragments"


def test_regenerate_note_from_several_fragments(repo, build_generated):
    base = _merge(repo, {
        "changes/KAN-7.added.md": "- First bullet,\n  wrapped onto a second line.\n- Second bullet with a # mark.\n",
        "changes/KAN-7.fixed.md": "- KAN-7: a fix that names its key.\n",
        "changes/KAN-8.md": "- Another ticket in the same merge.\n",
    })
    note = build_generated.fragment_note(repo, base)
    assert note == ("KAN-7: First bullet, wrapped onto a second line; Second bullet with a mark; KAN-7: a fix that "
                    "names its key. KAN-8: Another ticket in the same merge")
    assert "KAN-1" not in note  # only what this merge adds
    assert "\n" not in note and "#" not in note


def test_regenerate_note_is_cut_and_empty_without_fragments(repo, build_generated):
    base = _merge(repo, {"shared/x.md": "x\n"})
    assert build_generated.fragment_note(repo, base) == ""
    base = _merge(repo, {"changes/KAN-9.md": "- " + "word " * 200 + "\n"})
    note = build_generated.fragment_note(repo, base)
    assert len(note) == build_generated.CHANGE_LIMIT and note.endswith("…")


def test_regenerate_note_never_empty(build_generated):
    assert build_generated.one_line("  .  ") == ""
    assert build_generated.one_line("KAN-2: two\nlines. ") == "KAN-2: two lines"


def _candidate_comment(repo: Path) -> dict[str, str]:
    out, name = {}, None
    for line in (repo / "channels.yaml").read_text().splitlines():
        if line[:1].strip():
            name = line.split(":", 1)[0]
        elif line.strip().startswith("candidate:"):
            out[name] = line.split("#", 1)[1].strip() if "#" in line else ""
    return out


def test_regeneration_writes_the_fragment_on_channels_candidate(tmp_path):
    """End to end, as generated.yml runs it after a merge whose PR title didn't reach the merge commit."""
    pytest.importorskip("hangar")
    repo = _clone(tmp_path)
    before_build = _candidate_comment(repo)
    base = git(repo, "rev-parse", "HEAD").stdout.strip()
    skill = repo / "shared/work-system/skills/whats-next/SKILL.md"
    skill.write_text(skill.read_text() + "\nOne more line.\n")
    write(repo, "changes/KAN-9999.fixed.md", "- whats-next says one more line.\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "Merge pull request #1 from x/KAN-9999")
    r = _run(repo, "scripts/build_generated.py", "--since", base, "--note", "")
    assert r.returncode == 0, r.stderr
    after = _candidate_comment(repo)
    moved = [n for n in after if after[n] != before_build.get(n)]
    assert moved, r.stderr
    for n in moved:
        assert re.match(r"r\d+: KAN-9999: whats-next says one more line\. r\d+: ", after[n]), after[n]


def test_regeneration_falls_back_to_the_title_then_the_default(tmp_path):
    pytest.importorskip("hangar")
    repo = _clone(tmp_path)
    base = git(repo, "rev-parse", "HEAD").stdout.strip()
    skill = repo / "shared/work-system/skills/whats-next/SKILL.md"
    skill.write_text(skill.read_text() + "\nOne more line.\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "no fragment")
    r = _run(repo, "scripts/build_generated.py", "--since", base, "--note", " . ")
    assert r.returncode == 0, r.stderr
    notes = _candidate_comment(repo).values()
    assert not any(": ." in n.split(". r", 1)[0] for n in notes)
    assert any(": built from sources by scripts/build_generated.py. " in n for n in notes)
