"""The vendor-name rules for skills, in one place (KAN-511, KAN-502, KAN-459).

scripts/add_skill.py (intake), tests/test_skill_tool_names.py (every skill a harness ships) and
tests/test_skill_vendor_names.py (the shared sources) all import these, so intake and CI can never disagree.
"""

from __future__ import annotations

import re

# Atlassian's MCP tools are named for the product (createJiraIssue, getConfluencePage, atlassianUserInfo); its generic
# ones are the execute dispatchers and the Teamwork Graph tools. A server-qualified name (mcp__atlassian__x) counts too.
# Every skill a harness ships, rendered copies included, must not name one (KAN-459).
ATLASSIAN_TOOL = re.compile(
    r"(?<![A-Za-z0-9])(?:[A-Za-z]+(?:Jira|Confluence|Atlassian)[A-Za-z]*"
    r"|(?:jira|confluence)_[a-z_]+"
    r"|atlassian[A-Z][A-Za-z]*"
    r"|execute_?(?:Read|Write|Destructive|read|write|destructive)"
    r"|getTeamworkGraph[A-Za-z]*"
    r"|mcp__(?i:\w*(?:atlassian|jira|confluence)\w*?)__\w+"
    r"|mcp__[\w-]+?__(?i:\w*(?:jira|confluence|atlassian)\w*))(?![A-Za-z0-9])")

# The shared sources are stricter (seam rule 6, KAN-502): no vendor server or connector (atlassian, Rovo), no query
# language, no server-qualified tool name at all. A skill names a role and a verb; what a harness binds is a
# {{placeholder}} its profile fills. "Jira" and "Confluence" as product words stay allowed.
VENDOR = re.compile(r"(?i:\batlassian\b|\brovo\b)|\bJQL\b|\bCQL\b|\bmcp__[\w-]+")


def vendor_hits(line: str) -> list[str]:
    """Every vendor name in one line of a shared skill, by either rule, each once: a name both rules match, or one
    inside another hit (`atlassian` in `mcp__atlassian__getJiraIssue`), is reported once."""
    hits = dict.fromkeys(m.group(0) for rx in (VENDOR, ATLASSIAN_TOOL) for m in rx.finditer(line))
    return [h for h in hits if not any(h != o and h in o for o in hits)]
