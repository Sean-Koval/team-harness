"""KAN-481: two PRs that each add a feature and a changelog entry merge one after the other with no conflict."""

import subprocess
import sys
from pathlib import Path

import pytest
import yaml

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


def _run(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, *args], cwd=repo, capture_output=True, text=True)


def _build_and_commit(repo: Path, msg: str) -> None:
    r = _run(repo, "scripts/build_generated.py", "--note", msg)
    assert r.returncode == 0, r.stderr
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", msg, "--allow-empty")


def test_real_layout_source_only_prs_merge_cleanly_after_a_build(tmp_path):
    """The real files that used to conflict (locks, env files, channels.yaml, agent.yaml): PR A merges and main is
    rebuilt; PR B, branched before, still merges cleanly, and the rebuilt tree passes check_registry. A PR that
    commits its build output is refused by --guard."""
    pytest.importorskip("hangar")
    repo = tmp_path / "repo"
    subprocess.run(["git", "clone", "-q", "--no-local", str(ROOT), str(repo)], check=True, capture_output=True)
    git(repo, "checkout", "-qB", "main")
    _build_and_commit(repo, "base build")
    skills = "shared/work-system/skills"
    for name, skill, key in (("a", "whats-next", "KAN-1"), ("b", "plan-to-tickets", "KAN-2")):
        text = (repo / skills / skill / "SKILL.md").read_text()
        branch(repo, name, {f"{skills}/{skill}/SKILL.md": text + f"\nAlso {key}.\n",
                            f"changes/{key}.md": f"- {skill} says more ({key}).\n"})
    assert _run(repo, "scripts/build_generated.py", "--guard", "main").returncode == 0  # on main itself
    git(repo, "checkout", "-q", "a")
    assert _run(repo, "scripts/build_generated.py", "--guard", "main").returncode == 0
    git(repo, "checkout", "-q", "main")
    assert git(repo, "merge", "--no-ff", "-qm", "merge a", "a", check=False).returncode == 0
    _build_and_commit(repo, "KAN-1: whats-next says more")
    assert git(repo, "merge", "--no-ff", "-qm", "merge b", "b", check=False).returncode == 0
    before = git(repo, "rev-parse", "HEAD").stdout.strip()
    _build_and_commit(repo, "KAN-2: plan-to-tickets says more")
    r = _run(repo, "scripts/check_registry.py", ".", "--base", before)
    assert r.returncode == 0, r.stderr
    # the old way: a PR that commits the build's output is refused
    git(repo, "checkout", "-qb", "c", "main")
    write(repo, f"{skills}/whats-next/SKILL.md", (repo / skills / "whats-next" / "SKILL.md").read_text() + "\nC.\n")
    _build_and_commit(repo, "c with its build")
    r = _run(repo, "scripts/build_generated.py", "--guard", "main")
    assert r.returncode == 1 and "harness.lock: generated" in r.stderr and "candidate line" in r.stderr


def test_restore_puts_back_only_generated_files(tmp_path):
    pytest.importorskip("hangar")
    repo = tmp_path / "repo"
    subprocess.run(["git", "clone", "-q", "--no-local", str(ROOT), str(repo)], check=True, capture_output=True)
    _build_and_commit(repo, "base build")
    skill = repo / "shared/work-system/skills/whats-next/SKILL.md"
    skill.write_text(skill.read_text() + "\nMore.\n")
    own = repo / "harnesses/work-default/skills/change-set/SKILL.md"
    own.write_text(own.read_text() + "\nOwn edit.\n")
    assert _run(repo, "scripts/build_generated.py").returncode == 0
    assert _run(repo, "scripts/build_generated.py", "--restore").returncode == 0
    left = sorted(x[3:] for x in git(repo, "status", "--porcelain").stdout.splitlines())
    assert left == ["harnesses/work-default/skills/change-set/SKILL.md",
                    "shared/work-system/skills/whats-next/SKILL.md"]


