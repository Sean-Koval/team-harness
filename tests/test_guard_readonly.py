"""The PreToolUse guard: what it blocks and what it lets through."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parents[1] / "harnesses/team-default/native/claude-code/hooks/guard_readonly.py"


def run(event: dict) -> int:
    return subprocess.run([sys.executable, str(HOOK)], input=json.dumps(event), capture_output=True,
                          text=True).returncode


def bash(command: str) -> int:
    return run({"tool_name": "Bash", "tool_input": {"command": command}})


@pytest.mark.parametrize("command", [
    "kubectl get pods -n prod",
    "kubectl describe pod api-7d9 -n prod",
    "kubectl logs api-7d9 --previous | grep -i delete",
    "kubectl rollout status deploy/api",
    "kubectl get secrets -n prod",
    "helm status api",
    "echo env",
    "uv run --env-file .env.test pytest",
])
def test_reads_pass(command):
    assert bash(command) == 0


@pytest.mark.parametrize("command", [
    "kubectl delete pod api-7d9",
    "kubectl -n prod scale deploy/api --replicas=0",
    "kubectl --context=prod rollout restart deploy/api",
    "kubectl apply -f k8s/",
    "kubectl exec -it api-7d9 -- sh",
    "kubectl get secret db -o yaml",
    "helm upgrade api ./chart",
    "gcloud container clusters resize c --num-nodes 0",
    "gcloud auth print-access-token",
    "env",
    "ls && printenv",
    "cat ~/.kube/config",
])
def test_writes_and_credential_dumps_are_blocked(command):
    assert bash(command) == 2


def test_other_tools_pass():
    assert run({"tool_name": "Edit", "tool_input": {"file_path": "x"}}) == 0


def test_input_that_is_not_json_fails_closed():
    r = subprocess.run([sys.executable, str(HOOK)], input=b"not json", capture_output=True)
    assert r.returncode == 2 and b"not valid JSON" in r.stderr


def run_bytes(data: bytes) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONIOENCODING", "PYTHONUTF8")}
    return subprocess.run([sys.executable, str(HOOK)], input=data, capture_output=True, env=env)


def test_input_that_is_not_utf8_fails_closed():
    r = run_bytes(b'{"tool_name": "Bash", "tool_input": {"command": "ls \xe9\xff"}}')
    assert r.returncode == 2 and b"not valid UTF-8" in r.stderr


def test_non_ascii_utf8_command_is_still_judged():
    event = {"tool_name": "Bash", "tool_input": {"command": "echo 'café ✓' && kubectl delete pod x"}}
    r = run_bytes(json.dumps(event, ensure_ascii=False).encode("utf-8"))
    assert r.returncode == 2
    assert r.stderr.decode("utf-8").startswith("blocked by the team harness: ")


@pytest.mark.parametrize("command", ["ls\nenv", "echo ok\r\nkubectl delete pod x", "true & helm uninstall api", "kubectl \\\ndelete pod x", "kubectl get pods\nprintenv"])
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
    'kubectl.exe delete pod x',
    "& 'kubectl' delete pod x",
    "'kubectl' delete pod x",
    'kubectl `delete pod x',
    'kubectl `\ndelete pod x',
    "$v='delete'; kubectl $v pod x",
    "Start-Process kubectl -ArgumentList 'delete','pod','x'",
    "iex 'kubectl delete pod x'",
    'cmd /c kubectl delete pod x',
    'C:\\\\tools\\\\kubectl.exe delete pod x',
    'helm.exe uninstall web',
])
def test_powershell_s_own_spellings_are_blocked(tool, command):
    """PowerShell runs these as the plain command: iex and Invoke-Expression are eval, Start-Process and cmd /c are sh -c,
    a backtick escapes the next character or the line end, and $c = 'x' is c=x (PR 40 review). The .exe name
    and a quoted program name are the same program in either shell."""
    r = _tool(tool, command)
    assert r.returncode == 2, (command, r.stderr)


@pytest.mark.parametrize("tool", ["PowerShell", "Bash"])
@pytest.mark.parametrize("command", ['kubectl get pods', 'kubectl.exe get pods,services', "& 'kubectl' describe pod x", 'helm list'])
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
