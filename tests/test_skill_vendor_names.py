"""Seam rule 6 in CI: a shared work-system skill calls ai-dlc's roles, never a vendor's server or tool (KAN-502).

test_skill_tool_names.py keeps Atlassian tool names out of every skill a harness ships, rendered copies included,
where a profile may name the bound server. The shared sources are stricter: they name no vendor server, query
language or tool at all, so swapping the tracker changes a profile, never a skill. What a harness binds (its
tracker server, its searches) is a `{{placeholder}}` its profile fills. And every ai-dlc tool a skill names exists in
the pinned ai-dlc's MCP server, so a skill never sends an agent to a tool that isn't there.
"""

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from skill_rules import ATLASSIAN_TOOL, VENDOR  # noqa: E402  (one rule for intake and CI, KAN-511)

SHARED_SKILLS = ROOT / "shared/work-system/skills"
PROFILES = ROOT / "shared/work-system/profiles"
FIXTURE = ROOT / "tests/fixtures/vendor-skill"

# ai-dlc's role tools, as a skill names them: `tracker_search`, `knowledge_get`.
AI_DLC_TOOL = re.compile(r"`((?:tracker|knowledge)_[a-z][a-z_]*)`")

# Tools a shared skill may name before the pinned ai-dlc serves them, each with the ai-dlc change that adds it. Only a
# skill that stops and reports when the tool is missing may name one. The pin bump that brings a tool in removes its
# entry: test_a_pending_ai_dlc_tool_is_not_served_yet fails until it does.
PENDING_AI_DLC_TOOLS = {
    "tracker_create_decision": "KAN-518 (ai-dlc #291); decision-ticket stops and reports the question without it",
}
STOPS_WHEN_MISSING = "If it is missing"


def skill_files(root: Path) -> list[Path]:
    return sorted({f for skill in root.rglob("SKILL.md") for f in skill.parent.rglob("*.md")})


def vendor_names(root: Path) -> list[str]:
    found = []
    for f in skill_files(root):
        for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            hits = [m.group(0) for m in VENDOR.finditer(line)] + [m.group(0) for m in ATLASSIAN_TOOL.finditer(line)]
            found += [f"{f.relative_to(ROOT).as_posix()}:{n}: {h}" for h in hits]
    return found


def test_no_shared_skill_names_a_vendor_server_or_tool():
    found = vendor_names(SHARED_SKILLS)
    assert not found, ("shared skills name a vendor server, query language or tool; name the role and put what the "
                       "harness binds in a profile {{placeholder}} (seam rule 6):\n" + "\n".join(found))


def test_the_check_fails_on_a_skill_that_names_a_vendor():
    found = " ".join(vendor_names(FIXTURE))
    for name in ("JQL", "Atlassian", "createJiraIssue", "mcp__claude_ai_Atlassian__getConfluencePage"):
        assert name in found, name


@pytest.mark.parametrize("text", ["the tracker role", "`tracker_search`", "{{tracker_server}}", "a Jira project",
                                  "the jira-ticket skill", "`ai-dlc knowledge records search`"])
def test_the_check_leaves_roles_and_product_words_alone(text):
    assert not VENDOR.search(text) and not ATLASSIAN_TOOL.search(text)


@pytest.mark.parametrize("profile", sorted(PROFILES.glob("*.yaml")), ids=lambda p: p.stem)
def test_the_named_tracker_server_is_the_bound_one(profile):
    params = yaml.safe_load(profile.read_text(encoding="utf-8"))["params"]
    named = re.findall(r"`([^`]+)`", params["tracker_server"])
    assert named and set(named) <= set(json.loads(params["mcp_bindings"])["tracker"]), profile.name


