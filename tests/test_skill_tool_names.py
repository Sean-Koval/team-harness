"""No skill names an Atlassian MCP tool (KAN-459).

Skills reach the tracker and the wiki by role: ai-dlc's `tracker_*` tools, or the server bound to the tracker role,
used by verb. A skill that names `createJiraIssue` or `executeWrite` ties every harness to one vendor's server and its
tool names, which is what the hook stopped relying on. This scans every skill a harness ships, rendered or released,
and the shared and org sources they come from.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# Atlassian's MCP tools are named for the product (createJiraIssue, getConfluencePage, atlassianUserInfo); its generic
# ones are the execute dispatchers and the Teamwork Graph tools. A server-qualified name (mcp__atlassian__x) counts too.
ATLASSIAN_TOOL = re.compile(
    r"(?<![A-Za-z0-9])(?:[A-Za-z]+(?:Jira|Confluence|Atlassian)[A-Za-z]*"
    r"|(?:jira|confluence)_[a-z_]+"
    r"|atlassian[A-Z][A-Za-z]*"
    r"|execute_?(?:Read|Write|Destructive|read|write|destructive)"
    r"|getTeamworkGraph[A-Za-z]*"
    r"|mcp__(?i:\w*(?:atlassian|jira|confluence)\w*?)__\w+"
    r"|mcp__[\w-]+?__(?i:\w*(?:jira|confluence|atlassian)\w*))(?![A-Za-z0-9])")

SKILL_ROOTS = ["shared/work-system/skills", "orgs", "harnesses"]


def skill_files() -> list[Path]:
    out = []
    for root in SKILL_ROOTS:
        for skill in (ROOT / root).rglob("SKILL.md"):
            out += [f for f in skill.parent.rglob("*.md")]
    return sorted(set(out))


def test_the_scan_sees_every_harness_skill():
    files = {f.relative_to(ROOT).as_posix() for f in skill_files()}
    for expected in ("shared/work-system/skills/jira-ticket/SKILL.md",
                     "harnesses/work-default/skills/work-start/SKILL.md",
                     "harnesses/suite-default/skills/decision-ticket/SKILL.md",
                     "harnesses/work-default/skills/release-approvals/SKILL.md"):
        assert expected in files


@pytest.mark.parametrize("name", ["createJiraIssue", "transitionJiraIssue", "getConfluencePage",
                                  "searchJiraIssuesUsingJql", "atlassianUserInfo", "executeWrite",
                                  "getTeamworkGraphContext", "mcp__atlassian__createJiraIssue", "mcp__jira__x",
                                  "mcp__claude_ai_Atlassian__createJiraIssue", "mcp__Atlassian_MCP__executeWrite",
                                  "mcp__corp__transitionJiraIssue", "TransitionJiraIssue", "jira_transition_issue"])
def test_the_pattern_finds_atlassian_tool_names(name):
    assert ATLASSIAN_TOOL.search(f"call `{name}` here")


@pytest.mark.parametrize("text", ["the jira-ticket skill", "Jira automation moves it", "a Confluence page",
                                  "the Atlassian connector", "tracker_create", "`atlassian` in every harness",
                                  "mcp__github__create_pull_request", "mcp__ai-dlc__tracker_get", "jira-cloud"])
def test_the_pattern_leaves_product_words_alone(text):
    assert not ATLASSIAN_TOOL.search(text)


def test_no_skill_names_an_atlassian_tool():
    found = []
    for f in skill_files():
        for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            found += [f"{f.relative_to(ROOT).as_posix()}:{n}: {m.group(0)}" for m in ATLASSIAN_TOOL.finditer(line)]
    assert not found, "skills name Atlassian tools; use ai-dlc's tracker_* tools or the role (jira-ticket):\n" + \
        "\n".join(found)
