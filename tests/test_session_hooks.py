"""Every SessionStart and SessionEnd hook command a harness registers runs cleanly in sh (KAN-371).

A reminder that is a shell syntax error never prints, on any OS, and nothing else notices: work-default's echo once
held `company's` inside single quotes. The commands run with an empty stdin event and a scratch HOME.
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
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
