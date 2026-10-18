"""The PreToolUse guard: what it blocks and what it lets through."""

import json
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
