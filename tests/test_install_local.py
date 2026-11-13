"""scripts/install_local.py: a harness on a laptop, in user and project scope, pinned and never clobbering."""

import base64
import codecs
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import install_local as il  # noqa: E402

WORK = ROOT / "harnesses/work-default"
SUITE = ROOT / "harnesses/suite-default"
TEAM = ROOT / "harnesses/team-default"


@pytest.fixture(autouse=True)
def fake_py(tmp_path_factory, monkeypatch):
    """`py` (the Windows launcher) on PATH off Windows, so the Windows hook commands run here too."""
    if os.name == "nt":
        return
    bin_dir = tmp_path_factory.mktemp("bin")
    launcher = bin_dir / "py"
    launcher.write_text(f'#!/bin/sh\n[ "$1" = "-3" ] && shift\nexec "{sys.executable}" "$@"\n')
    launcher.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")


def run(*args) -> int:
    return il.main([str(a) for a in args])


def channel_of(harness: Path) -> str:
    """The channel whose digest is this checkout's lock (candidate, on main), or `checkout` for a copied harness."""
    if harness.parent.parent != ROOT:
        return "checkout"
    chans = yaml.safe_load((ROOT / "channels.yaml").read_text())
    lock = yaml.safe_load((harness / "harness.lock").read_text())
    return next(c for c, d in chans[lock["name"]].items() if d == il.harness_digest(lock))


def _defaults(harness, mode) -> list:
    """Install the channel the checkout holds, and let a working tree with local edits through: the channel and
    dirty-checkout rules have their own tests below."""
    extra = [] if "--channel" in mode else ["--channel", channel_of(Path(harness))]
    return [*extra, *([] if "--allow-dirty" in mode or "--strict" in mode else ["--allow-dirty"])]


def user(harness, home, *mode) -> int:
    mode = tuple(m for m in mode if m != "--strict") + tuple(_defaults(harness, mode))
    return run(harness, "--scope", "user", "--home", home, *mode)


def project(harness, target, *mode) -> int:
    mode = tuple(m for m in mode if m != "--strict") + tuple(_defaults(harness, mode))
    return run(harness, "--scope", "project", "--target", target, *mode)


def snapshot(d: Path) -> dict[str, bytes]:
    return {p.relative_to(d).as_posix(): p.read_bytes() for p in sorted(d.rglob("*")) if p.is_file()}


def manifest(base: Path) -> dict:
    return json.loads((base / il.MANIFEST).read_text(encoding="utf-8"))


def settings(base: Path, name: str = "settings.json") -> dict:
    return json.loads((base / name).read_bytes().decode("utf-8-sig"))


def hook_command(hook: str, scope: str, base: Path, windows: bool = il.WINDOWS) -> str:
    """The command a harness's `python3 "$HOME/.claude/hooks/<hook>"` becomes, spelled out per OS and scope."""
    if not windows:
        return (f'python3 "$CLAUDE_PROJECT_DIR"/.claude/hooks/{hook}' if scope == "project"
                else f'python3 "$HOME/.claude/hooks/{hook}"')
    if scope == "project":
        return ('py -3 -c "import os,runpy;runpy.run_path(os.path.join(os.environ[\'CLAUDE_PROJECT_DIR\'],'
                f"'.claude','hooks','{hook}'),run_name='__main__')\"")
    return f'py -3 "{Path(os.path.abspath(base)).as_posix()}/hooks/{hook}"'


def expected_hooks(hooks: dict, scope: str, base: Path, windows: bool = il.WINDOWS) -> dict:
    out = json.loads(json.dumps(hooks))
    for groups in out.values():
        for g in groups:
            for hk in g["hooks"]:
                m = re.fullmatch(r'python3 "\$HOME/\.claude/hooks/(.+)"', hk["command"])
                if m:
                    hk["command"] = hook_command(m.group(1), scope, base, windows)
    return out


def symlink(link: Path, target: Path) -> None:
    try:
        link.symlink_to(target)
    except OSError as e:  # Windows without the symlink privilege
        pytest.skip(f"no symlinks here: {e}")


def copy_harness(tmp_path: Path, src: Path = SUITE) -> Path:
    """A harness directory laid out as in the repo (harnesses/<h>/, bindings/), free to edit."""
    dst = tmp_path / "repo/harnesses" / src.name
    shutil.copytree(src, dst)
    (tmp_path / "repo/bindings").mkdir()
    shutil.copy(ROOT / "bindings" / f"{src.name}.yaml", tmp_path / "repo/bindings")
    # the tests below count revisions from r2, whatever the harness is at in the checkout (not part of the digest)
    lock = dst / "harness.lock"
    lock.write_text(re.sub(r"(?m)^revision: \d+$", "revision: 2", lock.read_text()))
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
    assert (base / f"team-harness/{lock['name']}.md").read_bytes() == (harness / "CLAUDE.md").read_bytes()
    assert (base / "CLAUDE.md").read_text() == f"@team-harness/{lock['name']}.md\n"
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
    assert got["hooks"] == expected_hooks(want["hooks"], "user", base) and got["permissions"] == want["permissions"]
    m = manifest(base)
    assert (m["harness"], m["revision"], m["scope"]) == (lock["name"], lock["revision"], "user")
    assert m["harness_digest"] == il.harness_digest(lock)
    assert m["channel"] == channel_of(harness) and "path" in m["source"]
    assert set(m["files"]) == set(snapshot(base)) - {il.MANIFEST, "settings.json", "CLAUDE.md"}
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


