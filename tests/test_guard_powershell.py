"""Every shell guard on a Windows machine without Git Bash (KAN-482): Claude Code's shell tool there is PowerShell, and
nothing but Windows Python runs the guard. Each guard lets an ordinary PowerShell call through, blocks a forbidden one
with the reason it gives the same command from Bash, and blocks a PowerShell call it can't read with exit 2 (the
installer's probe needs that 2, KAN-460).

The guards run here with an empty PATH, so no git, bash or sh can be found: what they decide can't depend on Git for
Windows. The Windows CI job runs this file, on Python 3.12 and 3.13."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import install_local as il  # noqa: E402

WORK_SYSTEM = ROOT / "shared/work-system/hooks/guard_work_system.py"  # the source; harness copies are generated
WORK = ROOT / "harnesses/work-default/native/claude-code/hooks/guard_work.py"
READONLY = ROOT / "harnesses/team-default/native/claude-code/hooks/guard_readonly.py"

# (guard, a PowerShell call it allows, one it blocks, words its reason carries)
GUARDS = [
    pytest.param(WORK_SYSTEM, "gh pr view 12; git status", "gh pr merge 12 --squash",
                 "blocked by the work-system hook", id="work-system"),
    pytest.param(WORK, "kubectl get pods -n svc; terraform.exe validate", "terraform.exe apply -auto-approve",
                 "blocked by the work harness", id="work"),
    pytest.param(READONLY, "kubectl get pods -n prod | Select-String api", "& 'kubectl' delete pod api-7d9",
                 "kubectl may only read", id="readonly"),
]

UNREADABLE = [
    pytest.param(b'{"tool_name": "PowerShell", "tool_input": {"command": "Get-ChildItem \xe9\xff"}}', id="not-utf8"),
    pytest.param(b'{"tool_name": "PowerShell", "tool_input": {"command": "Get-ChildItem"', id="truncated"),
    pytest.param(b'{"tool_name": "PowerShell"}', id="no-input"),
    pytest.param(b'{"tool_name": "PowerShell", "tool_input": {"command": null}}', id="no-command"),
    pytest.param(b'{"tool_name": "PowerShell", "tool_input": "Get-ChildItem"}', id="input-not-object"),
    pytest.param("﻿".encode() + b'{"tool_name": "PowerShell", "tool_input": {"command": 7}}', id="bom-number"),
]


def no_git_env(tmp: Path) -> dict[str, str]:
    """This environment with an empty PATH and no Git Bash named: Windows still finds Python, run by its full path."""
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONIOENCODING", "PYTHONUTF8",
                                                           "CLAUDE_CODE_GIT_BASH_PATH")}
    empty = tmp / "empty-path"
    empty.mkdir(exist_ok=True)
    env["PATH"] = str(empty)
    return env


def guard(hook: Path, data: bytes, tmp: Path) -> subprocess.CompletedProcess:
    # cwd outside any repository, so the work-system guard reads no branch from this checkout (KAN-501)
    return subprocess.run([sys.executable, str(hook)], input=data, capture_output=True, cwd=tmp, env=no_git_env(tmp),
                          timeout=60, check=False)


def call(tool: str, command: str) -> bytes:
    return json.dumps({"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": {"command": command}},
                      ensure_ascii=False).encode("utf-8")


def deny(stdout: bytes) -> str:
    out = json.loads(stdout)["hookSpecificOutput"]
    assert (out["hookEventName"], out["permissionDecision"]) == ("PreToolUse", "deny")
    return out["permissionDecisionReason"]


def test_the_guards_find_no_git_or_bash(tmp_path):
    """The premise of the file: with this environment, Git for Windows' git and bash are out of reach."""
    path = no_git_env(tmp_path)["PATH"]
    assert [p for p in ("git", "bash", "sh") if shutil.which(p, path=path)] == []


@pytest.mark.parametrize("hook, allowed, blocked, reason", GUARDS)
def test_an_ordinary_powershell_call_passes(tmp_path, hook, allowed, blocked, reason):
    r = guard(hook, call("PowerShell", allowed), tmp_path)
    assert (r.returncode, r.stdout) == (0, b""), r.stderr


@pytest.mark.parametrize("hook, allowed, blocked, reason", GUARDS)
def test_a_forbidden_powershell_call_is_blocked_as_from_bash(tmp_path, hook, allowed, blocked, reason):
    as_ps, as_bash = guard(hook, call("PowerShell", blocked), tmp_path), guard(hook, call("Bash", blocked), tmp_path)
    assert as_ps.returncode == 2 and reason.encode() in as_ps.stderr, as_ps.stderr
    assert (as_ps.stderr, as_ps.stdout) == (as_bash.stderr, as_bash.stdout)
    assert deny(as_ps.stdout) == as_ps.stderr.decode("utf-8").strip()


@pytest.mark.parametrize("data", UNREADABLE)
@pytest.mark.parametrize("hook", [p.values[0] for p in GUARDS], ids=[p.id for p in GUARDS])
def test_a_powershell_call_the_guard_cannot_read_exits_2(tmp_path, hook, data):
    r = guard(hook, data, tmp_path)
    assert r.returncode == 2, (r.returncode, r.stderr)
    assert deny(r.stdout) == r.stderr.decode("utf-8").strip()
    assert b"Traceback" not in r.stderr


# Through the command the installer writes for Windows, run as Claude Code runs it without Git Bash: in PowerShell.
# A block there is covered by test_install_local.py; this adds the allowed call and the unreadable one. Off Windows it
# runs in pwsh where installed, and skips without it.
needs_powershell = pytest.mark.skipif(not (shutil.which("powershell") or shutil.which("pwsh")),
                                      reason="the Windows hook command needs PowerShell (or pwsh)")


@needs_powershell
@pytest.mark.parametrize("hook, allowed, blocked, reason", GUARDS)
def test_through_the_windows_hook_command(tmp_path, monkeypatch, hook, allowed, blocked, reason):
    monkeypatch.setattr(il, "WINDOWS", True)
    root = tmp_path / "Jörg Ñúñez"
    (root / ".claude" / "hooks").mkdir(parents=True)
    shutil.copy2(hook, root / ".claude" / "hooks" / hook.name)
    harness = ROOT / "harnesses/work-default"
    cmd = il._hook_command(f'python3 "$HOME/.claude/hooks/{hook.name}"', "project", harness,
                           root / ".claude", guard=True)
    if shutil.which("py") is None:  # pwsh off Windows: the test's own Python stands in for the py launcher
        cmd = f'& "{sys.executable}"' + cmd.removeprefix("py -3")
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(root)}

    def run(data: bytes) -> subprocess.CompletedProcess:
        return subprocess.run(il.hook_shell(cmd, "powershell"), input=data, capture_output=True, timeout=60,
                              cwd=root, env=env, check=False)

    ok = run(call("PowerShell", allowed))
    assert (ok.returncode, ok.stdout.strip()) == (0, b""), (cmd, ok.stderr)
    for data in (b"not a tool call", b'{"tool_name": "PowerShell", "tool_input": {}}'):
        r = run(data)
        assert r.returncode == 2, (cmd, data, r.returncode, r.stderr)