def _clone(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    subprocess.run(["git", "clone", "-q", "--no-local", str(ROOT), str(repo)], check=True, capture_output=True)
    git(repo, "checkout", "-qB", "main")
    _build_and_commit(repo, "base build")
    return repo


def _tree(d: Path) -> dict[str, bytes]:
    return {str(p.relative_to(d)): p.read_bytes() for p in sorted(d.rglob("*")) if p.is_file()}


def test_build_moves_candidate_only_and_is_idempotent(tmp_path):
    """A one-line shared/ edit: candidate moves, the stable lines and every releases/ copy stay byte for byte (only
    promote.py changes them), and a second build changes nothing."""
    pytest.importorskip("hangar")
    repo = _clone(tmp_path)
    channels = repo / "channels.yaml"
    stable = [x for x in channels.read_text().splitlines() if x.strip().startswith("stable:")]
    candidate = [x for x in channels.read_text().splitlines() if x.strip().startswith("candidate:")]
    releases = {d.name: _tree(d / "releases") for d in (repo / "harnesses").iterdir() if (d / "releases").is_dir()}
    skill = repo / "shared/work-system/skills/whats-next/SKILL.md"
    skill.write_text(skill.read_text() + "\nOne more line.\n")
    _build_and_commit(repo, "KAN-1: one line")
    lines = channels.read_text().splitlines()
    assert [x for x in lines if x.strip().startswith("stable:")] == stable
    assert [x for x in lines if x.strip().startswith("candidate:")] != candidate
    assert {d.name: _tree(d / "releases") for d in (repo / "harnesses").iterdir()
            if (d / "releases").is_dir()} == releases
    r = _run(repo, "scripts/build_generated.py", "--note", "again")
    assert r.returncode == 0 and "candidate ->" not in r.stderr, r.stderr
    assert git(repo, "status", "--porcelain").stdout == ""


def test_a_hand_edited_copy_fails(tmp_path):
    """R2's case: a PR edits a rendered hook copy instead of shared/. --guard refuses it; --drift, run after the
    build, refuses it too, so a PR labelled generated-files (which skips --guard) can't carry one either."""
    pytest.importorskip("hangar")
    repo = _clone(tmp_path)
    hook = "harnesses/work-default/native/claude-code/hooks/guard_work_system.py"
    git(repo, "checkout", "-qb", "tampered")
    write(repo, hook, (repo / hook).read_text() + "\n# not from shared/\n")
    git(repo, "commit", "-qam", "tamper")
    r = _run(repo, "scripts/build_generated.py", "--guard", "main")
    assert r.returncode == 1 and f"{hook}: generated" in r.stderr
    assert _run(repo, "scripts/build_generated.py").returncode == 0
    r = _run(repo, "scripts/build_generated.py", "--drift", "main")
    assert r.returncode == 1 and f"{hook}: differs from what the build writes" in r.stderr
    # a PR that commits a current copy (built, not edited) passes --drift
    git(repo, "checkout", "-q", "--", ".")
    git(repo, "checkout", "-qb", "current", "main")
    skill = repo / "shared/work-system/skills/whats-next/SKILL.md"
    skill.write_text(skill.read_text() + "\nCurrent.\n")
    _build_and_commit(repo, "with its build")
    assert _run(repo, "scripts/build_generated.py").returncode == 0
    r = _run(repo, "scripts/build_generated.py", "--drift", "main")
    assert r.returncode == 0, r.stderr


def test_stable_env_changes_only_with_a_promotion(tmp_path):
    """ac72dd6: generated.yml built main from a depth-1 clone, where render_envs can't find the commit that added
    stable's release copy, so it rendered suite-default's stable environment with main's bindings: a dependency added
    after the release reached stable with no promotion. The build now refuses that, and still writes stable's
    environment after a promotion."""
    pytest.importorskip("hangar")
    full = _clone(tmp_path)
    env = "harnesses/suite-default/env.stable.yaml"
    b = full / "bindings/suite-default.yaml"
    data = yaml.safe_load(b.read_text())
    data.setdefault("dependencies", {}).setdefault("pip", []).append("example-tool==1.0")
    b.write_text(yaml.safe_dump(data, sort_keys=False))
    # and a file, so the lock moves past stable even when stable is the current lock (KAN-508)
    skill = full / "shared/work-system/skills/whats-next/SKILL.md"
    skill.write_text(skill.read_text() + "\nOne more line.\n")
    _build_and_commit(full, "KAN-1: a dependency")  # full history: stable keeps the bindings of its release
    stable = (full / env).read_text()
    assert "example-tool" not in stable
    shallow = tmp_path / "shallow"
    subprocess.run(["git", "clone", "-q", "--depth", "1", f"file://{full}", str(shallow)], check=True,
                   capture_output=True)
    r = _run(shallow, "scripts/build_generated.py", "--note", "shallow")
    assert r.returncode != 0 and f"{env}: the build would change stable's environment" in r.stderr, r.stderr
    assert (shallow / env).read_text() == stable
    # a promotion moves stable, and its environment with it
    r = _run(full, "scripts/promote.py", "harnesses/suite-default")
    assert r.returncode == 0, r.stderr
    _build_and_commit(full, "KAN-2: promote")
    assert "example-tool==1.0" in (full / env).read_text()


def test_guard_refuses_a_changelog_edit_but_not_its_creation(tmp_path):
    """A PR edits CHANGELOG.md only when it folds fragments (deletes them); adding the file is fine."""
    pytest.importorskip("hangar")
    repo = _clone(tmp_path)
    log = (repo / "CHANGELOG.md").read_text()
    branch(repo, "edit", {"CHANGELOG.md": log + "- straight in.\n"})
    git(repo, "checkout", "-q", "edit")
    r = _run(repo, "scripts/build_generated.py", "--guard", "main")
    assert r.returncode == 1 and "CHANGELOG.md: add changes/<KEY>.md instead" in r.stderr
    git(repo, "checkout", "-q", "main")
    git(repo, "rm", "-q", "CHANGELOG.md")
    git(repo, "commit", "-qm", "no changelog yet")
    branch(repo, "create", {"CHANGELOG.md": log})
    git(repo, "checkout", "-q", "create")
    assert _run(repo, "scripts/build_generated.py", "--guard", "main").returncode == 0


def test_generated_yml_runs_the_checks_with_check_yml_tools():
    """generated.yml re-runs PR CI's checks on main, so it installs the same tools at the same refs (KAN-481): a
    tool check.yml adds and generated.yml lacks turns every post-merge build red."""
    import yaml

    wf = ROOT / ".github/workflows"
    check = yaml.safe_load((wf / "check.yml").read_text(encoding="utf-8"))
    gen = yaml.safe_load((wf / "generated.yml").read_text(encoding="utf-8"))
    refs = {k: v for k, v in check["env"].items() if k.endswith("_REF")}
    assert refs, "check.yml pins no tool refs"
    for k, v in refs.items():
        assert gen["env"].get(k) == v, f"generated.yml's {k} differs from check.yml's"
    build = "\n".join(str(s.get("run", "")) for s in gen["jobs"]["build"]["steps"])
    for k in refs:
        assert "${" + k + "}" in build, f"generated.yml's build installs nothing at {k}"
    # a shallow clone renders a release copy's env with today's bindings, so stable would change without a promotion
    def depth(steps):
        return [s.get("with", {}).get("fetch-depth") for s in steps if str(s.get("uses", "")).startswith("actions/checkout")]
    assert depth(gen["jobs"]["build"]["steps"]) == depth(check["jobs"]["check"]["steps"]) == [0], "fetch-depth differs"
    # a tool installed but left off PATH (the ai-dlc CLI's own venv) is as missing as one not installed
    check_steps = [s for job in check["jobs"].values() for s in job.get("steps", [])]
    for line in "\n".join(str(s.get("run", "")) for s in check_steps).splitlines():
        if "GITHUB_PATH" in line:
            assert line.strip() in build, f"generated.yml's build lacks check.yml's PATH line: {line.strip()}"