def test_own_guide_gets_one_import_line_and_edits_never_block_an_upgrade(tmp_path, capsys):
    guide = tmp_path / ".claude/CLAUDE.md"
    guide.parent.mkdir(parents=True)
    guide.write_text("# my own instructions")  # no trailing newline
    assert user(WORK, tmp_path, "--apply") == 0
    assert "CLAUDE.md + @team-harness/work-default.md" in capsys.readouterr().out
    assert guide.read_text() == "# my own instructions\n@team-harness/work-default.md\n"
    beside = tmp_path / ".claude/team-harness/work-default.md"
    assert beside.read_bytes() == (WORK / "CLAUDE.md").read_bytes()
    m = manifest(tmp_path / ".claude")
    assert m["guide"] == "team-harness/work-default.md" and "CLAUDE.md" not in m["files"]
    # Claude Code (or you) edits CLAUDE.md: re-apply and check are still clean, and nothing is added twice
    guide.write_text(guide.read_text() + "- remember: tests first\n")
    assert user(WORK, tmp_path, "--apply") == 0
    assert user(WORK, tmp_path, "--check") == 0
    assert guide.read_text().count("@team-harness/work-default.md") == 1
    # the line removed by hand is drift, and re-apply puts it back
    guide.write_text("# my own instructions\n")
    capsys.readouterr()
    assert user(WORK, tmp_path, "--check") == 1
    assert "no longer has the line @team-harness/work-default.md" in capsys.readouterr().out
    assert user(WORK, tmp_path, "--apply") == 0 and user(WORK, tmp_path, "--check") == 0
    # uninstall takes the line out and leaves the rest of the file alone
    assert user(WORK, tmp_path, "--uninstall") == 0
    assert guide.read_text() == "# my own instructions\n"


def test_import_line_in_a_created_claude_md_goes_with_the_install(tmp_path):
    assert user(SUITE, tmp_path, "--apply") == 0
    assert (tmp_path / ".claude/CLAUDE.md").read_text() == "@team-harness/suite-default.md\n"
    assert user(SUITE, tmp_path, "--uninstall") == 0
    assert not (tmp_path / ".claude/CLAUDE.md").exists()


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


def test_check_with_a_wrong_path_says_so(tmp_path, capsys):
    assert user(tmp_path / "no-such-harness", tmp_path, "--check") == 2
    err = capsys.readouterr().err
    assert "is not a harness directory" in err and "Traceback" not in err
    assert user(tmp_path / "no-such-harness", tmp_path, "--apply") == 2
    assert user(tmp_path / "no-such-harness", tmp_path, "--uninstall") == 2


def test_os_error_is_a_message_not_a_traceback(tmp_path, capsys, monkeypatch):
    def boom(*_a, **_k):
        raise PermissionError(13, "Permission denied", str(tmp_path / ".claude/skills"))
    monkeypatch.setattr(il, "_write", boom)
    assert user(WORK, tmp_path, "--apply") == 2
    assert "Permission denied" in capsys.readouterr().err


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
    (base / "skills/release-approvals/SKILL.md").write_bytes(b"my edits\n")
    capsys.readouterr()
    assert user(WORK, tmp_path, "--uninstall") == 0
    assert "left skills/release-approvals/SKILL.md" in capsys.readouterr().err
    assert snapshot(base) == {"skills/release-approvals/SKILL.md": b"my edits\n"}


# --- project scope ----------------------------------------------------------------------------------------------

def test_project_scope(tmp_path):
    target, home = tmp_path / "svc", tmp_path / "home"
    (target / "src").mkdir(parents=True)
    (target / "CLAUDE.md").write_bytes(b"# the project's own guide\n")
    assert project(WORK, target, "--home", home, "--apply") == 0
    base = target / ".claude"
    assert not home.exists()
    assert (target / "CLAUDE.md").read_text() == "# the project's own guide\n"
    assert (base / "team-harness/work-default.md").read_bytes() == (WORK / "CLAUDE.md").read_bytes()
    assert (base / "CLAUDE.md").read_text() == "@team-harness/work-default.md\n"
    assert "path" not in manifest(base)["source"]  # a project's manifest may be committed: no machine path
    assert (base / "skills/change-set/SKILL.md").is_file() and (base / "hooks/guard_work.py").is_file()
    # hooks per machine, in the gitignored settings.local.json; the deny rules stay in the committed settings.json
    cmds = [hk["command"] for g in settings(base, "settings.local.json")["hooks"]["PreToolUse"] for hk in g["hooks"]]
    assert cmds == [hook_command("guard_work.py", "project", base),
                    hook_command("guard_work_system.py", "project", base)]
    assert "hooks" not in settings(base) and "Bash(gh pr merge:*)" in settings(base)["permissions"]["deny"]
    assert (target / ".gitignore").read_bytes() == b".claude/*.local.json\n"
    assert "$HOME" not in (base / "settings.local.json").read_text()
    assert manifest(base)["scope"] == "project"
    assert project(WORK, target, "--check") == 0
    assert project(WORK, target, "--uninstall") == 0
    assert snapshot(target) == {"CLAUDE.md": b"# the project's own guide\n"}


# --- printed, never run -----------------------------------------------------------------------------------------

def test_mcp_commands_use_placeholders_only(tmp_path, capsys):
    assert user(WORK, tmp_path) == 0
    out = capsys.readouterr().out
    var = "$env:JIRA_MCP_AUTHORIZATION" if il.WINDOWS else "$JIRA_MCP_AUTHORIZATION"
    assert ('claude mcp add --scope user --transport http jira https://mcp.atlassian.com/v1/mcp '
            f'--header "Authorization: {var}"') in out
    assert project(SUITE, tmp_path / "p") == 0
    out = capsys.readouterr().out
    assert "--header 'Authorization: ${ATLASSIAN_MCP_AUTHORIZATION}'" in out
    assert "Bearer " not in out.replace("`Bearer <token>`", "")


def test_mcp_and_plugins_are_never_written(tmp_path):
    assert user(ROOT / "harnesses/team-default", tmp_path, "--apply") == 0
    base = tmp_path / ".claude"
    assert not (tmp_path / ".claude.json").exists() and not (base / "plugins").exists()
    assert "mcpServers" not in settings(base)


# --- KAN-367: reversible on failure, channels, dirty checkouts, symlinks, edited hook groups ---------------------

MINE = {
    "model": "my-model",
    "enabledPlugins": {"mine@local": True},
    "permissions": {"deny": ["Read(./secrets/**)"]},
    "hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "my-hook"}]}]},
}