def _pinned_mcp_server() -> str | None:
    """The pinned ai-dlc's mcp_server.py: from a checkout (AI_DLC_CHECKOUT) at the pin, or from the `ai-dlc` CLI on
    PATH, which CI installs at the pin (.github/workflows/check.yml) and which must say it was built from the pin."""
    ref = yaml.safe_load((ROOT / "environments/agent.yaml").read_text(encoding="utf-8"))["env"]["AI_DLC_REF"]
    checkout = os.environ.get("AI_DLC_CHECKOUT")
    if checkout:
        r = subprocess.run(["git", "-C", checkout, "show", f"{ref}:src/ai_dlc/mcp_server.py"],
                           capture_output=True, text=True, encoding="utf-8")
        assert r.returncode == 0, f"AI_DLC_CHECKOUT has no commit {ref}: {r.stderr}"
        return r.stdout
    cli = shutil.which("ai-dlc")
    if not cli:
        return None
    python = Path(os.path.realpath(cli)).parent / ("python.exe" if os.name == "nt" else "python")
    code = ("import importlib.metadata as m, json, ai_dlc.mcp_server as s;"
            "u = json.loads(m.distribution('ai-dlc').read_text('direct_url.json') or '{}');"
            "print(json.dumps([u.get('vcs_info', {}).get('commit_id'), s.__file__]))")
    r = subprocess.run([str(python), "-c", code], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    commit, path = json.loads(r.stdout)
    assert commit == ref, f"the ai-dlc on PATH is built from {commit}, not the pin {ref}"
    return Path(path).read_text(encoding="utf-8")


def _served_by_the_pin() -> set[str]:
    source = _pinned_mcp_server()
    if source is None:
        if os.environ.get("CI"):
            pytest.fail("CI installs the ai-dlc CLI at AI_DLC_REF (.github/workflows/check.yml); it is not on PATH")
        pytest.skip("needs the ai-dlc CLI at the pin, or AI_DLC_CHECKOUT")
    served = set(re.findall(r"@server\.tool\(\)\s*\n\s*def (\w+)\(", source))
    assert {"tracker_search", "knowledge_get"} <= served, "the pinned mcp_server.py no longer reads as expected"
    return served


def _ai_dlc_tools_named() -> dict[str, list[Path]]:
    named: dict[str, list[Path]] = {}
    for f in skill_files(SHARED_SKILLS):
        for tool in sorted(set(AI_DLC_TOOL.findall(f.read_text(encoding="utf-8")))):
            named.setdefault(tool, []).append(f)
    assert named, "no shared skill names an ai-dlc tool; the scan is broken"
    return named


def test_every_ai_dlc_tool_a_skill_names_exists_in_the_pinned_ai_dlc():
    served = _served_by_the_pin()
    missing = {t: [f.relative_to(ROOT).as_posix() for f in where] for t, where in _ai_dlc_tools_named().items()
               if t not in served and t not in PENDING_AI_DLC_TOOLS}
    assert not missing, f"skills name ai-dlc tools the pinned ai-dlc does not serve: {missing}"


@pytest.mark.parametrize("tool", sorted(PENDING_AI_DLC_TOOLS))
def test_a_pending_ai_dlc_tool_is_not_served_yet(tool):
    assert tool not in _served_by_the_pin(), (
        f"the pinned ai-dlc serves {tool} now: remove it from PENDING_AI_DLC_TOOLS ({PENDING_AI_DLC_TOOLS[tool]})")


@pytest.mark.parametrize("tool", sorted(PENDING_AI_DLC_TOOLS))
def test_only_a_skill_that_stops_without_it_names_a_pending_tool(tool):
    where = _ai_dlc_tools_named().get(tool)
    assert where, f"no shared skill names {tool}: remove it from PENDING_AI_DLC_TOOLS"
    for f in where:
        text = f.read_text(encoding="utf-8")
        assert STOPS_WHEN_MISSING in text, (
            f"{f.relative_to(ROOT).as_posix()} names {tool}, which the pinned ai-dlc does not serve yet, without "
            f"saying what to do when it is missing ('{STOPS_WHEN_MISSING} ..., stop')")
