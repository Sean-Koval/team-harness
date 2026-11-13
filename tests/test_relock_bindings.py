"""KAN-459: relock.py builds a lock's MCP servers from bindings/<name>.yaml when its servers declare a transport, so a
server added, renamed or moved is a source change and the build writes the lock (KAN-481)."""

import shutil
import sys
from pathlib import Path

import pytest
import yaml

pytest.importorskip("hangar")
from hangar import harness_lock as hl  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import relock  # noqa: E402


def _repo(tmp_path: Path, name: str) -> tuple[Path, Path]:
    h = tmp_path / "harnesses" / name
    shutil.copytree(ROOT / "harnesses" / name, h)
    (tmp_path / "bindings").mkdir()
    b = tmp_path / "bindings" / f"{name}.yaml"
    shutil.copy(ROOT / "bindings" / f"{name}.yaml", b)
    return h, b


def _edit(b: Path, change) -> None:
    data = yaml.safe_load(b.read_text())
    change(data["mcp"])
    b.write_text(yaml.safe_dump(data, sort_keys=False))


@pytest.mark.parametrize("name", ["suite-default", "work-default"])
def test_the_work_system_harnesses_take_their_servers_from_bindings(name):
    """Their bindings declare every server's transport, and the committed lock pins exactly what they build."""
    servers = yaml.safe_load((ROOT / "bindings" / f"{name}.yaml").read_text())["mcp"]
    assert all("transport" in s for s in servers.values())
    assert relock._mcp(ROOT / "harnesses" / name, hl.load(ROOT / "harnesses" / name)) == \
        hl.load(ROOT / "harnesses" / name)["binding"]["mcp"]


def test_renaming_a_server_in_bindings_renames_it_in_the_lock(tmp_path):
    h, b = _repo(tmp_path, "work-default")
    before = hl.load(h)
    _edit(b, lambda mcp: mcp.update({"tracker": mcp.pop("atlassian")}))
    lock, _ = relock.relock(h)
    names = [m["name"] for m in lock["binding"]["mcp"]]
    assert names == ["ai-dlc", "github", "tracker"]  # name order, as a session lists them
    tracker = lock["binding"]["mcp"][2]
    assert tracker == {"name": "tracker", "transport": "http", "endpoint": "https://mcp.atlassian.com/v1/mcp",
                       "header_names": ["Authorization"]}  # names only: no header value reaches the lock
    assert hl.harness_digest(lock) != hl.harness_digest(before)
    assert lock["revision"] == before["revision"] + 1


def test_a_stdio_server_pins_its_command_args_and_env_names(tmp_path):
    h, b = _repo(tmp_path, "suite-default")
    _edit(b, lambda mcp: mcp["ai-dlc"].update({"args": ["mcp", "serve", "--read-only"],
                                               "env": {"KNOWLEDGE_REPO": "${KNOWLEDGE_REPO}", "B": "${B}"}}))
    lock, _ = relock.relock(h)
    assert lock["binding"]["mcp"][0] == {"name": "ai-dlc", "transport": "stdio", "command": "ai-dlc",
                                         "args": ["mcp", "serve", "--read-only"],
                                         "env_names": ["B", "KNOWLEDGE_REPO"]}


def test_bindings_without_transports_keep_the_lock_s_servers(tmp_path):
    """team-default's bindings declare none (it is the running experiment's treated arm): its lock is kept as it is."""
    h, b = _repo(tmp_path, "team-default")
    assert not any("transport" in s for s in yaml.safe_load(b.read_text())["mcp"].values())
    lock, prev = relock.relock(h)
    assert lock["binding"]["mcp"] == prev["binding"]["mcp"]


def test_a_harness_without_bindings_keeps_the_lock_s_servers(tmp_path):
    h = tmp_path / "harnesses" / "work-default"
    shutil.copytree(ROOT / "harnesses" / "work-default", h)
    lock, prev = relock.relock(h)
    assert lock["binding"]["mcp"] == prev["binding"]["mcp"]


@pytest.mark.parametrize("change, message", [
    (lambda mcp: mcp["github"].pop("transport"), "every mcp server a transport, or none"),
    (lambda mcp: mcp["github"].pop("endpoint"), "http needs endpoint"),
    (lambda mcp: mcp["ai-dlc"].pop("args"), "stdio needs command and args"),
    (lambda mcp: mcp["github"].update({"transport": "sse"}), "http needs endpoint"),
])
def test_incomplete_server_declarations_are_refused(tmp_path, change, message):
    h, b = _repo(tmp_path, "work-default")
    _edit(b, change)
    with pytest.raises(SystemExit, match=message):
        relock.relock(h)


def test_rekey_refuses_a_binding_change(tmp_path):
    h, b = _repo(tmp_path, "work-default")
    _edit(b, lambda mcp: mcp.update({"tracker": mcp.pop("atlassian")}))
    with pytest.raises(SystemExit, match="--rekey keeps the binding"):
        relock.relock(h, rekey=True)


TOKEN = "ghp_EXAMPLEnotarealtoken0000"


@pytest.mark.parametrize("change, message", [
    (lambda mcp: mcp["github"].update({"headers": [f"Authorization: Bearer {TOKEN}"]}), "headers: a mapping"),
    (lambda mcp: mcp["github"].update({"headers": {f"Authorization: Bearer {TOKEN}": None}}), "not a header name"),
    (lambda mcp: mcp["ai-dlc"].update({"env": [f"KNOWLEDGE_REPO={TOKEN}"]}), "env: a mapping"),
    (lambda mcp: mcp["ai-dlc"].update({"env": {f"GH_TOKEN={TOKEN}": None}}), "not a variable name"),
    (lambda mcp: mcp["github"].update({"endpoint": f"https://x:{TOKEN}@api.githubcopilot.com/mcp/"}), "endpoint"),
    (lambda mcp: mcp["github"].update({"endpoint": f"https://api.githubcopilot.com/mcp/?token={TOKEN}"}), "endpoint"),
    (lambda mcp: mcp["github"].update({"endpoint": "https://api.githubcopilot.com/mcp/#${GITHUB_TOKEN}"}), "endpoint"),
    (lambda mcp: mcp["github"].update({"endpoint": f"https://api.githubcopilot.com/{TOKEN}/token"}), "endpoint"),
    (lambda mcp: mcp["github"].update({"endpoint": "http://api.githubcopilot.com/mcp/"}), "endpoint"),
    (lambda mcp: mcp["ai-dlc"].update({"args": ["mcp", "serve", f"--token={TOKEN}"]}), "plain words"),
    (lambda mcp: mcp["ai-dlc"].update({"args": ["mcp", "serve", "${KNOWLEDGE_TOKEN}"]}), "plain words"),
    (lambda mcp: mcp["ai-dlc"].update({"command": f"ai-dlc --token {TOKEN}"}), "plain words"),
    (lambda mcp: mcp["ai-dlc"].update({"args": "mcp serve"}), "args: a list"),
    (lambda mcp: mcp["github"].update({"token": TOKEN}), "unknown keys token"),
])
def test_a_misshapen_binding_never_puts_a_value_in_the_lock(tmp_path, change, message):
    """The lock is committed: only names and plain values reach it, and the refusal never echoes the value (R2)."""
    h, b = _repo(tmp_path, "work-default")
    _edit(b, change)
    with pytest.raises(SystemExit, match=message) as e:
        relock.relock(h)
    assert TOKEN not in str(e.value) and "${" not in str(e.value).replace("`${VAR}`", "").replace("`${...}`", "")