def test_failure_between_manifest_and_settings_stays_reversible(tmp_path, monkeypatch):
    base = tmp_path / ".claude"
    base.mkdir()
    (base / "settings.json").write_text(json.dumps(MINE))
    real = il._write

    def crash_after_settings(f, data, mode=None):
        real(f, data, mode)
        if f.name == "settings.json":
            raise KeyboardInterrupt  # killed after settings.json, before the final manifest

    monkeypatch.setattr(il, "_write", crash_after_settings)
    with pytest.raises(KeyboardInterrupt):
        user(WORK, tmp_path, "--apply")
    monkeypatch.setattr(il, "_write", real)
    entries = manifest(base)["settings"]["entries"]
    added = [r for r in entries if r["section"] == "permissions"]
    assert added and all(r["value"] != "Read(./secrets/**)" for r in added)  # the person's own rule is not claimed
    # a re-run finishes the install and takes none of the merged entries as the person's own
    assert user(WORK, tmp_path, "--apply") == 0
    assert manifest(base)["settings"]["entries"] == entries
    assert user(WORK, tmp_path, "--uninstall") == 0
    assert settings(base) == MINE


def test_failure_before_settings_leaves_them_untouched_and_uninstall_clean(tmp_path, monkeypatch):
    base = tmp_path / ".claude"
    base.mkdir()
    (base / "settings.json").write_text(json.dumps(MINE))
    real = il._write

    def crash_on_settings(f, data, mode=None):
        if f.name == "settings.json":
            raise KeyboardInterrupt
        real(f, data, mode)

    monkeypatch.setattr(il, "_write", crash_on_settings)
    with pytest.raises(KeyboardInterrupt):
        user(WORK, tmp_path, "--apply")
    monkeypatch.setattr(il, "_write", real)
    assert settings(base) == MINE
    assert user(WORK, tmp_path, "--uninstall") == 0
    assert settings(base) == MINE


def test_symlinked_settings_are_written_through(tmp_path):
    dotfiles = tmp_path / "dotfiles/claude-settings.json"
    dotfiles.parent.mkdir()
    dotfiles.write_text(json.dumps(MINE))
    base = tmp_path / ".claude"
    base.mkdir()
    symlink(base / "settings.json", dotfiles)
    assert user(WORK, tmp_path, "--apply") == 0
    assert (base / "settings.json").is_symlink()
    assert "Bash(gh pr merge:*)" in json.loads(dotfiles.read_text())["permissions"]["deny"]
    assert user(WORK, tmp_path, "--uninstall") == 0
    assert (base / "settings.json").is_symlink() and json.loads(dotfiles.read_text()) == MINE


def test_symlinked_claude_md_is_written_through(tmp_path):
    dotfiles = tmp_path / "dotfiles/CLAUDE.md"
    dotfiles.parent.mkdir()
    dotfiles.write_text("# mine\n")
    base = tmp_path / ".claude"
    base.mkdir()
    symlink(base / "CLAUDE.md", dotfiles)
    assert user(WORK, tmp_path, "--apply") == 0
    assert (base / "CLAUDE.md").is_symlink() and "@team-harness/work-default.md" in dotfiles.read_text()
    assert user(WORK, tmp_path, "--uninstall") == 0
    assert dotfiles.read_text() == "# mine\n"


def test_edited_harness_hook_group_is_not_added_twice(tmp_path, capsys):
    assert user(WORK, tmp_path, "--apply") == 0
    base = tmp_path / ".claude"
    s = settings(base)
    s["hooks"]["PreToolUse"][0]["matcher"] = "Bash"
    (base / "settings.json").write_text(json.dumps(s))
    capsys.readouterr()
    assert user(WORK, tmp_path, "--apply") == 0
    assert "it is yours now and is not added again" in capsys.readouterr().out
    cmd = s["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
    groups = [g for g in settings(base)["hooks"]["PreToolUse"] if g["hooks"][0]["command"] == cmd]
    assert len(groups) == 1 and groups[0]["matcher"] == "Bash"


def test_user_scope_says_where_a_work_harness_belongs(tmp_path, capsys):
    assert user(WORK, tmp_path) == 0
    assert "every Claude Code session on this machine" in capsys.readouterr().out
    assert project(WORK, tmp_path / "svc") == 0
    assert "every Claude Code session" not in capsys.readouterr().out


def _git(repo: Path, *args: str) -> str:
    import subprocess
    return subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.invalid",
                           "-c", "commit.gpgsign=false", *args], capture_output=True, text=True, check=True).stdout


def channel_repo(tmp_path: Path) -> tuple[Path, Path, dict]:
    """A git repo with suite-default at r2 (stable) and then r3 (candidate), as a team-harness checkout lays it out."""
    repo = tmp_path / "repo"
    h = copy_harness(tmp_path)
    _git(repo, "init", "-q")
    r2 = il.harness_digest(yaml.safe_load((h / "harness.lock").read_text()))
    (repo / "channels.yaml").write_text(yaml.safe_dump({"suite-default": {"stable": r2, "candidate": r2}}))
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "r2")
    skill = h / "skills/work-docs/SKILL.md"
    skill.write_text(skill.read_text() + "\nr3 adds this line.\n")
    repin(h, revision=3)
    r3 = il.harness_digest(yaml.safe_load((h / "harness.lock").read_text()))
    (repo / "channels.yaml").write_text(yaml.safe_dump({"suite-default": {"stable": r2, "candidate": r3}}))
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "r3")
    return repo, h, {"r2": r2, "r3": r3}


def test_installs_the_stable_channel_from_git_history(tmp_path, capsys):
    repo, h, d = channel_repo(tmp_path)
    home = tmp_path / "home"
    assert run(h, "--scope", "user", "--home", home, "--apply") == 0  # the default: stable, which is r2
    out = capsys.readouterr().out
    assert "suite-default@stable: suite-default r2" in out and "from git history" in out
    base = home / ".claude"
    m = manifest(base)
    assert (m["channel"], m["revision"], m["harness_digest"]) == ("stable", 2, d["r2"])
    assert "r3 adds this line." not in (base / "skills/work-docs/SKILL.md").read_text()
    assert run(h, "--scope", "user", "--home", home, "--check") == 0
    # promotion moves stable: --check reports it, --apply upgrades
    (repo / "channels.yaml").write_text(yaml.safe_dump({"suite-default": {"stable": d["r3"], "candidate": d["r3"]}}))
    _git(repo, "commit", "-qam", "promote r3")
    capsys.readouterr()
    assert run(h, "--scope", "user", "--home", home, "--check") == 1
    out = capsys.readouterr().out
    assert "newer harness revision: r3" in out and "on the stable channel" in out
    assert run(h, "--scope", "user", "--home", home, "--apply") == 0
    assert "r3 adds this line." in (base / "skills/work-docs/SKILL.md").read_text()
    assert manifest(base)["revision"] == 3


