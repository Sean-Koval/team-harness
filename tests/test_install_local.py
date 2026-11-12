"""scripts/install_local.py: a harness on a laptop, in user and project scope, pinned and never clobbering."""

import json
import shutil
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import install_local as il  # noqa: E402

WORK = ROOT / "harnesses/work-default"
SUITE = ROOT / "harnesses/suite-default"


def run(*args) -> int:
    return il.main([str(a) for a in args])


def user(harness, home, *mode) -> int:
    return run(harness, "--scope", "user", "--home", home, *mode)


def project(harness, target, *mode) -> int:
    return run(harness, "--scope", "project", "--target", target, *mode)


def snapshot(d: Path) -> dict[str, bytes]:
    return {p.relative_to(d).as_posix(): p.read_bytes() for p in sorted(d.rglob("*")) if p.is_file()}


def manifest(base: Path) -> dict:
    return json.loads((base / il.MANIFEST).read_text())


def settings(base: Path) -> dict:
    return json.loads((base / "settings.json").read_text())


def copy_harness(tmp_path: Path, src: Path = SUITE) -> Path:
    """A harness directory laid out as in the repo (harnesses/<h>/, bindings/), free to edit."""
    dst = tmp_path / "repo/harnesses" / src.name
    shutil.copytree(src, dst)
    (tmp_path / "repo/bindings").mkdir()
    shutil.copy(ROOT / "bindings" / f"{src.name}.yaml", tmp_path / "repo/bindings")
    return dst


def repin(h: Path, **changes) -> None:
    """Re-pin a copied harness's lock after editing its files, as relock.py would (without hangar)."""
    lock_file = h / "harness.lock"
    lock = yaml.safe_load(lock_file.read_text())
    comps = []
    for c in lock["components"]:
        p = h / c["path"]
        if not p.exists():
            continue
        if c["id"].startswith("skill:"):
            c["digest"] = il.files_digest(il._read_dir(p))
        else:
            c["digest"] = il.sha(p.read_bytes())
        comps.append(c)
    lock["components"] = comps
    lock.update(changes)
    lock_file.write_text(yaml.safe_dump(lock, sort_keys=False))


# --- digests ----------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("name", ["team-default", "work-default", "suite-default"])
def test_digests_match_hangar(name):
    hl = pytest.importorskip("hangar.harness_lock")
    root = ROOT / "harnesses" / name
    lock = yaml.safe_load((root / "harness.lock").read_text())
    assert il.harness_digest(lock) == hl.harness_digest(lock)
    for c in lock["components"]:
        if c["id"].startswith("skill:") and c.get("path"):
            files = hl.read_dir(root / c["path"])
            assert il._read_dir(root / c["path"]) == files
            assert il.files_digest(files) == hl.files_digest(files) == c["digest"]


def test_digest_matches_a_channel():
    chans = yaml.safe_load((ROOT / "channels.yaml").read_text())
    for h in (WORK, SUITE):
        lock = yaml.safe_load((h / "harness.lock").read_text())
        assert il.harness_digest(lock) in chans[lock["name"]].values()


# --- install ----------------------------------------------------------------------------------------------------

def test_dry_run_is_the_default_and_writes_nothing(tmp_path, capsys):
    assert user(WORK, tmp_path) == 0
    assert not (tmp_path / ".claude").exists()
    assert "dry run: nothing written" in capsys.readouterr().out


