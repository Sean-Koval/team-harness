"""The agent environment (KAN-447): its pins agree and its names are a contract. hangar runs it locally
(`hangar env local`, KAN-472), and the runner and its egress sidecar are tested there; this repository holds no runner
or proxy code. The end-to-end run (two instances, no mounts, egress and DNS refused) needs Docker:
`make agent-env-check`."""

import re
import shutil
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "environments" / "agent.env.example"
sys.path.insert(0, str(ROOT / "scripts"))
import check_registry  # noqa: E402


def test_pins_agree():
    assert check_registry.agent_pin_problems(ROOT) == []
    raw = yaml.safe_load((ROOT / "environments" / "agent.yaml").read_text())
    # extends names the environment serving the pinned digest (KAN-477), here suite-default-candidate, not the harness
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
    assert any(expect in p for p in check_registry.agent_pin_problems(root)), check_registry.agent_pin_problems(root)


def test_contract_lists_inputs_and_holds_no_values():
    names = check_registry.contract_names(CONTRACT)
    assert set(check_registry.AGENT_INPUTS) <= set(names)
    for line in CONTRACT.read_text().splitlines():
        if re.match(r"^[A-Z][A-Z0-9_]*=", line):
            assert re.match(r"^[A-Z][A-Z0-9_]*=\s*(#.*)?$", line), f"a value in the contract: {line}"


def test_no_host_paths_in_the_spec():
    text = (ROOT / "environments" / "agent.yaml").read_text()
    assert "/Users/" not in text and "~/" not in text and "$HOME" not in text


def test_makefile_runs_the_hangar_ci_pins():
    ci = re.search(r"HANGAR_REF: (\w+)", (ROOT / ".github/workflows/check.yml").read_text()).group(1)
    make = re.search(r"HANGAR_REF := (\w+)", (ROOT / "Makefile").read_text()).group(1)
    built = re.search(r"HANGAR_REF: (\w+)", (ROOT / ".github/workflows/generated.yml").read_text()).group(1)
    assert make == ci == built  # the build on main (KAN-481) relocks with the hangar CI checks against


def test_no_runner_or_proxy_code_here():
    """KAN-472: hangar owns the local runner and its egress sidecar; the Makefile calls `hangar env local`."""
    assert not (ROOT / "scripts" / "agent_env.py").exists() and not (ROOT / "scripts" / "egress_proxy.py").exists()
    make = (ROOT / "Makefile").read_text()
    assert "hangar env local" in make and "scripts/agent_env.py" not in make


def test_policy_is_the_stated_allowlist():
    from hangar import localenv

    spec = check_registry.agent_catalog(ROOT).get(check_registry.AGENT_ENV)
    hosts = {("*." if w else "") + h for h, w, _ in localenv.egress_rules(spec)}
    assert {"github.com", "api.github.com", "pypi.org", "api.atlassian.com", "mcp.atlassian.com",
            "api.anthropic.com"} <= hosts
    assert not any(h.startswith("*.") for h in hosts)
    assert "example.com" not in hosts