def test_candidate_installs_from_a_clean_checkout(tmp_path):
    _, h, d = channel_repo(tmp_path)
    home = tmp_path / "home"
    assert run(h, "--scope", "user", "--home", home, "--channel", "candidate", "--apply") == 0
    m = manifest(home / ".claude")
    assert (m["channel"], m["revision"], m["harness_digest"]) == ("candidate", 3, d["r3"])
    assert m["source"]["dirty"] is False


def test_dirty_checkout_is_refused_unless_allowed(tmp_path, capsys):
    _, h, _ = channel_repo(tmp_path)
    home = tmp_path / "home"
    (h / "NOTES.txt").write_text("a local note, not in the lock\n")
    assert run(h, "--scope", "user", "--home", home, "--channel", "candidate", "--apply") == 2
    assert "has uncommitted changes" in capsys.readouterr().err
    assert not (home / ".claude").exists()
    assert run(h, "--scope", "user", "--home", home, "--channel", "candidate", "--allow-dirty", "--apply") == 0


def test_checkout_outside_git_is_refused_unless_allowed(tmp_path, capsys):
    h = copy_harness(tmp_path)
    assert run(h, "--scope", "user", "--home", tmp_path / "home", "--channel", "checkout", "--apply") == 2
    assert "is not in a git checkout" in capsys.readouterr().err


def test_unknown_or_unreachable_channel_is_refused(tmp_path, capsys):
    repo, h, _ = channel_repo(tmp_path)
    home = tmp_path / "home"
    assert run(h, "--scope", "user", "--home", home, "--channel", "beta", "--apply") == 2
    assert "has no suite-default@beta" in capsys.readouterr().err
    (repo / "channels.yaml").write_text(yaml.safe_dump({"suite-default": {"stable": "sha256:" + "0" * 64}}))
    assert run(h, "--scope", "user", "--home", home, "--apply") == 2
    assert "neither this checkout's lock" in capsys.readouterr().err
    assert not (home / ".claude").exists()


# --- KAN-460: native Windows hook commands, settings.json back byte for byte ------------------------------------

@pytest.fixture(params=[False, True], ids=["posix", "windows"])
def windows(request, monkeypatch):
    """Run a test with the hook commands of each OS: the Windows forms are plain strings, checkable anywhere."""
    monkeypatch.setattr(il, "WINDOWS", request.param)
    if os.name == "nt" and not request.param:
        # sh commands can't start under cmd (the dry-run bug --apply now catches): Linux CI runs them
        monkeypatch.setattr(il, "probe_hooks", lambda *_a: [])
    return request.param


def hook_commands(base: Path) -> list[str]:
    """Every hook command installed: settings.json (user scope) and settings.local.json (project scope)."""
    return [hk["command"] for name in ("settings.json", "settings.local.json") if (base / name).is_file()
            for groups in (settings(base, name).get("hooks") or {}).values() for g in groups for hk in g["hooks"]]


def test_windows_user_scope_runs_hooks_with_py_and_a_quoted_profile_path(tmp_path, monkeypatch):
    monkeypatch.setattr(il, "WINDOWS", True)
    home = tmp_path / "Users" / "Jo Smith"  # a profile directory with a space
    assert user(WORK, home, "--apply") == 0
    base = home / ".claude"
    cmds = [c for c in hook_commands(base) if not c.startswith("echo ")]
    profile = Path(os.path.abspath(base)).as_posix()
    assert cmds == [f'py -3 "{profile}/hooks/guard_work.py"', f'py -3 "{profile}/hooks/guard_work_system.py"',
                    f'py -3 "{profile}/hooks/knowledge_session_end.py"']
    assert not any("$HOME" in c or "python3" in c for c in hook_commands(base))
    assert user(WORK, home, "--check") == 0
    assert user(WORK, home, "--uninstall") == 0
    assert not (base / "settings.json").exists()


@pytest.mark.parametrize("bad", ["50%off", "a$b", 'say"hi'])
def test_windows_profile_path_that_cannot_be_quoted_is_refused(tmp_path, monkeypatch, capsys, bad):
    monkeypatch.setattr(il, "WINDOWS", True)
    home = tmp_path / bad
    assert user(WORK, home, "--apply") == 2
    assert "can't be quoted for both Git Bash and PowerShell" in capsys.readouterr().err
    assert not (home / ".claude").exists()


def test_windows_project_scope_has_no_machine_path(tmp_path, monkeypatch):
    monkeypatch.setattr(il, "WINDOWS", True)
    target = tmp_path / "svc"
    assert project(WORK, target, "--apply") == 0
    base = target / ".claude"
    text = (base / "settings.json").read_text(encoding="utf-8") + (base / "settings.local.json").read_text("utf-8")
    assert str(tmp_path) not in text and tmp_path.as_posix() not in text and "$" not in text
    cmds = [c for c in hook_commands(base) if not c.startswith("echo ")]
    assert cmds == [hook_command("guard_work.py", "project", base, True),
                    hook_command("guard_work_system.py", "project", base, True),
                    hook_command("knowledge_session_end.py", "project", base, True)]


BLOCKED = {"tool_name": "Bash", "tool_input": {"command": "terraform apply -auto-approve"}}


def test_windows_project_hook_command_blocks_with_the_same_message(tmp_path, monkeypatch):
    """The `py -3 -c` line runs the installed hook as running the file does: same exit code, same bytes out."""
    monkeypatch.setattr(il, "WINDOWS", True)
    target = tmp_path / "svc"
    assert project(WORK, target, "--apply") == 0
    cmd = next(c for c in hook_commands(target / ".claude") if "guard_work.py" in c)
    prefix = 'py -3 -c "'
    assert cmd.startswith(prefix) and cmd.endswith('"')
    code = cmd[len(prefix):-1]
    event = json.dumps(BLOCKED).encode()
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(target)}
    via = subprocess.run([sys.executable, "-c", code], input=event, capture_output=True, env=env, cwd=tmp_path)
    direct = subprocess.run([sys.executable, str(target / ".claude/hooks/guard_work.py")], input=event,
                            capture_output=True, env=env, cwd=tmp_path)
    assert direct.returncode == 2 and direct.stderr
    assert (via.returncode, via.stdout, via.stderr) == (direct.returncode, direct.stdout, direct.stderr)