@pytest.mark.parametrize("harness", [WORK, SUITE])
def test_fresh_user_install(tmp_path, harness):
    assert user(harness, tmp_path, "--apply") == 0
    base = tmp_path / ".claude"
    lock = yaml.safe_load((harness / "harness.lock").read_text())
    assert (base / "CLAUDE.md").read_bytes() == (harness / "CLAUDE.md").read_bytes()
    for c in lock["components"]:
        if c["id"].startswith("skill:"):
            for f in (harness / c["path"]).rglob("*"):
                if f.is_file():
                    rel = f.relative_to(harness / c["path"])
                    assert (base / "skills" / c["id"][6:] / rel).read_bytes() == f.read_bytes()
    for hook in (harness / "native/claude-code/hooks").iterdir():
        assert (base / "hooks" / hook.name).read_bytes() == hook.read_bytes()
    want = json.loads((harness / "native/claude-code/settings.json").read_text())
    got = settings(base)
    assert got["hooks"] == want["hooks"] and got["permissions"] == want["permissions"]
    m = manifest(base)
    assert (m["harness"], m["revision"], m["scope"]) == (lock["name"], lock["revision"], "user")
    assert m["harness_digest"] == il.harness_digest(lock)
    assert set(m["files"]) == set(snapshot(base)) - {il.MANIFEST, "settings.json"}
    assert all(m["files"][rel] == il.sha(data) for rel, data in snapshot(base).items() if rel in m["files"])


def test_rerun_is_idempotent(tmp_path, capsys):
    assert user(WORK, tmp_path, "--apply") == 0
    before = snapshot(tmp_path)
    mtimes = {p: p.stat().st_mtime_ns for p in tmp_path.rglob("*") if p.is_file()}
    capsys.readouterr()
    assert user(WORK, tmp_path, "--apply") == 0
    assert "up to date" in capsys.readouterr().out
    assert snapshot(tmp_path) == before
    assert {p: p.stat().st_mtime_ns for p in tmp_path.rglob("*") if p.is_file()} == mtimes
    assert user(WORK, tmp_path) == 0
    assert "up to date" in capsys.readouterr().out


def test_user_settings_are_preserved(tmp_path):
    base = tmp_path / ".claude"
    base.mkdir()
    mine = {
        "model": "my-model",
        "env": {"MY_FLAG": "1"},
        "permissions": {"allow": ["Bash(make test)"], "deny": ["Read(./secrets/**)", "Bash(gh pr merge:*)"]},
        "hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "my-hook"}]}],
                  "Stop": [{"hooks": [{"type": "command", "command": "notify"}]}]},
    }
    (base / "settings.json").write_text(json.dumps(mine))
    assert user(WORK, tmp_path, "--apply") == 0
    s = settings(base)
    assert s["model"] == "my-model" and s["env"] == {"MY_FLAG": "1"}
    assert s["permissions"]["allow"] == ["Bash(make test)"]
    assert s["permissions"]["deny"][:2] == ["Read(./secrets/**)", "Bash(gh pr merge:*)"]
    assert s["permissions"]["deny"].count("Bash(gh pr merge:*)") == 1  # already the user's: not added again
    assert s["hooks"]["PreToolUse"][0]["hooks"][0]["command"] == "my-hook"
    assert s["hooks"]["Stop"] == mine["hooks"]["Stop"]
    assert len(s["hooks"]["PreToolUse"]) == 3
    recorded = [r["value"] for r in manifest(base)["settings"]["entries"]]
    assert "Bash(gh pr merge:*)" not in recorded
    assert user(WORK, tmp_path, "--uninstall") == 0
    assert settings(base) == mine
    assert sorted(p.name for p in base.iterdir()) == ["settings.json"]


def test_settings_created_by_the_install_go_with_it(tmp_path):
    assert user(SUITE, tmp_path, "--apply") == 0
    assert user(SUITE, tmp_path, "--uninstall") == 0
    assert not (tmp_path / ".claude").exists() or not any((tmp_path / ".claude").iterdir())


def test_conflict_is_refused_and_nothing_is_written(tmp_path, capsys):
    mine = tmp_path / ".claude/skills/github-pr/SKILL.md"
    mine.parent.mkdir(parents=True)
    mine.write_text("my own github-pr skill\n")
    before = snapshot(tmp_path)
    assert user(WORK, tmp_path, "--apply") == 1
    err = capsys.readouterr().err
    assert "skills/github-pr/SKILL.md: exists and was not installed by this script" in err
    assert snapshot(tmp_path) == before


