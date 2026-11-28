#!/usr/bin/env python3
"""Add the installed implement-standard skill after a bound single-issue read."""

import hashlib
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

BINDINGS = r"""{"tracker": ["atlassian"], "wiki": ["atlassian"], "ai-dlc": ["ai-dlc"]}"""
LABEL = "standards-change"
ISSUE_KEY = re.compile(r"[A-Z][A-Z0-9_]*-[1-9][0-9]*", re.ASCII)
TOOL = re.compile(r"mcp__(.+?)__(tracker_get|getJiraIssue)")


def _json(value):
    try:
        return json.loads(value)
    except (ValueError, RecursionError):
        return None


def _failed(response):
    return (response.get("isError", False) is not False or response.get("is_error", False) is not False
            or response.get("success") is False
            or any(response.get(field) for field in ("error", "errors", "errorMessages"))
            or response.get("status") in ("failed", "error", "refused"))


def _single_result(response):
    """Unwrap the MCP envelope or a single JSON text block, without searching arbitrary nested text."""
    if isinstance(response, str):
        response = _json(response)
    if isinstance(response, dict):
        if _failed(response):
            return None
        content = response.get("content")
        if content is not None and content != []:
            # Atlassian publishes the single issue in its text block. Its structured view can be a list.
            if not isinstance(content, list):
                return None
            response = content
        elif "structuredContent" in response:
            response = response["structuredContent"]
    if isinstance(response, list) and len(response) == 1:
        response = response[0]
        if not isinstance(response, dict) or response.get("type") != "text":
            return None
    if (isinstance(response, dict) and response.get("type") == "text"
            and isinstance(response.get("text"), str) and not _failed(response)):
        response = _json(response["text"])
    if (isinstance(response, dict) and not _failed(response)
            and not any(field in response for field in ("issues", "items"))):
        return response
    return None


def _jira_browse(url):
    if not isinstance(url, str):
        return None
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    if parts.scheme == "https" and parts.hostname == parts.netloc.lower() and not (parts.query or parts.fragment):
        prefix, _, key = parts.path.rpartition("/")
        if prefix == "/browse" and ISSUE_KEY.fullmatch(key):
            return parts.hostname, key
    return None


def _atlassian_reference(reference, cloud_id):
    """A direct Jira reference can be a key, numeric id, or HTTPS browse URL."""
    if not isinstance(reference, str) or not reference.startswith("https://"):
        return reference
    browse = _jira_browse(reference)
    if browse is None:
        return None
    host, key = browse
    if isinstance(cloud_id, str):
        try:
            site = urlsplit(cloud_id if "://" in cloud_id else f"//{cloud_id}").hostname
        except ValueError:
            return None
        if site and "." in site and site != host:
            return None
    return key


def _marked_issue(event):
    tool = event.get("tool_name")
    args = event.get("tool_input")
    match = TOOL.fullmatch(tool) if isinstance(tool, str) else None
    if not match or not isinstance(args, dict):
        return None
    server, operation = match.groups()
    role = "ai-dlc" if operation == "tracker_get" else "tracker"
    bindings = _json(BINDINGS)
    if not isinstance(bindings, dict) or server.replace("-", "_") not in {
        name.replace("-", "_") for name in bindings.get(role, [])
    }:
        return None
    result = _single_result(event.get("tool_response"))
    if result is None:
        return None

    if role == "ai-dlc":
        issue = result.get("item")
        if result.get("status") != "ok" or result.get("provider") != "jira-cloud" or not isinstance(issue, dict):
            return None
        # The pinned Jira Cloud provider carries the key in its verified canonical browse URL.
        browse = _jira_browse(issue.get("url"))
        key = browse[1] if browse else None
        labels = issue.get("labels")
        reference = args.get("reference")
    else:
        issue = result.get("data", result)
        if not isinstance(issue, dict) or _failed(issue) or "issues" in issue or "items" in issue:
            return None
        key = issue.get("key")
        fields = issue.get("fields")
        labels = fields.get("labels") if isinstance(fields, dict) else None
        reference = _atlassian_reference(args.get("issueIdOrKey"), args.get("cloudId"))

    if (not isinstance(key, str) or not ISSUE_KEY.fullmatch(key)
            or not isinstance(reference, str) or not reference.isascii()
            or not isinstance(labels, list) or not all(isinstance(label, str) for label in labels)
            or LABEL not in labels):
        return None
    if reference.upper() == key or (re.fullmatch(r"[0-9]+", reference) and issue.get("id") == reference):
        return key
    return None


def main():
    event = _json(sys.stdin.buffer.read())
    if not isinstance(event, dict) or event.get("hook_event_name") != "PostToolUse":
        return
    key = _marked_issue(event)
    if key is None:
        return
    # The installer places hooks and skills under the same .claude directory in either scope.
    skill = Path(__file__).parent.parent / "skills/implement-standard/SKILL.md"
    try:
        data = skill.read_bytes()
        body = data.decode("utf-8")
    except (OSError, UnicodeError):
        body = ""
    if body.strip():
        digest = hashlib.sha256(data).hexdigest()
        context = f"{key} has the {LABEL} label. Installed implement-standard skill (sha256={digest}):\n\n{body}"
    else:
        context = (f"{key} has the {LABEL} label. The installed implement-standard skill body is unavailable. "
                   "Verify or repair the work-default installation and read the skill before making this ticket's "
                   "standards-related edits. Independent work can continue.")
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": context}}))


if __name__ == "__main__":
    main()
