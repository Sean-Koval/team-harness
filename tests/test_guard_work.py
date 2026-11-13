"""The work harness's PreToolUse guard: shared systems read-only, the deploy checkout untouched."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parents[1] / "harnesses/work-default/native/claude-code/hooks/guard_work.py"


def run(event) -> int:
    return subprocess.run([sys.executable, str(HOOK)], input=json.dumps(event), capture_output=True,
                          text=True).returncode


def bash(command: str) -> int:
    return run({"tool_name": "Bash", "tool_input": {"command": command}})


@pytest.mark.parametrize("command", [
    "cd /workspace/infra && terraform fmt -check -recursive",
    "terraform -chdir=/workspace/infra init -backend=false -input=false && terraform validate",
    "terraform init -backend=false",
    "psql -h localhost -U app -c 'select 1'",
    "psql --host=db -U app test",
    "DATABASE_URL=postgres://app:app@127.0.0.1:5432/app make migrate-up",
    "DATABASE_URL=postgresql://app@db:5432/app make test",
    "cat /workspace/deploy/overlays/dev/kustomization.yaml",
    "git -C /workspace/deploy log --oneline -5",
    "grep -r image: /workspace/deploy",
    "kubectl get pods -n svc",
    "make lint test",
])
def test_allowed(command):
    assert bash(command) == 0


@pytest.mark.parametrize("command", [
    "terraform apply -auto-approve",
    "cd /workspace/infra && terraform -chdir=. destroy",
    "terraform import google_storage_bucket.b b",
    "terraform state rm module.queue",
    "terraform init",
    "terraform -chdir=/workspace/infra init -upgrade",
    "terraform plan -out=tf.plan",
    "psql -h prod-db.internal.example.com -U app",
    "pg_dump --host=10.0.0.5 app > dump.sql",
    "DATABASE_URL=postgres://app:secret@prod-db.example.com:5432/app make migrate-up",
    "kubectl -n svc rollout restart deploy/app",
    "helm upgrade app ./chart",
    "printenv",
    "cat ~/.pgpass",
    "sed -i 's/abc/def/' /workspace/deploy/overlays/dev/kustomization.yaml",
    "echo x > /workspace/deploy/overlays/dev/patch.yaml",
    "git -C /workspace/deploy commit -am bump",
    "cd /workspace/deploy && git commit -am bump",
    "rm -rf /workspace/deploy/overlays",
])
def test_blocked(command):
    assert bash(command) == 2


@pytest.mark.parametrize("tool,path,code", [
    ("Edit", "/workspace/deploy/overlays/dev/kustomization.yaml", 2),
    ("Write", "/workspace/deploy/new.yaml", 2),
    ("MultiEdit", "/workspace/deploy", 2),
    ("Edit", "/workspace/code/src/app.py", 0),
    ("Write", "/workspace/deployments-notes.md", 0),
])
def test_edits(tool, path, code):
    assert run({"tool_name": tool, "tool_input": {"file_path": path}}) == code


def test_input_that_is_not_json_fails_closed():
    r = subprocess.run([sys.executable, str(HOOK)], input=b"not json", capture_output=True)
    assert r.returncode == 2 and b"not valid JSON" in r.stderr


def test_json_that_is_not_an_event_fails_closed():
    """It used to pass; a call the hook cannot read as an event is one it cannot check (PR 40 review)."""
    assert run(["a list"]) == 2


def run_bytes(data: bytes) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONIOENCODING", "PYTHONUTF8")}
    return subprocess.run([sys.executable, str(HOOK)], input=data, capture_output=True, env=env)


def test_input_that_is_not_utf8_fails_closed():
    r = run_bytes(b'{"tool_name": "Bash", "tool_input": {"command": "ls \xe9\xff"}}')
    assert r.returncode == 2 and b"not valid UTF-8" in r.stderr


def test_non_ascii_utf8_command_is_still_judged():
    event = {"tool_name": "Bash", "tool_input": {"command": "echo 'café ✓' && terraform apply"}}
    r = run_bytes(json.dumps(event, ensure_ascii=False).encode("utf-8"))
    assert r.returncode == 2
    assert r.stderr.decode("utf-8").startswith("blocked by the work harness: ")


@pytest.mark.parametrize("command", ["ls\nenv", "echo ok\r\nterraform apply", "terraform init\necho -backend=false", "cd /workspace/deploy\ngit commit -am x", "true & kubectl delete pod x", "kubectl \\\ndelete pod x"])
def test_every_line_and_separator_is_judged(command):
    assert bash(command) == 2


@pytest.mark.parametrize("command", [
    "kubectl delete pod web-1",
    "helm upgrade api ./chart",
    "kubectl get pods -n prod",
])
def test_powershell_calls_are_judged_like_bash(command):
    """On Windows without Git Bash, Claude Code's shell tool is PowerShell (KAN-482): the same command gets the same
    verdict and the same reason."""
    def call(tool):
        return subprocess.run([sys.executable, str(HOOK)], capture_output=True,
                              input=json.dumps({"tool_name": tool, "tool_input": {"command": command}}).encode())
    as_bash, as_ps = call("Bash"), call("PowerShell")
    assert (as_ps.returncode, as_ps.stderr) == (as_bash.returncode, as_bash.stderr)
    assert (as_ps.returncode == 2) == (" get " not in command)


def _tool(tool: str, command) -> subprocess.CompletedProcess:
    event = {"tool_name": tool, "tool_input": {"command": command}}
    return subprocess.run([sys.executable, str(HOOK)], input=json.dumps(event).encode(), capture_output=True)


@pytest.mark.parametrize("tool", ["PowerShell", "Bash"])
@pytest.mark.parametrize("command", [
    'terraform.exe apply',
    'terraform.exe apply -auto-approve',
    "& 'terraform' destroy",
    'terraform `apply',
    "$t='apply'; terraform $t",
    "Start-Process terraform -ArgumentList 'apply','-auto-approve'",
    'kubectl.exe delete pod x',
])
def test_powershell_s_own_spellings_are_blocked(tool, command):
    """PowerShell runs these as the plain command: iex and Invoke-Expression are eval, Start-Process and cmd /c are sh -c,
    a backtick escapes the next character or the line end, and $c = 'x' is c=x (PR 40 review). The .exe name
    and a quoted program name are the same program in either shell."""
    r = _tool(tool, command)
    assert r.returncode == 2, (command, r.stderr)


@pytest.mark.parametrize("tool", ["PowerShell", "Bash"])
@pytest.mark.parametrize("command", ['terraform validate', 'terraform.exe fmt', 'terraform init -backend=false', 'kubectl.exe get pods'])
def test_ordinary_powershell_still_passes(tool, command):
    assert _tool(tool, command).returncode == 0, command


@pytest.mark.parametrize("data", [b"null", b"[]", b"7", b'"x"', b'{"tool_name": "Bash"}',
                                  b'{"tool_name": "PowerShell", "tool_input": {"command": 5}}',
                                  b'{"tool_name": "Bash", "tool_input": []}'])
def test_a_call_that_is_not_an_object_or_has_no_command_text_fails_closed(data):
    r = subprocess.run([sys.executable, str(HOOK)], input=data, capture_output=True)
    assert r.returncode == 2 and b"cannot be checked" in r.stderr, (data, r.stderr)


@pytest.mark.skipif(os.name == "nt", reason="closes stdin with the POSIX shell")
def test_a_closed_stdin_fails_closed():
    """With stdin closed, sys.stdin is None: the hook used to crash with exit 1, which lets the call through."""
    r = subprocess.run(["/bin/sh", "-c", f'"{sys.executable}" "{HOOK}" <&-'], capture_output=True)
    assert r.returncode == 2 and b"could not be read" in r.stderr and b"Traceback" not in r.stderr


BLOCKED_CALL = json.dumps({"tool_name": "Bash", "tool_input": {"command": "kubectl delete pod é"}}).encode()


@pytest.mark.parametrize("data", [BLOCKED_CALL, b"not json", b"\xff\xfe"])
def test_a_block_also_denies_on_stdout_with_the_same_reason(data):
    """PowerShell turns exit 2 into 1, so Claude Code reads the verdict from stdout there (KAN-460): a block prints one
    PreToolUse deny, nothing else, with the words stderr carries, and still exits 2 for every caller that reads that."""
    r = subprocess.run([sys.executable, str(HOOK)], input=data, capture_output=True)
    assert r.returncode == 2
    out = json.loads(r.stdout)["hookSpecificOutput"]
    assert (out["hookEventName"], out["permissionDecision"]) == ("PreToolUse", "deny")
    assert out["permissionDecisionReason"] == r.stderr.decode("utf-8").strip()
    assert r.stdout.decode("ascii").strip().count("\n") == 0


def test_an_allowed_call_prints_nothing():
    """A deny is only printed on a block; an allowed call leaves stdout empty, so Claude Code's own flow decides."""
    r = subprocess.run([sys.executable, str(HOOK)], capture_output=True,
                       input=json.dumps({"hook_event_name": "PreToolUse", "tool_name": "Bash",
                                         "tool_input": {"command": "kubectl get pods"}}).encode())
    assert (r.returncode, r.stdout) == (0, b"")