def test_windows_hook_that_is_not_python_is_refused(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(il, "WINDOWS", True)
    h = copy_harness(tmp_path)
    sfile = h / "native/claude-code/settings.json"
    sfile.write_text(sfile.read_text().replace('python3 \\"$HOME/.claude/hooks/guard_work_system.py\\"',
                                               'bash \\"$HOME/.claude/hooks/guard.sh\\"'))
    repin(h)
    assert user(h, tmp_path / "home", "--channel", "checkout", "--apply") == 2
    assert "has no native Windows form" in capsys.readouterr().err


# Written the way a person's editor might: a BOM, CRLF, tabs, its own key order, non-ASCII, no final newline.
OWN_SETTINGS = ('\ufeff{\r\n\t"model":"my-model",  "env": {"GREETING": "Grüße"},\r\n'
                '\t"permissions": {"deny": ["Read(./secrets/**)"]},\r\n'
                '\t"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "my-hook"}]}]}'
                '\r\n}').encode("utf-8")


OWN_LOCAL = b'{\r\n  "permissions": {"allow": ["Bash(make test)"]}\r\n}\r\n'
OWN_IGNORE = b"node_modules/\r\n*.log"  # CRLF, and no final newline


def test_uninstall_leaves_settings_byte_identical(tmp_path, windows):
    base = tmp_path / ".claude"
    base.mkdir()
    (base / "settings.json").write_bytes(OWN_SETTINGS)
    assert user(WORK, tmp_path, "--apply") == 0
    s = settings(base)
    assert s["env"] == {"GREETING": "Grüße"} and "Bash(gh pr merge:*)" in s["permissions"]["deny"]
    assert s["hooks"]["PreToolUse"][0]["hooks"][0]["command"] == "my-hook"
    assert user(WORK, tmp_path, "--apply") == 0  # a re-run keeps the original it recorded
    assert user(WORK, tmp_path, "--uninstall") == 0
    assert (base / "settings.json").read_bytes() == OWN_SETTINGS
    assert sorted(p.name for p in base.iterdir()) == ["settings.json"]


OWN_EMPTY = b'{\n  "model": "my-own",\n  "hooks": {},\n  "permissions": {"deny": []}\n}\n'
OWN_EMPTY_WINDOWS = codecs.BOM_UTF8 + OWN_EMPTY.replace(b"\n", b"\r\n")


@pytest.mark.parametrize("own", [OWN_EMPTY, OWN_EMPTY_WINDOWS], ids=["lf", "crlf-bom"])
def test_uninstall_restores_a_persons_own_empty_sections(tmp_path, windows, own):
    """KAN-433: an empty "hooks": {} or "deny": [] of the person's own is not lost on the way back."""
    base = tmp_path / ".claude"
    base.mkdir()
    (base / "settings.json").write_bytes(own)
    assert user(WORK, tmp_path, "--apply") == 0
    assert user(WORK, tmp_path, "--uninstall") == 0
    assert (base / "settings.json").read_bytes() == own


@pytest.mark.parametrize("own", [OWN_EMPTY, OWN_EMPTY_WINDOWS], ids=["lf", "crlf-bom"])
def test_uninstall_after_an_edit_keeps_own_empty_sections_and_line_endings(tmp_path, windows, own):
    """KAN-433: settings edited since the install are rewritten, but the person's empty sections stay, and so do
    the file's CRLF and byte-order mark."""
    base = tmp_path / ".claude"
    base.mkdir()
    (base / "settings.json").write_bytes(own)
    assert user(WORK, tmp_path, "--apply") == 0
    raw = (base / "settings.json").read_bytes()
    assert raw.startswith(codecs.BOM_UTF8) == own.startswith(codecs.BOM_UTF8)  # the install kept them too
    assert (b"\r\n" in raw) == (b"\r\n" in own)
    s = json.loads(raw.decode("utf-8-sig"))
    s["env"] = {"NEW": "1"}
    edited = (json.dumps(s, indent=2) + "\n").encode()  # an editor that keeps the file's own style
    if b"\r\n" in raw:
        edited = edited.replace(b"\n", b"\r\n")
    if raw.startswith(codecs.BOM_UTF8):
        edited = codecs.BOM_UTF8 + edited
    (base / "settings.json").write_bytes(edited)
    assert user(WORK, tmp_path, "--uninstall") == 0
    after = (base / "settings.json").read_bytes()
    assert json.loads(after.decode("utf-8-sig")) == {**json.loads(own.decode("utf-8-sig")), "env": {"NEW": "1"}}
    assert after.startswith(codecs.BOM_UTF8) == own.startswith(codecs.BOM_UTF8)
    if own is OWN_EMPTY_WINDOWS:
        assert b"\n" not in after.replace(b"\r\n", b"")
    else:
        assert b"\r" not in after



def test_an_upgrade_that_drops_every_entry_keeps_own_empty_sections(tmp_path, windows):
    """KAN-433: a revision that no longer ships any hook or deny rule leaves the person's own empty sections."""
    h = copy_harness(tmp_path)
    base = tmp_path / ".claude"
    base.mkdir()
    (base / "settings.json").write_bytes(OWN_EMPTY)
    assert user(h, tmp_path, "--apply") == 0
    sfile = h / "native/claude-code/settings.json"
    s = json.loads(sfile.read_text())
    s.pop("hooks", None)
    s.setdefault("permissions", {})["deny"] = []
    sfile.write_text(json.dumps(s, indent=2))
    repin(h, revision=3)
    assert user(h, tmp_path, "--apply") == 0
    assert json.loads((base / "settings.json").read_bytes()) == json.loads(OWN_EMPTY)

def test_project_uninstall_leaves_settings_byte_identical_across_an_upgrade(tmp_path, windows):
    h = copy_harness(tmp_path)
    target = tmp_path / "svc"
    base = target / ".claude"
    base.mkdir(parents=True)
    (base / "settings.json").write_bytes(OWN_SETTINGS)
    (base / "settings.local.json").write_bytes(OWN_LOCAL)
    (target / ".gitignore").write_bytes(OWN_IGNORE)
    assert project(h, target, "--apply") == 0
    assert (target / ".gitignore").read_bytes() == OWN_IGNORE + b"\r\n.claude/*.local.json\r\n"
    sfile = h / "native/claude-code/settings.json"
    s = json.loads(sfile.read_text())
    s["permissions"]["deny"].remove("Read(~/.git-credentials)")
    sfile.write_text(json.dumps(s, indent=2))
    repin(h, revision=3)
    assert project(h, target, "--apply") == 0
    assert manifest(base)["revision"] == 3
    assert project(h, target, "--uninstall") == 0
    assert (base / "settings.json").read_bytes() == OWN_SETTINGS
    assert (base / "settings.local.json").read_bytes() == OWN_LOCAL
    assert (target / ".gitignore").read_bytes() == OWN_IGNORE


def test_settings_changed_since_the_install_keep_the_change(tmp_path):
    base = tmp_path / ".claude"
    base.mkdir()
    (base / "settings.json").write_bytes(OWN_SETTINGS)
    assert user(WORK, tmp_path, "--apply") == 0
    s = settings(base)
    s["env"]["NEW"] = "1"
    (base / "settings.json").write_text(json.dumps(s), encoding="utf-8")
    assert user(WORK, tmp_path, "--uninstall") == 0
    want = json.loads(OWN_SETTINGS.decode("utf-8-sig"))
    want["env"]["NEW"] = "1"
    assert settings(base) == want  # not the old bytes: that would drop NEW


def test_manifest_from_before_kan_460_is_not_taken_as_the_original(tmp_path):
    """An install that recorded no original: uninstall falls back to removing its entries, as it always did."""
    base = tmp_path / ".claude"
    base.mkdir()
    (base / "settings.json").write_bytes(OWN_SETTINGS)
    assert user(WORK, tmp_path, "--apply") == 0
    mfile = base / il.MANIFEST
    m = manifest(base)
    assert base64.b64decode(m["settings"]["original"]) == OWN_SETTINGS
    del m["settings"]["original"]
    mfile.write_text(json.dumps(m, indent=2) + "\n", encoding="utf-8")
    assert user(WORK, tmp_path, "--apply") == 0
    assert "original" not in manifest(base)["settings"]  # the file now holds our entries: never recorded as yours
    assert user(WORK, tmp_path, "--uninstall") == 0
    assert settings(base) == json.loads(OWN_SETTINGS.decode("utf-8-sig"))


def test_crlf_claude_md_comes_back_byte_identical(tmp_path):
    guide = tmp_path / ".claude/CLAUDE.md"
    guide.parent.mkdir(parents=True)
    guide.write_bytes(b"# mine\r\n- one rule\r\n")
    assert user(WORK, tmp_path, "--apply") == 0
    assert guide.read_bytes() == b"# mine\r\n- one rule\r\n@team-harness/work-default.md\r\n"
    assert user(WORK, tmp_path, "--check") == 0
    assert user(WORK, tmp_path, "--uninstall") == 0
    assert guide.read_bytes() == b"# mine\r\n- one rule\r\n"


def test_check_runs_each_hook_once(tmp_path, monkeypatch, windows):
    """A clean --check has run every installed hook command, with this OS's commands, and each exited 0."""
    if os.name == "nt" and not windows:
        pytest.skip("the POSIX hook commands run on Linux CI")
    calls = []
    real = il.probe_hooks

    def spy(base, scope, entries):
        out = real(base, scope, entries)
        calls.append((scope, sorted({hk["command"] for r in entries if r["section"] == "hooks"
                                     for hk in r["value"]["hooks"]}), out))
        return out

    monkeypatch.setattr(il, "probe_hooks", spy)
    assert project(WORK, tmp_path / "svc", "--apply") == 0
    assert project(WORK, tmp_path / "svc", "--check") == 0
    assert len(calls) == 2 and all(out == [] for _, _, out in calls)
    cmds = calls[1][1]
    assert hook_command("guard_work.py", "project", tmp_path / "svc/.claude", windows) in cmds
    assert all(("py -3" in c) == windows for c in cmds if not c.startswith("echo "))


@pytest.mark.parametrize("scope", ["user", "project"])
def test_hook_that_does_not_start_fails_check_loudly(tmp_path, capsys, monkeypatch, scope):
    """No Python on PATH (no `py` launcher on Windows): Claude Code would skip the hook; --check says the guard is off."""
    where = tmp_path / ("home" if scope == "user" else "svc")
    install = user if scope == "user" else project
    assert install(WORK, where, "--apply") == 0
    empty = tmp_path / "empty-path"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    capsys.readouterr()
    assert install(WORK, where, "--check") == 1
    out = capsys.readouterr().out
    assert "hook did not run, so its guard is OFF: PreToolUse" in out
    assert "guard_work.py" in out and "guard_work_system.py" in out
    assert "drift: work-default" in out


def test_apply_fails_loudly_when_a_hook_does_not_start(tmp_path, capsys, monkeypatch):
    real = il.probe_hooks
    monkeypatch.setattr(il, "probe_hooks", lambda base, scope, entries: real(base, scope, [
        {**r, "value": {**r["value"], "hooks": [{"type": "command", "command": "no-such-interpreter-kan460 .claude/hooks/x.py"}]}}
        if r["section"] == "hooks" else r for r in entries]))
    assert project(WORK, tmp_path / "svc", "--apply") == 1
    err = capsys.readouterr().err
    assert "error: hook did not run, so its guard is OFF" in err and "no-such-interpreter-kan460" in err
    assert "Claude Code skips a hook that can't start" in err


@pytest.mark.skipif(os.name != "nt", reason="the native Windows shell")
def test_posix_hook_command_on_windows_is_caught(tmp_path, monkeypatch, capsys):
    """The teammate-guide dry run: main wrote `python3 "$CLAUDE_PROJECT_DIR"/...` on Windows, and Claude Code went on
    with the guard off. Without Git Bash, Claude Code runs hooks in PowerShell, where `$CLAUDE_PROJECT_DIR` is an empty
    PowerShell variable, so the command can't find its hook. Such a command now fails --apply and --check out loud."""
    monkeypatch.setattr(il, "WINDOWS", False)
    monkeypatch.setattr(il, "_git_bash", lambda: None)
    target = tmp_path / "svc"
    assert project(WORK, target, "--apply") == 1
    assert "hook did not run, so its guard is OFF" in capsys.readouterr().err
    assert project(WORK, target, "--check") == 1
    assert "hook did not run, so its guard is OFF" in capsys.readouterr().out


@pytest.mark.skipif(os.name != "nt", reason="the native Windows shells")
@pytest.mark.parametrize("shell", ["git-bash", "powershell"])
@pytest.mark.parametrize("scope", ["user", "project"])
def test_windows_hook_commands_run_in_both_hook_shells(tmp_path, monkeypatch, capsys, scope, shell):
    """The commands written for Windows pass the probe in Git Bash and, where Git Bash isn't installed, PowerShell:
    the two shells Claude Code runs shell-form hooks with on Windows."""
    if shell == "git-bash" and il._git_bash() is None:
        pytest.skip("no Git Bash on this machine")
    if shell == "powershell":
        monkeypatch.setattr(il, "_git_bash", lambda: None)
    monkeypatch.setattr(il, "WINDOWS", True)
    if scope == "project":
        assert project(WORK, tmp_path / "svc", "--apply") == 0, capsys.readouterr().err
        assert project(WORK, tmp_path / "svc", "--check") == 0, capsys.readouterr().out
    else:
        home = tmp_path / "home" / ".claude"
        assert user(WORK, home, "--apply") == 0, capsys.readouterr().err
        assert user(WORK, home, "--check") == 0, capsys.readouterr().out


def test_hook_shell_is_sh_off_windows(monkeypatch):
    if os.name == "nt":
        pytest.skip("Windows picks Git Bash or PowerShell")
    assert il.hook_shell("echo hi") == ["/bin/sh", "-c", "echo hi"]


def test_git_bash_follows_claude_code_s_variable_then_looks_in_program_files(tmp_path, monkeypatch):
    bash = tmp_path / "Git" / "bin" / "bash.exe"
    bash.parent.mkdir(parents=True)
    bash.write_bytes(b"")
    monkeypatch.setenv("CLAUDE_CODE_GIT_BASH_PATH", str(bash))
    assert il._git_bash() == str(bash)
    monkeypatch.delenv("CLAUDE_CODE_GIT_BASH_PATH")
    for var in ("ProgramFiles", "ProgramW6432", "ProgramFiles(x86)", "LOCALAPPDATA"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(il.shutil, "which", lambda name: None)
    monkeypatch.setenv("ProgramFiles", str(tmp_path))
    assert il._git_bash() == str(bash)
    monkeypatch.setenv("ProgramFiles", str(tmp_path / "elsewhere"))
    assert il._git_bash() is None


def test_a_git_bash_variable_naming_no_file_fails_the_probe_out_loud(tmp_path, monkeypatch, capsys):
    """Claude Code reports a wrong CLAUDE_CODE_GIT_BASH_PATH instead of quietly using PowerShell, so the probe does too."""
    monkeypatch.setenv("CLAUDE_CODE_GIT_BASH_PATH", str(tmp_path / "missing" / "bash.exe"))
    with pytest.raises(FileNotFoundError, match="CLAUDE_CODE_GIT_BASH_PATH names no file"):
        il._git_bash()
    if os.name == "nt":
        assert project(WORK, tmp_path / "svc", "--apply") == 1
        assert "CLAUDE_CODE_GIT_BASH_PATH names no file" in capsys.readouterr().err


GUARD_BLOCKS = [  # (harness, guard, a command it blocks, its reason)
    (WORK, "guard_work.py", "kubectl delete pod web-1", b"kubectl may only read"),
    (WORK, "guard_work_system.py", "git push origin main", b"blocked by the work-system hook"),
    (SUITE, "guard_work_system.py", "git push --force origin KAN-1-x", b"blocked by the work-system hook"),
    (TEAM, "guard_readonly.py", "kubectl delete pod web-1", b"kubectl may only read"),
]


@pytest.mark.skipif(os.name != "nt", reason="the native Windows shells")
@pytest.mark.parametrize("shell", ["git-bash", "powershell"])
@pytest.mark.parametrize("scope", ["user", "project"])
@pytest.mark.parametrize("tool", ["Bash", "PowerShell"])
@pytest.mark.parametrize("harness, guard, command, reason", GUARD_BLOCKS)
def test_a_guard_still_blocks_through_each_windows_hook_shell(tmp_path, monkeypatch, shell, scope, tool, harness,
                                                              guard, command, reason):
    """The probe only proves a hook starts; this proves a block survives the shell, in both scopes, from a path with a
    space and letters outside the console code page, for a Bash call and a PowerShell call. Git Bash passes exit 2 and
    the reason through. PowerShell's -Command turns a native exit 2 into 1, which Claude Code also treats as a block
    when Git Bash isn't installed (a PreToolUse exit other than 0 or 2 fails closed); the reason still reaches stderr."""
    if shell == "git-bash" and il._git_bash() is None:
        pytest.skip("no Git Bash on this machine")
    if shell == "powershell":
        monkeypatch.setattr(il, "_git_bash", lambda: None)
    monkeypatch.setattr(il, "WINDOWS", True)
    root = tmp_path / "Jörg Ñúñez"
    shutil.copytree(harness / "native" / "claude-code" / "hooks", root / ".claude" / "hooks")
    cmd = il._hook_command(f'python3 "$HOME/.claude/hooks/{guard}"', scope, harness, root / ".claude")
    event = json.dumps({"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": {"command": command}},
                       ensure_ascii=False).encode("utf-8")
    r = subprocess.run(il.hook_shell(cmd), input=event, capture_output=True, timeout=60, cwd=root,
                       env={**os.environ, "CLAUDE_PROJECT_DIR": str(root)})
    assert reason in r.stderr, (cmd, r.stderr)
    assert r.returncode == 2 if shell == "git-bash" else r.returncode != 0


def test_windows_guard_that_cannot_see_powershell_fails_loudly(tmp_path, capsys, monkeypatch):
    """On Windows without Git Bash, Claude Code's shell tool is PowerShell (KAN-482): a guard whose matcher names Bash
    but not PowerShell would see no shell command there, so --apply says so instead of reporting a working setup."""
    monkeypatch.setattr(il, "WINDOWS", True)
    real = il.probe_hooks
    monkeypatch.setattr(il, "probe_hooks", lambda base, scope, entries: real(base, scope, [
        {**r, "value": {**r["value"], "matcher": "Bash|mcp__.*"}}
        if r["section"] == "hooks" and r["key"] == "PreToolUse" else r for r in entries]))
    assert project(WORK, tmp_path / "svc", "--apply") == 1
    err = capsys.readouterr().err
    assert "hook sees no PowerShell call, so its guard is OFF" in err and "install Git for Windows" in err
    assert "--channel candidate" in err  # stable's frozen release still has Bash-only matchers until a promotion


@pytest.mark.parametrize("matcher, bash, powershell", [
    ("Bash", True, False), ("Bash|PowerShell|mcp__.*", True, True), ("(Bash|Edit)", True, False),
    ("Ba.*", True, False), ("", True, True), ("*", True, True), ("mcp__.*", False, False), ("Bash|(", True, False),
])
def test_a_matcher_is_read_as_claude_code_reads_it(matcher, bash, powershell):
    """A regex form like `(Bash|Edit)` must not slip past the check that a guard also sees PowerShell."""
    assert (il._matches(matcher, "Bash"), il._matches(matcher, "PowerShell")) == (bash, powershell)


def test_off_windows_a_bash_only_matcher_is_fine(tmp_path, monkeypatch):
    monkeypatch.setattr(il, "WINDOWS", False)
    real = il.probe_hooks
    monkeypatch.setattr(il, "probe_hooks", lambda base, scope, entries: real(base, scope, [
        {**r, "value": {**r["value"], "matcher": "Bash|mcp__.*"}}
        if r["section"] == "hooks" and r["key"] == "PreToolUse" else r for r in entries]))
    assert project(WORK, tmp_path / "svc", "--apply") == 0


# --- project scope: hooks per machine in settings.local.json, never committed --------------------------------------

def test_mixed_os_team_commits_no_hook_command(tmp_path, monkeypatch):
    """A Mac and a Windows machine install into the same repository: the committed files come out the same, and each
    machine's hook commands stay in its own settings.local.json."""
    committed = {}
    real = il.probe_hooks
    for os_name, win in (("mac", False), ("windows", True)):
        monkeypatch.setattr(il, "WINDOWS", win)
        # the other OS's commands can't start on this host (fake_py covers Windows off Windows, not sh under cmd)
        monkeypatch.setattr(il, "probe_hooks", (lambda *_a: []) if os.name == "nt" and not win else real)
        target = tmp_path / os_name
        assert project(WORK, target, "--apply") == 0
        files = snapshot(target)
        local = {".claude/settings.local.json", ".claude/team-harness.local.json"}
        assert local <= files.keys()
        committed[os_name] = {k: v for k, v in files.items() if k not in local}
        for shared in (".claude/settings.json", ".claude/team-harness.json"):
            text = files[shared].decode("utf-8")
            assert "python3" not in text and "py -3" not in text
    assert committed["mac"] == committed["windows"]  # byte for byte: no churn between the two machines


def test_gitignore_already_covering_settings_local_is_left_alone(tmp_path):
    target = tmp_path / "svc"
    target.mkdir()
    _git(target, "init", "-q")
    (target / ".gitignore").write_bytes(b"*.local.json\n")
    assert project(WORK, target, "--apply") == 0
    assert (target / ".gitignore").read_bytes() == b"*.local.json\n"
    assert "gitignore" not in manifest(target / ".claude")
    assert project(WORK, target, "--uninstall") == 0
    assert (target / ".gitignore").read_bytes() == b"*.local.json\n"


def test_gitignore_line_removed_by_hand_is_drift(tmp_path, capsys):
    target = tmp_path / "svc"
    assert project(WORK, target, "--apply") == 0
    (target / ".gitignore").write_bytes(b"")
    capsys.readouterr()
    assert project(WORK, target, "--check") == 1
    assert ".gitignore no longer has the line .claude/*.local.json" in capsys.readouterr().out
    assert project(WORK, target, "--apply") == 0
    assert project(WORK, target, "--check") == 0


def test_older_project_install_moves_its_hooks_to_settings_local(tmp_path, monkeypatch):
    """An install from before this change put the hooks in the committed settings.json: --apply moves them out, and
    --uninstall still leaves settings.json as the person had it."""
    target = tmp_path / "svc"
    base = target / ".claude"
    base.mkdir(parents=True)
    (base / "settings.json").write_bytes(OWN_SETTINGS)
    real = il.split_settings
    monkeypatch.setattr(il, "split_settings", lambda s, scope: real(s, "user"))  # the old layout
    assert project(WORK, target, "--apply") == 0
    assert "hooks" in manifest(base)["settings"]["entries"][0]["section"]
    monkeypatch.setattr(il, "split_settings", real)
    assert project(WORK, target, "--apply") == 0
    own_hooks = json.loads(OWN_SETTINGS.decode("utf-8-sig"))["hooks"]
    assert settings(base)["hooks"] == own_hooks  # only the person's own hook is left in the committed file
    assert len(settings(base, "settings.local.json")["hooks"]["PreToolUse"]) == 2
    assert project(WORK, target, "--check") == 0
    assert project(WORK, target, "--uninstall") == 0
    assert (base / "settings.json").read_bytes() == OWN_SETTINGS
    assert sorted(p.name for p in target.rglob("*") if p.is_file()) == ["settings.json"]


def test_manifest_records_the_pinned_model_and_runtime(tmp_path):
    """ai-dlc's knowledge doctor prints the pins from the manifest alone (KAN-433)."""
    home = tmp_path / "home"
    home.mkdir()
    lock = yaml.safe_load((SUITE / "harness.lock").read_text())
    assert user(SUITE, home, "--apply") == 0
    m = manifest(home / ".claude")
    assert m["model"] == lock["model"]["id"]
    assert m["runtime_version"] == lock["runtime"]["version"]
