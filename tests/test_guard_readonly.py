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


def test_other_tools_and_bad_input_pass():
    assert run({"tool_name": "Edit", "tool_input": {"file_path": "x"}}) == 0
    assert subprocess.run([sys.executable, str(HOOK)], input=b"not json", capture_output=True).returncode == 0


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
