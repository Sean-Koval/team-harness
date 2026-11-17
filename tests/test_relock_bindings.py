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


@pytest.mark.parametrize("name", ["suite-default", "work-default"])
def test_ai_dlc_s_writing_tools_are_write_tools(name):
    """KAN-483: ai-dlc's tools that write past the session, the vault included, are `write_tools`, so hangar's taint
    gate keeps a tainted session from them; its reading tools are not."""
    tools = yaml.safe_load((ROOT / "bindings" / f"{name}.yaml").read_text())["mcp"]["ai-dlc"]["write_tools"]
    writers = {"tracker_create", "tracker_create_decision", "tracker_update", "tracker_comment", "knowledge_propose",
               "knowledge_render",
               "knowledge_pull_transcripts", "knowledge_append", "knowledge_note", "work_publish", "work_pr"}
    assert writers <= set(tools)
    assert not {"tracker_get", "tracker_search", "knowledge_search", "knowledge_check"} & set(tools)


# --- KAN-380: a laptop-only server is declared in bindings, checked, and kept out of the lock and the environments --

def test_work_copilot_is_bound_for_laptops_only():
    """work-default binds Work Copilot as a stdio server marked local_only: its data directory is one `${VAR}` set per
    machine, it is untrusted (captured company text), and the lock leaves it out, since no sandbox runs it."""
    s = yaml.safe_load((ROOT / "bindings" / "work-default.yaml").read_text())["mcp"]["work-copilot"]
    assert s["transport"] == "stdio" and s["command"] == "work-copilot" and s["args"] == ["mcp"]
    assert s["env"] == {"WORK_COPILOT_DATA_DIR": "${WORK_COPILOT_DATA_DIR}"}  # a name, never a path
    assert s["local_only"] is True and s["trust"] == "untrusted"
    h = ROOT / "harnesses" / "work-default"
    assert "work-copilot" not in {m["name"] for m in relock._mcp(h, hl.load(h))}


def test_work_copilot_s_writing_tools_are_write_tools():
    """Its tools that change local state (projects, obligations, priorities, vault notes) are write_tools, and its
    reading tools are not."""
    tools = yaml.safe_load((ROOT / "bindings" / "work-default.yaml").read_text())["mcp"]["work-copilot"]["write_tools"]
    assert {"create_project", "track_obligation", "review_obligation", "update_project", "set_priorities",
            "capture_note"} <= set(tools)
    assert not {"get_attention", "get_project", "get_source", "get_reply_context", "search_context"} & set(tools)


def test_a_local_only_server_never_reaches_the_lock_or_the_environments(tmp_path):
    """hangar's thaw refuses a lock that binds a server its environment doesn't define, and a session's digest counts
    the servers it ran: a local_only server stays out of both, and adding one changes neither."""
    import render_envs

    h, b = _repo(tmp_path, "work-default")
    _edit(b, lambda mcp: mcp.update({"laptop-tool": {"transport": "stdio", "command": "laptop-tool", "args": ["mcp"],
                                                     "env": {"LAPTOP_DIR": "${LAPTOP_DIR}"}, "local_only": True}}))
    before = hl.load(h)
    lock, _ = relock.relock(h)
    assert {m["name"] for m in lock["binding"]["mcp"]} == {m["name"] for m in before["binding"]["mcp"]}
    assert "laptop-tool" not in {m["name"] for m in lock["binding"]["mcp"]} and "work-copilot" not in str(lock)
    assert hl.harness_digest(lock) == hl.harness_digest(before) and lock["revision"] == before["revision"]
    (h / hl.LOCK_FILE).write_text(hl.dump(lock), encoding="utf-8")
    for text in render_envs.render(h).values():
        assert "laptop-tool" not in text and "work-copilot" not in text and "WORK_COPILOT" not in text


@pytest.mark.parametrize("change, message", [
    (lambda mcp: mcp["work-copilot"].update({"local_only": "yes"}), "local_only: true or false"),
    (lambda mcp: mcp["work-copilot"].update({"env": {"WORK_COPILOT_DATA_DIR": "/Users/someone/wc"}}), "one `\\${VAR}`"),
    (lambda mcp: mcp["work-copilot"].update({"env": {"WORK_COPILOT_DATA_DIR": "${HOME}/wc"}}), "one `\\${VAR}`"),
    (lambda mcp: mcp["work-copilot"].pop("args"), "stdio needs command and args"),
    (lambda mcp: mcp["work-copilot"].update({"args": ["mcp", f"--token={TOKEN}"]}), "plain words"),
])
def test_a_misshapen_local_only_server_is_refused(tmp_path, change, message):
    """Left out of the lock, it is still checked: no machine path or token in shared config, and a complete shape."""
    h, b = _repo(tmp_path, "work-default")
    _edit(b, change)
    with pytest.raises(SystemExit, match=message) as e:
        relock.relock(h)
    assert TOKEN not in str(e.value) and "/Users/someone" not in str(e.value)
