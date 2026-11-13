"""Every SessionStart and SessionEnd hook command a harness registers runs cleanly in sh (KAN-371).

A reminder that is a shell syntax error never prints, on any OS, and nothing else notices: work-default's echo once
held `company's` inside single quotes. The commands run with an empty stdin event and a scratch HOME.

On Windows the same commands run in the form install_local.py writes for Windows, through the shells Claude Code
runs hooks with there: Git Bash, or PowerShell where Git Bash isn't installed (KAN-460).
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import install_local as il  # noqa: E402
SESSION_EVENTS = ("SessionStart", "SessionEnd")


def _commands():
    for settings in sorted(ROOT.glob("harnesses/*/native/claude-code/settings.json")):
        data = json.loads(settings.read_text(encoding="utf-8"))
        for event in SESSION_EVENTS:
            for group in data.get("hooks", {}).get(event, []):
                for hook in group.get("hooks", []):
                    if hook.get("type") == "command":
                        yield pytest.param(settings.parents[2], hook["command"],
                                           id=f"{settings.parents[2].name}-{event}")


@pytest.mark.skipif(shutil.which("sh") is None, reason="needs a POSIX sh")
@pytest.mark.parametrize("harness, command", list(_commands()))
def test_session_hook_runs_in_sh(harness, command, tmp_path):
    # the harness's hooks as the installer lays them out under $HOME/.claude/hooks
    hooks = harness / "native" / "claude-code" / "hooks"
    if hooks.is_dir():
        shutil.copytree(hooks, tmp_path / ".claude" / "hooks")
    env = {**os.environ, "HOME": str(tmp_path)}
    event = json.dumps({"hook_event_name": "SessionStart", "session_id": "test", "cwd": str(tmp_path)})
    r = subprocess.run(["sh", "-c", command], input=event, capture_output=True, encoding="utf-8", env=env,
                       cwd=tmp_path, timeout=30)
    assert r.returncode == 0, r.stderr
    assert "syntax error" not in r.stderr and "unexpected" not in r.stderr


@pytest.mark.skipif(os.name != "nt", reason="the native Windows hook shells")
@pytest.mark.parametrize("shell", ["git-bash", "powershell"])
@pytest.mark.parametrize("scope", ["user", "project"])
@pytest.mark.parametrize("harness, command", list(_commands()))
def test_session_hook_runs_in_windows_hook_shells(harness, command, scope, shell, tmp_path, monkeypatch):
    if shell == "git-bash" and il._git_bash() is None:
        pytest.skip("no Git Bash on this machine")
    if shell == "powershell":
        monkeypatch.setattr(il, "_git_bash", lambda: None)
    monkeypatch.setattr(il, "WINDOWS", True)
    root = tmp_path / "Jörg Ñúñez"  # a profile or project path with letters outside the console code page
    hooks = harness / "native" / "claude-code" / "hooks"
    if hooks.is_dir():
        shutil.copytree(hooks, root / ".claude" / "hooks")
    else:
        root.mkdir()
    native = il._hook_command(command, scope, harness, root / ".claude")
    env = {**os.environ, "HOME": str(root), "USERPROFILE": str(root), "CLAUDE_PROJECT_DIR": str(root)}
    event = json.dumps({"hook_event_name": "SessionEnd", "session_id": "test", "cwd": str(root)})
    r = subprocess.run(il.hook_shell(native), input=event.encode("utf-8"), capture_output=True, env=env, cwd=root,
                       timeout=60)
    said = (r.stderr or r.stdout).decode("utf-8", "replace")
    assert r.returncode == 0, f"{native}\n{said}"
    if command.startswith("echo "):
        assert command[len("echo '"):len("echo '") + 20] in r.stdout.decode("utf-8", "replace"), said


def test_every_harness_with_a_reminder_is_covered():
    assert len(list(_commands())) >= 3


@pytest.mark.parametrize("harness, command", list(_commands()))
def test_session_reminders_need_no_escaping(harness, command):
    # an echo reminder is one single-quoted string with no quote inside it, so sh, cmd and PowerShell all print it
    # without an interpreter (Windows usually has no python3)
    if not command.startswith("echo "):
        return
    text = command[len("echo "):]
    assert text.startswith("'") and text.endswith("'"), command
    assert "'" not in text[1:-1] and '"' not in text[1:-1], command