def test_same_bytes_are_adopted(tmp_path, capsys):
    hook = tmp_path / ".claude/hooks/guard_work_system.py"
    hook.parent.mkdir(parents=True)
    shutil.copy(SUITE / "native/claude-code/hooks/guard_work_system.py", hook)
    assert user(SUITE, tmp_path, "--apply") == 0
    assert "adopt   hooks/guard_work_system.py" in capsys.readouterr().out
    assert "hooks/guard_work_system.py" in manifest(tmp_path / ".claude")["files"]


def test_own_guide_is_kept_and_the_harness_guide_goes_beside_it(tmp_path, capsys):
    guide = tmp_path / ".claude/CLAUDE.md"
    guide.parent.mkdir(parents=True)
    guide.write_text("# my own instructions\n")
    assert user(WORK, tmp_path, "--apply") == 0
    out = capsys.readouterr().out
    assert guide.read_text() == "# my own instructions\n"
    beside = tmp_path / ".claude/team-harness/work-default.md"
    assert beside.read_bytes() == (WORK / "CLAUDE.md").read_bytes()
    assert "@team-harness/work-default.md" in out
    guide.write_text("# my own instructions\n@team-harness/work-default.md\n")
    assert user(WORK, tmp_path, "--apply") == 0
    assert "Add this line" not in capsys.readouterr().out
    assert manifest(tmp_path / ".claude")["guide"] == "team-harness/work-default.md"
    assert "CLAUDE.md" not in manifest(tmp_path / ".claude")["files"]


def test_one_harness_per_scope(tmp_path, capsys):
    assert user(WORK, tmp_path, "--apply") == 0
    assert user(SUITE, tmp_path, "--apply") == 2
    assert "has work-default installed" in capsys.readouterr().err
    assert user(SUITE, tmp_path, "--uninstall") == 2
    assert manifest(tmp_path / ".claude")["harness"] == "work-default"


def test_checkout_that_differs_from_its_lock_is_refused(tmp_path, capsys):
    h = copy_harness(tmp_path)
    (h / "skills/work-docs/SKILL.md").write_text("edited without relocking\n")
    assert user(h, tmp_path / "home", "--apply") == 2
    assert "skills/work-docs/ does not match skill:work-docs" in capsys.readouterr().err
    assert not (tmp_path / "home/.claude").exists()


def test_upgrade_removes_what_the_new_revision_dropped(tmp_path, capsys):
    h = copy_harness(tmp_path)
    home = tmp_path / "home"
    assert user(h, home, "--apply") == 0
    shutil.rmtree(h / "skills/work-docs")
    sfile = h / "native/claude-code/settings.json"
    s = json.loads(sfile.read_text())
    s["permissions"]["deny"].remove("Read(~/.git-credentials)")
    sfile.write_text(json.dumps(s, indent=2))
    repin(h, revision=3)
    capsys.readouterr()
    assert user(h, home, "--check") == 1
    assert "newer harness revision: r3" in capsys.readouterr().out
    assert user(h, home, "--apply") == 0
    out = capsys.readouterr().out
    assert "remove  skills/work-docs/SKILL.md" in out and "- permissions.deny Read(~/.git-credentials)" in out
    base = home / ".claude"
    assert not (base / "skills/work-docs").exists()
    assert "Read(~/.git-credentials)" not in settings(base)["permissions"]["deny"]
    assert manifest(base)["revision"] == 3
    assert user(h, home, "--check") == 0


# --- check, uninstall -------------------------------------------------------------------------------------------

def test_check_detects_drift(tmp_path, capsys):
    assert user(WORK, tmp_path, "--check") == 1
    assert "not installed" in capsys.readouterr().out
    assert user(WORK, tmp_path, "--apply") == 0
    assert user(WORK, tmp_path, "--check") == 0
    base = tmp_path / ".claude"
    (base / "skills/github-pr/SKILL.md").write_text("edited\n")
    (base / "hooks/guard_work.py").unlink()
    s = settings(base)
    s["permissions"]["deny"].remove("Bash(gh pr merge:*)")
    (base / "settings.json").write_text(json.dumps(s))
    capsys.readouterr()
    assert user(WORK, tmp_path, "--check") == 1
    out = capsys.readouterr().out
    assert "edited: skills/github-pr/SKILL.md" in out
    assert "missing: hooks/guard_work.py" in out
    assert "no longer has permissions.deny Bash(gh pr merge:*)" in out
    # an edited file blocks the upgrade path too, rather than being overwritten
    assert user(WORK, tmp_path, "--apply") == 1
    assert (base / "skills/github-pr/SKILL.md").read_text() == "edited\n"


