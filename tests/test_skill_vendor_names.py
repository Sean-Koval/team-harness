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
from pathlib import Path

import pytest
import yaml

from test_skill_tool_names import ATLASSIAN_TOOL

ROOT = Path(__file__).resolve().parents[1]
SHARED_SKILLS = ROOT / "shared/work-system/skills"
PROFILES = ROOT / "shared/work-system/profiles"
FIXTURE = ROOT / "tests/fixtures/vendor-skill"

# The vendor's server and connector (atlassian, Rovo), its query languages, and any server-qualified tool name: a
# skill names a role (tracker, knowledge, wiki, transcripts, scm) and a verb, never where the role is served from.
VENDOR = re.compile(r"(?i:\batlassian\b|\brovo\b)|\bJQL\b|\bCQL\b|\bmcp__[\w-]+")
# ai-dlc's role tools, as a skill names them: `tracker_search`, `knowledge_get`.
AI_DLC_TOOL = re.compile(r"`((?:tracker|knowledge)_[a-z][a-z_]*)`")


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


def test_every_ai_dlc_tool_a_skill_names_exists_in_the_pinned_ai_dlc():
    source = _pinned_mcp_server()
    if source is None:
        if os.environ.get("CI"):
            pytest.fail("CI installs the ai-dlc CLI at AI_DLC_REF (.github/workflows/check.yml); it is not on PATH")
        pytest.skip("needs the ai-dlc CLI at the pin, or AI_DLC_CHECKOUT")
    served = set(re.findall(r"@server\.tool\(\)\s*\n\s*def (\w+)\(", source))
    assert {"tracker_search", "knowledge_get"} <= served, "the pinned mcp_server.py no longer reads as expected"
    named = {}
    for f in skill_files(SHARED_SKILLS):
        for tool in AI_DLC_TOOL.findall(f.read_text(encoding="utf-8")):
            named.setdefault(tool, f.relative_to(ROOT).as_posix())
    assert named, "no shared skill names an ai-dlc tool; the scan is broken"
    missing = {t: where for t, where in named.items() if t not in served}
    assert not missing, f"skills name ai-dlc tools the pinned ai-dlc does not serve: {missing}"
