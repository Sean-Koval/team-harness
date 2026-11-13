"""The agent environment (KAN-447): its pins agree, its names are a contract, and the local egress proxy answers as
hangar's policy does. The end-to-end run (two instances, no mounts, egress refused) needs Docker:
`make agent-env-check`."""

import re
import shutil
import socket
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import agent_env  # noqa: E402
import egress_proxy  # noqa: E402


def test_pins_agree():
    # extends is check_registry's rule (KAN-477): the environment serving the pinned digest, here suite-default-candidate
    import check_registry

    assert [p for p in agent_env.pin_problems(ROOT) if "extends" not in p] == []
    raw = yaml.safe_load((ROOT / "environments" / "agent.yaml").read_text())
    assert check_registry.agent_extends_problems(ROOT, "agent", raw["extends"], raw["env"]) == []
    assert check_registry.agent_extends_problems(ROOT, "agent", "suite-default", raw["env"])


def copy_repo(tmp_path: Path) -> Path:
    for d in ("harnesses", "environments"):
        shutil.copytree(ROOT / d, tmp_path / d)
    shutil.copy(ROOT / "channels.yaml", tmp_path / "channels.yaml")
    return tmp_path


def edit_spec(root: Path, edit) -> None:
    f = root / "environments" / "agent.yaml"
    spec = yaml.safe_load(f.read_text())
    edit(spec)
    f.write_text(yaml.safe_dump(spec, sort_keys=False))


@pytest.mark.parametrize("edit,expect", [
    (lambda s: s["env"].update(AGENT_ENV_HARNESS_DIGEST="sha256:" + "0" * 64), "but suite-default provides"),
    (lambda s: s["env"].update(AGENT_ENV_HARNESS_DIGEST="sha256:" + "0" * 64), "no channel"),
    (lambda s: s["env"].update(AI_DLC_REF="main"), "full commit SHA"),
    (lambda s: s["env"].update(AI_DLC_REF="a" * 40), "does not install ai-dlc"),
    (lambda s: s["env"].pop("KNOWLEDGE_FORMAT_VERSION"), "pin(s) missing"),
    (lambda s: s.update(model="claude-other"), "not the harness lock's"),
    (lambda s: s["secrets"].update(NEW_TOKEN="new"), "lacks the spec's secrets: NEW_TOKEN"),
    (lambda s: s["env"].update(CODE_REPO="https://example.com/x.git"), "names values the spec fixes"),
    (lambda s: s["egress"].update(mode="open"), "allowlist"),
    (lambda s: s.update(extends="work-default"), "AGENT_ENV_HARNESS"),
])
def test_a_drifted_pin_fails(tmp_path, edit, expect):
    root = copy_repo(tmp_path)
    edit_spec(root, edit)
    assert any(expect in p for p in agent_env.pin_problems(root)), agent_env.pin_problems(root)


def test_contract_lists_inputs_and_holds_no_values():
    names = agent_env.contract_names()
    assert set(agent_env.INPUTS) <= set(names)
    for line in agent_env.CONTRACT.read_text().splitlines():
        if re.match(r"^[A-Z][A-Z0-9_]*=", line):
            assert re.match(r"^[A-Z][A-Z0-9_]*=\s*(#.*)?$", line), f"a value in the contract: {line}"


def test_no_host_paths_in_the_spec():
    text = (ROOT / "environments" / "agent.yaml").read_text()
    assert "/Users/" not in text and "~/" not in text and "$HOME" not in text


def test_makefile_runs_the_hangar_ci_pins():
    ci = re.search(r"HANGAR_REF: (\w+)", (ROOT / ".github/workflows/check.yml").read_text()).group(1)
    make = re.search(r"HANGAR_REF := (\w+)", (ROOT / "Makefile").read_text()).group(1)
    assert make == ci


def test_policy_is_the_stated_allowlist():
    spec = agent_env.catalog().get(agent_env.ENV_NAME)
    hosts = {("*." if w else "") + h for h, w, _ in agent_env.egress_rules(spec)}
    assert {"github.com", "api.github.com", "pypi.org", "api.atlassian.com", "mcp.atlassian.com",
            "api.anthropic.com"} <= hosts
    assert not any(h.startswith("*.") for h in hosts)
    assert "example.com" not in hosts


@pytest.mark.parametrize("host,port", [
    ("github.com", 443), ("github.com", 80), ("github.com", 22), ("api.github.com", 443), ("evil.github.com", 443),
    ("api.atlassian.com", 443), ("x.api.atlassian.com", 443), ("example.com", 443), ("internal.example.com", 443),
    ("pypi.org", 8443), ("files.pythonhosted.org", 443), ("GITHUB.COM.", 443), ("registry.example.com", 8443),
])
def test_proxy_answers_as_hangar_does(host, port):
    from hangar import egress

    spec = agent_env.catalog().get(agent_env.ENV_NAME).model_copy(update={"egress": egress.EgressSpec(
        mode="allowlist", presets=["github", "pypi"],
        allow=["api.atlassian.com", "*.internal.example.com", "registry.example.com:8443"])})
    policy = egress.resolve(SimpleNamespace(egress_default="allowlist", package_mirror=False, gateway_url=None),
                            spec, harness="claude-code")
    rules = [[r.host, r.wildcard, r.port] for r in policy.rules]
    assert egress_proxy.allowed(rules, host, port) == (policy.allows(egress.normalize_host(host), port) is not None)


@pytest.fixture
def proxy():
    egress_proxy.Handler.rules = [["localhost", False, None]]
    server = egress_proxy.Server(("127.0.0.1", 0), egress_proxy.Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server.server_address
    server.shutdown()
    server.server_close()


def ask(addr, request: bytes) -> str:
    with socket.create_connection(addr, timeout=5) as s:
        s.sendall(request)
        return s.recv(1024).decode().split("\r\n")[0]


def test_proxy_refuses_off_list_plain_http_and_private_addresses(proxy):
    assert ask(proxy, b"CONNECT example.com:443 HTTP/1.1\r\nHost: example.com:443\r\n\r\n").endswith("403 Forbidden")
    plain = ask(proxy, b"GET http://example.com/ HTTP/1.1\r\nHost: example.com\r\n\r\n")
    assert plain.endswith("405 Method Not Allowed")
    # on the list, but it resolves to loopback: refused, as hangar refuses non-public addresses
    assert ask(proxy, b"CONNECT localhost:443 HTTP/1.1\r\nHost: localhost:443\r\n\r\n").endswith("403 Forbidden")