def test_check_reports_a_newer_revision(tmp_path, capsys):
    assert user(WORK, tmp_path, "--apply") == 0
    mfile = tmp_path / ".claude" / il.MANIFEST
    m = json.loads(mfile.read_text())
    m.update(revision=1, harness_digest="sha256:" + "0" * 64)
    mfile.write_text(json.dumps(m))
    capsys.readouterr()
    assert user(WORK, tmp_path, "--check") == 1
    # the revision the checkout's lock pins, so the test holds when the harness is bumped
    lock_rev = yaml.safe_load((WORK / "harness.lock").read_text())["revision"]
    assert f"newer harness revision: r{lock_rev}" in capsys.readouterr().out


def test_uninstall_leaves_edited_files(tmp_path, capsys):
    assert user(WORK, tmp_path, "--apply") == 0
    base = tmp_path / ".claude"
    (base / "skills/release-approvals/SKILL.md").write_text("my edits\n")
    capsys.readouterr()
    assert user(WORK, tmp_path, "--uninstall") == 0
    assert "left skills/release-approvals/SKILL.md" in capsys.readouterr().err
    assert snapshot(base) == {"skills/release-approvals/SKILL.md": b"my edits\n"}


# --- project scope ----------------------------------------------------------------------------------------------

def test_project_scope(tmp_path):
    target, home = tmp_path / "svc", tmp_path / "home"
    (target / "src").mkdir(parents=True)
    (target / "CLAUDE.md").write_text("# the project's own guide\n")
    assert project(WORK, target, "--home", home, "--apply") == 0
    base = target / ".claude"
    assert not home.exists()
    assert (target / "CLAUDE.md").read_text() == "# the project's own guide\n"
    assert (base / "CLAUDE.md").read_bytes() == (WORK / "CLAUDE.md").read_bytes()
    assert (base / "skills/change-set/SKILL.md").is_file() and (base / "hooks/guard_work.py").is_file()
    cmds = [hk["command"] for g in settings(base)["hooks"]["PreToolUse"] for hk in g["hooks"]]
    assert cmds == ['python3 "$CLAUDE_PROJECT_DIR"/.claude/hooks/guard_work.py',
                    'python3 "$CLAUDE_PROJECT_DIR"/.claude/hooks/guard_work_system.py']
    assert "$HOME" not in (base / "settings.json").read_text()
    assert manifest(base)["scope"] == "project"
    assert project(WORK, target, "--check") == 0
    assert project(WORK, target, "--uninstall") == 0
    assert snapshot(target) == {"CLAUDE.md": b"# the project's own guide\n"}


# --- printed, never run -----------------------------------------------------------------------------------------

def test_mcp_commands_use_placeholders_only(tmp_path, capsys):
    assert user(WORK, tmp_path) == 0
    out = capsys.readouterr().out
    assert ('claude mcp add --scope user --transport http jira https://mcp.atlassian.com/v1/mcp '
            '--header "Authorization: $JIRA_MCP_AUTHORIZATION"') in out
    assert project(SUITE, tmp_path / "p") == 0
    out = capsys.readouterr().out
    assert "--header 'Authorization: ${ATLASSIAN_MCP_AUTHORIZATION}'" in out
    assert "Bearer " not in out.replace("`Bearer <token>`", "")


def test_mcp_and_plugins_are_never_written(tmp_path):
    assert user(ROOT / "harnesses/team-default", tmp_path, "--apply") == 0
    base = tmp_path / ".claude"
    assert not (tmp_path / ".claude.json").exists() and not (base / "plugins").exists()
    assert "mcpServers" not in settings(base)
