#!/usr/bin/env python3
"""PreToolUse hook for the work system: work carries a ticket key, and agents don't move tickets.

Claude Code passes the tool call as JSON on stdin. This exits 2 with the reason on stderr (Claude Code shows it to the
agent and skips the call) for:

- `git commit` on a branch whose name has no ticket key (except `nokey/`, `deps/`, `dependabot/`, `renovate/`
  branches, and the `claude/` branches a cloud session is assigned), or on main/master;
- `git push` to main/master, and `git push --force` / `-f` (use `--force-with-lease` on your own branch);
- `gh pr create` (or a GitHub MCP `create_pull_request`) without a title starting with a key, or without a body (`--body` / `--body-file`) holding the
  `Jira: <KEY>` line for that key and a `Docs:` line, or with `--fill`;
- an Atlassian MCP call that files a ticket with `exec:agent` (or the older `lane:agent`), or edits a ticket's
  execution label: only a person decides what runs unattended;
- any Atlassian MCP call that transitions an issue, and any destructive one: statuses move by Jira automation,
  hangar and people (skill `jira-ticket`);
- `gh pr merge` with `--admin`, always; and, when the harness's merge rule is `never` (skill `github-pr`), every merge
  or approval by any route it can see: `gh pr merge` (also after `gh -R <repo>`), `gh pr review --approve`, a
  `gh api` call to a PR's merge endpoint or the GraphQL merge, auto-merge or approve mutations, and the GitHub MCP
  `merge_pull_request`, `enable_pr_auto_merge` and an `APPROVE` review. `bash -c` / `sh -c` strings are judged too.

Everything else is allowed with exit 0. The only command it runs is `git symbolic-ref --short HEAD` (read-only) to
learn the branch; it writes nothing. The ticket key pattern is `WORK_SYSTEM_KEY` (a regex, default
`[A-Z][A-Z0-9]{1,9}-[0-9]+`) and the PR line's name is `WORK_SYSTEM_TRACKER_LINE` (default `Jira`). `MERGE_RULE` is
rendered per harness by scripts/sync_shared.py from its profile (`allowed` or `never`); anything else, including this
unrendered source, means `never`.

The same rules are checked again on the pull request by the work-system PR check (actions/work-system-pr), which every
surface crosses; this hook only catches them earlier, in the session.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys

KEY = os.environ.get("WORK_SYSTEM_KEY") or r"[A-Z][A-Z0-9]{1,9}-[0-9]+"
LINE = os.environ.get("WORK_SYSTEM_TRACKER_LINE") or "Jira"
MERGE_RULE = "{{merge_mode}}"  # rendered by scripts/sync_shared.py; only "allowed" lets an agent merge
PROTECTED = {"main", "master"}
EXEC = r"(?:exec|lane):"  # execution labels; lane:* is the older name, accepted while Jira is relabelled
NO_KEY_PREFIXES = ("nokey/", "deps/", "dependabot/", "renovate/", "claude/")
MCP_TRANSITION = re.compile(r"^mcp__.+__transition\w*$")  # transitionJiraIssue; not listJiraIssueTransitions
MCP_GENERIC_WRITE = re.compile(r"^mcp__.+__execute(Write|Destructive)$")  # discover/execute: the op is in input.name
MCP_ISSUE_WRITE = re.compile(r"^mcp__.+__(createJiraIssue|editJiraIssue)$")
MCP_DESTRUCTIVE = re.compile(r"^mcp__.+__(executeDestructive|delete\w*)$")
SEGMENT_SPLIT = re.compile(r"\s*(?:&&|\|\||;|\|)\s*")
GH_GLOBAL_WITH_VALUE = ("-R", "--repo", "--hostname")
GH_API_MERGE = re.compile(r"/pulls/[0-9]+/merge\b|\b(mergePullRequest|enablePullRequestAutoMerge)\b"
                          r"|\bAPPROVE\b")
NEVER_MERGE = "agents never merge or approve in this harness: approvers and hangar land PRs (skill github-pr)"


def _branch(cwd: str | None, git_c: str | None) -> str | None:
    where = git_c or cwd or "."
    if git_c and cwd and not os.path.isabs(git_c):
        where = os.path.join(cwd, git_c)
    try:
        # symbolic-ref names the branch even before its first commit, and fails when HEAD is detached
        r = subprocess.run(["git", "-C", where, "symbolic-ref", "--short", "-q", "HEAD"], capture_output=True,
                           text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    name = r.stdout.strip()
    return name if r.returncode == 0 and name else None


def _words(segment: str) -> list[str]:
    try:
        return shlex.split(segment)
    except ValueError:
        return segment.split()


def _git_subcommand(words: list[str]) -> tuple[str | None, str | None, list[str]]:
    """(subcommand, -C path, the words after the subcommand) for a `git ...` command, else (None, None, [])."""
    if not words or os.path.basename(words[0]) != "git":
        return None, None, []
    i, git_c = 1, None
    while i < len(words) and words[i].startswith("-"):
        if words[i] == "-C" and i + 1 < len(words):
            git_c = words[i + 1]
            i += 2
        elif words[i] in ("-c", "--git-dir", "--work-tree") and i + 1 < len(words):
            i += 2
        else:
            i += 1
    if i >= len(words):
        return None, git_c, []
    return words[i], git_c, words[i + 1:]


def _strip_env(words: list[str]) -> list[str]:
    while words and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", words[0]):
        words = words[1:]
    return words


def _commit(cwd: str | None, git_c: str | None) -> str | None:
    branch = _branch(cwd, git_c)
    if branch is None:
        return None  # not a repository, or detached: not ours to judge
    if branch in PROTECTED:
        return f"don't commit on {branch}: start a branch named <KEY>-<slug> for the ticket (skill work-start)"
    if branch.startswith(NO_KEY_PREFIXES):
        return None
    if not re.search(KEY, branch):
        return (f"branch {branch!r} has no ticket key: rename it <KEY>-<slug> (git branch -m), or use a nokey/ branch "
                "for work that deliberately has no ticket (skill work-start)")
    return None


def _push(rest: list[str]) -> str | None:
    if any(w in ("--force", "-f") or (w.startswith("-") and not w.startswith("--") and "f" in w[1:]) for w in rest):
        return "no force push: use --force-with-lease on your own branch"
    for w in rest:
        ref = w.split(":")[-1].removeprefix("+").removeprefix("refs/heads/")
        if ref in PROTECTED:
            return f"never push to {ref}: push the ticket branch and open a PR"
    return None


def _flag(words: list[str], *names: str) -> str | None:
    for i, w in enumerate(words):
        for n in names:
            if w == n and i + 1 < len(words):
                return words[i + 1]
            if w.startswith(n + "="):
                return w.split("=", 1)[1]
    return None


def _pr_create(words: list[str], cwd: str | None) -> str | None:
    if "--fill" in words or "--fill-first" in words or "--fill-verbose" in words:
        return "gh pr create --fill skips the PR contract: pass --title '<KEY>: ...' and a --body with the Jira and Docs lines"
    title = _flag(words, "--title", "-t")
    if not title or not re.match(rf"^({KEY})\b", title):
        return "the PR title must start with the ticket key: --title '<KEY>: <what changes>'"
    key = re.match(rf"^({KEY})", title).group(1)
    body = _flag(words, "--body", "-b")
    body_file = _flag(words, "--body-file", "-F")
    if body is None and body_file:
        path = body_file if os.path.isabs(body_file) or not cwd else os.path.join(cwd, body_file)
        try:
            with open(path, encoding="utf-8") as fh:
                body = fh.read()
        except OSError:
            return None  # the PR check will judge the body; don't wedge on a path we can't read
    if body is None:
        return f"pass the PR body (--body or --body-file) with a '{LINE}: {key}' line and a 'Docs:' line (skill work-docs)"
    if not re.search(rf"(?mi)(?:^|\\n)\W*{re.escape(LINE)}:\s*{re.escape(key)}\b", body):
        return f"the PR body needs the line '{LINE}: {key}' so the tracker links it"
    if not re.search(r"(?mi)(?:^|\\n)\W*Docs:\s*\S", body):
        return "the PR body needs a 'Docs:' line: the files or page you updated, or 'none needed - <why>' (skill work-docs)"
    return None


def _pr_merge(words: list[str]) -> str | None:
    if "--admin" in words:
        return "never merge with --admin: it bypasses branch protection"
    if MERGE_RULE != "allowed":
        return NEVER_MERGE
    return None


def _pr_review(words: list[str]) -> str | None:
    if MERGE_RULE != "allowed" and any(w in ("--approve", "-a") for w in words):
        return NEVER_MERGE
    return None


def _gh_api(words: list[str]) -> str | None:
    if MERGE_RULE != "allowed" and GH_API_MERGE.search(" ".join(words)):
        return NEVER_MERGE
    return None


def _gh_words(words: list[str]) -> list[str]:
    """`gh` and its subcommand words with the global flags (`-R owner/repo`, `--repo=...`) taken out."""
    out, i = words[:1], 1
    while i < len(words):
        w = words[i]
        if w in GH_GLOBAL_WITH_VALUE and i + 1 < len(words):
            i += 2
            continue
        if any(w.startswith(f + "=") for f in GH_GLOBAL_WITH_VALUE if f.startswith("--")):
            i += 1
            continue
        out.append(w)
        i += 1
    return out


def why(event: dict) -> str | None:
    tool = str(event.get("tool_name") or "")
    if MCP_DESTRUCTIVE.match(tool):
        return "destructive tracker or wiki calls are not the agent's: ask a person"
    op = str((event.get("tool_input") or {}).get("name") or "") if MCP_GENERIC_WRITE.match(tool) else ""
    m = MCP_ISSUE_WRITE.match(tool)
    kind = (m.group(1) if m else op if op in ("createJiraIssue", "editJiraIssue") else "").lower()
    if kind:
        text = json.dumps(event.get("tool_input") or {})
        if re.search(EXEC + "agent", text):
            return ("only a person sets exec:agent: it decides what runs unattended. File it exec:pair or exec:human")
        if kind == "editjiraissue" and re.search(EXEC, text):
            return "an execution label that is already set is a person's to change: comment instead"
    if MCP_TRANSITION.match(tool) or op.lower().startswith("transition"):
        return ("agents don't move tickets: Jira automation moves them on branch, PR and merge, hangar moves the ones "
                "it runs, and people move the rest. Comment instead, or list the moves for confirmation "
                "(skills jira-ticket, decision-ticket)")
    if MERGE_RULE != "allowed":
        if re.match(r"^mcp__.+__(merge_pull_request|enable_pr_auto_merge)$", tool):
            return NEVER_MERGE
        if re.match(r"^mcp__.+__\w*review\w*$", tool) and re.search(r"\bAPPROVE\b",
                                                                   json.dumps(event.get("tool_input") or {})):
            return NEVER_MERGE
    if re.match(r"^mcp__.+__create_pull_request$", tool):
        args = event.get("tool_input") or {}
        words = ["--title", str(args.get("title") or ""), "--body", str(args.get("body") or "")]
        return _pr_create(words, None)
    if tool != "Bash":
        return None
    return _bash(str((event.get("tool_input") or {}).get("command") or ""), event.get("cwd"))


def _bash(command: str, cwd: str | None, depth: int = 0) -> str | None:
    for segment in SEGMENT_SPLIT.split(command):
        words = _strip_env(_words(segment.strip()))
        if not words:
            continue
        if words[0] == "cd" and len(words) > 1:
            cwd = words[1] if os.path.isabs(words[1]) or not cwd else os.path.join(cwd, words[1])
            continue
        if os.path.basename(words[0]) in ("bash", "sh", "zsh") and len(words) > 2 and words[1] == "-c" and depth < 3:
            reason = _bash(words[2], cwd, depth + 1)
            if reason:
                return reason
            continue
        if os.path.basename(words[0]) == "gh":
            words = _gh_words(words)
        sub, git_c, rest = _git_subcommand(words)
        if sub == "commit":
            reason = _commit(cwd, git_c)
        elif sub == "push":
            reason = _push(rest)
        elif os.path.basename(words[0]) == "gh" and words[1:3] == ["pr", "create"]:
            reason = _pr_create(words[3:], cwd)
        elif os.path.basename(words[0]) == "gh" and words[1:3] == ["pr", "merge"]:
            reason = _pr_merge(words[3:])
        elif os.path.basename(words[0]) == "gh" and words[1:3] == ["pr", "review"]:
            reason = _pr_review(words[3:])
        elif os.path.basename(words[0]) == "gh" and words[1:2] == ["api"]:
            reason = _gh_api(words[2:])
        else:
            reason = None
        if reason:
            return reason
    return None


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except (ValueError, OSError):
        return 0  # not ours to judge; never wedge a session on a malformed event
    reason = why(event) if isinstance(event, dict) else None
    if reason:
        print(f"blocked by the work-system hook: {reason}.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
