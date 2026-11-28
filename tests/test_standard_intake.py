"""The normal launcher must validate the structured ticket before it starts an agent."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest


SKILL = Path(__file__).resolve().parents[1] / "shared/work-system/skills/implement-standard"
TOOL = SKILL / "scripts/intake.py"
KEY = "WEB-24"


def run(*args, payload=None):
    return subprocess.run(
        [sys.executable, str(TOOL), *map(str, args)],
        input=json.dumps(payload).encode() if payload is not None else None,
        capture_output=True,
    )


def launch(tmp_path, issue):
    receipt = tmp_path / "first-input"
    child = (
        "import pathlib,sys; "
        "pathlib.Path(sys.argv[1]).write_bytes(sys.stdin.buffer.read()); "
        "sys.exit(7)"
    )
    result = run("run", "-", "--", sys.executable, "-c", child, receipt, payload=issue)
    return result, receipt


def test_config_carries_the_exact_installed_skill():
    body = (SKILL / "SKILL.md").read_bytes()
    config = json.loads(run("hangar-config").stdout)
    assert config == {
        "skill": "implement-standard",
        "label": "standards-change",
        "sha256": hashlib.sha256(body).hexdigest(),
        "content": body.decode("utf-8"),
    }


def test_agent_receives_pinned_bytes_and_its_own_exit_is_preserved(tmp_path):
    result, receipt = launch(tmp_path, {"key": KEY, "fields": {"labels": ["exec:pair", "standards-change"]}})
    assert result.returncode == 7, result.stderr
    config = json.loads(run("hangar-config").stdout)
    delivered = receipt.read_bytes()
    assert delivered.endswith(config["content"].encode("utf-8"))
    assert config["sha256"].encode() in delivered and KEY.encode() in delivered


def test_ordinary_ticket_cannot_trigger_with_prose_or_a_partial_label(tmp_path):
    fields = {"labels": ["STANDARDS-CHANGE", "old-standards-change"], "summary": "standards-change"}
    result, receipt = launch(tmp_path, {"key": KEY, "fields": fields, "labels": ["standards-change"]})
    assert result.returncode == 7
    message = receipt.read_bytes()
    assert KEY.encode() in message
    assert b"standards-change" not in message
    assert (SKILL / "SKILL.md").read_bytes() not in message


@pytest.mark.parametrize("issue", [
    {"key": KEY, "fields": {}},
    {"key": KEY, "fields": {"labels": "standards-change"}},
    {"key": KEY, "fields": {"labels": [False, "standards-change"]}},
    {"key": "WEB-24\nOther", "fields": {"labels": ["standards-change"]}},
    {"issues": [{"key": KEY, "fields": {"labels": ["standards-change"]}}]},
])
def test_unverified_ticket_never_starts_child(tmp_path, issue):
    result, receipt = launch(tmp_path, issue)
    assert result.returncode != 0 and not receipt.exists()
    assert result.stderr
