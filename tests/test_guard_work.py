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


def test_json_that_is_not_an_event_passes():
    assert run(["a list"]) == 0


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
