#!/usr/bin/env python3
"""PreToolUse hook for the work system: work carries a ticket key, and agents don't move tickets.

Claude Code passes the tool call as JSON on stdin. This exits 2 with the reason on stderr, and prints the same
reason as a PreToolUse deny on stdout, which Claude Code reads alongside the exit 2 (it shows the reason to the agent
and skips the call), for:

- `git commit` on a branch whose name has no ticket key (except `nokey/`, `deps/`, `dependabot/`, `renovate/`
  branches, and the `claude/` branches a cloud session is assigned), or on main/master;
- `git push` to main/master, and `git push --force` / `-f` (use `--force-with-lease` on your own branch);
- `gh pr create` (or a GitHub MCP `create_pull_request`) without a title starting with a key, or without a body (`--body` / `--body-file`) holding the
  `Jira: <KEY>` line for that key and a `Docs:` line, or with `--fill`;
- on an MCP server bound to the tracker role (or ai-dlc's tracker and work tools), a write that sets `exec:agent`
  (or the older `lane:agent`), or that edits an execution label: only a person decides what runs unattended;
- on a server bound to the tracker or wiki role, any call whose verb is a transition or destructive, and any call
  whose verb the hook does not recognise as a read or an ordinary write (fail closed): statuses move by Jira
  automation, hangar and people (skill `jira-ticket`). Roles are read from the profile's `mcp_bindings`, rendered
  below, so a different Jira server is guarded the same; a server named like Atlassian, Jira or Confluence counts as
  tracker and wiki even when unbound, and so does a server under any other name whose tool is named for Jira,
  Confluence or Atlassian, any tool given an Atlassian site (`cloudId`), and a router (`call_tool`, `use_tool`,
  `RUBE_MULTI_EXECUTE_TOOL`) naming such an operation or server, every operation it names judged. A binding only adds
  roles: it never takes these away, and bindings the hook cannot read refuse every MCP call (fail closed). A server
  whose tools are `tracker_*`, or whose name ends in `ai-dlc`, counts as ai-dlc. Not covered: an unbound server whose
  name, tools and input show no sign of Atlassian (`mcp__tickets2__editIssue`); only the bound server holds the
  Atlassian credential, so such a server cannot reach the site;
- on a server bound to the tracker role, a write that sets a status, state, transition or resolution: that moves the
  ticket as a transition does;
- an MCP tool making an HTTP write (`fetch {url, method: POST}`) to Jira or Confluence, as through curl;
- on a server bound to the wiki role, and for ai-dlc's wiki tools, every page or other wiki write: the render job publishes, sessions propose
  records. The profile's `wiki_write_allow` may allow site and space pairs; a write must name both to use one;
- `gh pr merge` with `--admin`, always; and when the harness's merge rule is `never` (skill `github-pr`), every
  merge, auto-merge, approval and review dismissal: `gh pr merge` (with `-R` anywhere), `gh pr review --approve`,
  `gh api` on the REST merge, review-approve and dismissal endpoints or the GraphQL merge, auto-merge and approve
  mutations, the same through curl, and a GitHub MCP merge, auto-merge or `APPROVE` review;
- a write to Jira or Confluence over HTTP (curl, wget, httpie, Invoke-RestMethod) or from acli or jira-cli that moves,
  deletes, labels `exec:` or writes the wiki: those go through the role-bound MCP tools above.

Labels and other MCP input are compared after NFKC normalisation with format characters (zero-width and the like)
removed, as ai-dlc does, so `exec:agent` with a zero-width space or a fullwidth colon in it still reads as `exec:agent`.

Every command in a call is judged: lines, `;`, `&&`, `||`, `|` and `&` outside quotes separate them, and the
commands inside `$(...)`, backticks, `bash -c` / `sh -c`, `eval`, `( )` and `{ }` groups and function bodies, and
behind `env`, `command`, `exec`, `xargs`, `find -exec`, `watch` and similar prefixes are judged too. Aliases, variables
and `git -c alias.*` defined in the call are expanded, and git's and gh's configured aliases are resolved. A script
the call runs (`bash x.sh`, `source x.sh`, an executable `./x.sh`, `python x.py`) is judged by its contents; code the
hook cannot parse as shell (`python -c`, `node -e`, `perl -e`, `pwsh -Command`, a heredoc or pipe into an
interpreter, a script the same call writes) is scanned for the git and gh commands, GitHub mutations and Jira or
Confluence writes it names. xargs and `find -exec` around a guarded command are refused, since the arguments that
decide it are not in the call. Not covered: shell aliases and functions defined before the call, variables set
outside it, code fetched or built at run time (`bash -c "$(curl ...)"`, base64 decoding, IFS tricks, string
concatenation in a script), and commands build tools read from their own files (`make`, `npm run`, `just`); the PR
check and branch protection still apply. A PowerShell call is also read as PowerShell runs it: `iex` and
`Invoke-Expression` (also `iex('...')`, `-Command` and a string piped into it) are judged as `eval`, every script
block (`Invoke-Command`, `icm`, `% {...}`, `$sb = {...}`, nested) as the commands in it, `Start-Process` (program and `-ArgumentList`) and `cmd /c` as `sh -c`, a backtick before a
character or a line end is that character or a continuation, and `$c = 'x'` sets c as `c=x` does. Not covered there:
a program name built at run time (`& ('g'+'h')`), splatting (`gh @a`) and `[scriptblock]::Create`.
Input that is not UTF-8, not JSON or not an object, a shell call without command text, a closed stdin and any error
in the hook itself are blocked (fail closed). Everything else is allowed with exit 0.
The only commands it runs are `git symbolic-ref --short HEAD`, to learn the branch, and `git config --get
alias.<name>` for a git subcommand it does not know, both read-only; it reads the scripts a call runs and gh's config
file, and writes nothing. The ticket key pattern is `WORK_SYSTEM_KEY` (a regex, default `[A-Z][A-Z0-9]{1,9}-[0-9]+`)
and the PR line's name is `WORK_SYSTEM_TRACKER_LINE` (default `Jira`). `MERGE_RULE` is rendered per harness by
scripts/sync_shared.py from its profile (`allowed` or `never`); anything else, including this
unrendered source, means `never`.

The same rules are checked again on the pull request by the work-system PR check (actions/work-system-pr), which every
surface crosses; this hook only catches them earlier, in the session.

It runs the same on Linux, macOS and native Windows (standard library only, no POSIX-only calls). The event is read
as UTF-8 bytes and the reason written as UTF-8 bytes, whatever the console code page, so a blocked call reads the same
everywhere. A segment holding a drive path (`C:\\repo`) keeps its backslashes; Git Bash paths (`/c/repo`) are mapped to
drive paths on Windows; `git.exe`, `gh.exe` and full program paths are recognised.
"""

from __future__ import annotations

import base64
import json
import os
import re
import shlex
import subprocess
import sys
import time
import unicodedata

KEY = os.environ.get("WORK_SYSTEM_KEY") or r"[A-Z][A-Z0-9]{1,9}-[0-9]+"
LINE = os.environ.get("WORK_SYSTEM_TRACKER_LINE") or "Jira"
MERGE_RULE = "never"  # rendered by scripts/sync_shared.py; only "allowed" lets an agent merge
PROTECTED = {"main", "master"}
EXEC = r"(?i)(?:exec|lane)\s*:"  # execution labels, any case and spacing; lane:* is the older name, accepted while Jira
# is relabelled
NO_KEY_PREFIXES = ("nokey/", "deps/", "dependabot/", "renovate/", "claude/")
# MCP rules are per role and verb, not per tool name. BINDINGS maps a role to the MCP server names a harness binds it
# to; scripts/sync_shared.py renders it from the profile's `mcp_bindings`, which a test holds to the harness lock's
# binding.mcp names. WORK_SYSTEM_MCP_BINDINGS (the same JSON) adds bindings at hook start, for a session whose servers
# are named otherwise. A server named like Atlassian, Jira or Confluence is taken as tracker and wiki even unbound.
ROLES = ("tracker", "wiki", "ai-dlc")
BINDINGS_RENDERED = r"""{"tracker": ["atlassian"], "wiki": ["atlassian"], "ai-dlc": ["ai-dlc"]}"""
ATLASSIAN_HINT = r"atlassian|jira|confluence"  # one server holds both: a name alone cannot tell which it serves
SERVER_HINTS = {"tracker": ATLASSIAN_HINT, "wiki": ATLASSIAN_HINT, "ai-dlc": r"(^|_)ai_?dlc$"}  # on normalised names
AI_DLC_TOOL = re.compile(r"^tracker_")  # ai-dlc's tracker tools, under any server name (`mcp__dlc__tracker_update`)
# An Atlassian server bound to nothing, under a name with no hint ("corp", "tickets2"), is still Atlassian's when its
# tools say so: Atlassian names its tools for the product (createJiraIssue, updateConfluencePage) and its dispatchers
# executeRead, executeWrite and executeDestructive, which take any operation, with or without the site's cloudId. Any
# call carrying an Atlassian site (a cloudId that is a UUID or a *.atlassian.net host, at any depth) counts, whatever
# the tool is called (`createIssue`, `updatePage`). A router of another server (`run`, `call_tool`, `callTool`,
# `use_tool`, Composio's `RUBE_MULTI_EXECUTE_TOOL`) counts when an operation or server it names is Atlassian's.
ATLASSIAN_TOKENS = {"jira", "confluence", "atlassian"}
ATLASSIAN_DISPATCHERS = {"executeread", "executewrite", "executedestructive"}
DISPATCH_WORDS = {"tool", "tools", "operation", "op", "action", "command"}  # `call_tool`, `run_operation`
ROUTER_VERBS = {"execute", "call", "invoke", "run", "use"}  # with a DISPATCH_WORD: a tool that runs another tool
# keys (normalised to lower-case letters) under which a router names the operation it runs, and the server it runs on
OP_KEYS = {"name", "operation", "op", "action", "tool", "toolname", "toolslug", "method", "operationname",
           "operationid", "actionname", "function", "functionname"}
SERVER_KEYS = {"server", "servername", "mcpserver", "app", "appname", "toolkit", "integration", "provider"}
PAYLOAD_KEYS = {"inputs", "input", "arguments", "args", "params", "parameters", "body", "data", "fields", "payload",
                "update", "query", "jql", "cql"}  # what the operation is given: its values are not operation names
# keys that change a ticket's status, at any depth of a tracker write's input: statuses move by automation and people
STATUS_KEYS = {"status", "statusid", "statusname", "state", "stateid", "statename", "transition", "transitionid",
               "transitionname", "resolution", "resolutionid", "resolutionname", "workflowstate", "column"}
URL_KEYS = {"url", "uri", "href", "endpoint", "link", "address"}
ATLASSIAN_SITE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$|(^|[./])atlassian\.net\b",
                            re.IGNORECASE)
MCP_TOOL = re.compile(r"^mcp__(.+?)__(.+)$")
DISPATCH = {"execute", "call", "invoke", "run"}  # a generic tool whose operation is named in its input
BAD_BINDINGS = ("this harness's rendered mcp_bindings (or WORK_SYSTEM_MCP_BINDINGS) is not a JSON object of role -> "
                "server names, so no MCP call can be judged (fail closed): rebuild the harness or fix the variable")
READ = {"get", "list", "search", "fetch", "read", "lookup", "find", "query", "discover", "describe", "show", "view",
        "whoami", "info", "home", "check", "preview", "count", "download", "context", "status", "doctor", "inventory",
        "impact", "gate"}
WRITE = {"create", "add", "edit", "update", "set", "put", "post", "patch", "upsert", "write", "publish", "assign",
         "link", "unlink", "comment", "attach", "upload", "rank", "log", "append", "note", "record", "import", "copy",
         "clone", "rename", "label", "vote", "watch", "start", "finish", "review", "submit", "send", "invite",
         "convert", "duplicate", "restore", "enable", "disable", "mark", "apply", "change", "modify", "save", "insert",
         "replace", "merge", "sync", "push", "register", "reply", "react", "disposition", "propose", "file"}
DESTRUCTIVE = {"delete", "remove", "destroy", "destructive", "purge", "trash", "erase", "drop", "wipe", "archive"}
TRANSITION = {"transition", "resolve", "reopen", "move"}  # `transitions` (plural) is a noun: listJiraIssueTransitions
# Wiki writes: a session never writes the wiki; the render job publishes records. A profile may allow site and space
# pairs (`wiki_write_allow`, JSON: [{"site": "<host>", "space": "<key or id>"}]); the unrendered source allows none.
WIKI_ALLOW_RENDERED = r"""[]"""
WIKI_NOUNS = {"confluence", "page", "pages", "space", "spaces", "blog", "blogpost", "footer", "inline", "wiki",
              "whiteboard", "folder", "content", "database", "smart"}
TRACKER_NOUNS = {"jira", "issue", "issues", "ticket", "tickets", "worklog", "sprint", "epic", "board", "workitem",
                 "transition", "tracker", "work"}
SITE_KEYS = ("cloudId", "cloud_id", "site", "siteUrl", "site_url", "baseUrl", "base_url")
SPACE_KEYS = ("spaceKey", "space_key", "spaceId", "space_id", "space")
NOT_LABELS = {"comment", "worklog", "link"}  # writes whose text may mention a label without setting one
# every command in the call is judged: newlines, ;, &&, ||, | and a background & all start a new one (not 2>&1)
SEGMENT_SPLIT = re.compile(r"\s*(?:\r?\n|&&|\|\||;|\||(?<![<>])&(?![>&]))\s*")
GH_API_MERGE = re.compile(r"(?:^|/)(?:pulls/\d+/merge|merges)/?(?:\?.*)?$")  # the REST merge endpoints
CONTINUATION = re.compile(r"\\\r?\n")  # a backslash-newline joins two lines into one command
DRIVE_PATH = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:\\")  # C:\... : backslashes are separators, not escapes
MSYS_DRIVE = re.compile(r"^/([A-Za-z])(?=/|$)")  # Git Bash's /c/Users/... on Windows
WINDOWS = os.name == "nt"


def _prog(word: str) -> str:
    """The program a command word names: `git` for git, /usr/bin/git, C:\\Git\\cmd\\git.exe or GIT.EXE."""
    name = re.split(r"[\\/]", word)[-1].lower()
    return name[:-4] if name.endswith(".exe") else name


def _path(p: str, cwd: str | None) -> str:
    """`p` as a native path, relative to `cwd` when it is relative."""
    if WINDOWS:
        p = MSYS_DRIVE.sub(lambda m: m.group(1).upper() + ":", p)
    if os.path.isabs(p) or DRIVE_PATH.match(p) or not cwd:
        return p
    return os.path.join(cwd, p)


def _branch(cwd: str | None, git_c: str | None) -> str | None:
    where = _path(git_c, cwd) if git_c else (cwd or ".")
    try:
        # symbolic-ref names the branch even before its first commit, and fails when HEAD is detached
        r = subprocess.run(["git", "-C", where, "symbolic-ref", "--short", "-q", "HEAD"], capture_output=True,
                           encoding="utf-8", errors="replace", timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    name = r.stdout.strip()
    return name if r.returncode == 0 and name else None


def _words(segment: str) -> list[str]:
    try:
        # a Windows path: C:\Users must not lose its backslashes
        return _posix_words(segment, escape=not DRIVE_PATH.search(segment))
    except ValueError:
        return segment.split()


_UNQUOTED = re.compile(r"[^\s'\"\\]+")
_IN_DOUBLE = re.compile(r'[^"\\]+')


def _posix_words(text: str, escape: bool = True) -> list[str]:
    """The words of `text` as shlex reads them (POSIX mode, split on whitespace, no comments), in linear time: shlex
    builds each word a character at a time, which is quadratic on a long word and could hold the hook past its
    timeout. Raises ValueError on an open quote or a trailing backslash, as shlex does."""
    words, cur, i, n, started = [], [], 0, len(text), False
    while i < n:
        c = text[i]
        if c in " \t\r\n":
            if started:
                words.append("".join(cur))
                cur, started = [], False
            i += 1
            continue
        started = True
        if c == "'":
            j = text.find("'", i + 1)
            if j < 0:
                raise ValueError("No closing quotation")
            cur.append(text[i + 1:j])
            i = j + 1
        elif c == '"':
            i += 1
            while True:
                m = _IN_DOUBLE.match(text, i)
                if m:
                    cur.append(m.group(0))
                    i = m.end()
                if i >= n:
                    raise ValueError("No closing quotation")
                if text[i] == '"':
                    i += 1
                    break
                if not escape:  # a backslash, kept as it is
                    cur.append("\\")
                    i += 1
                    continue
                if i + 1 >= n:
                    raise ValueError("No closing quotation")
                nxt = text[i + 1]
                cur.append(nxt if nxt in '"\\' else "\\" + nxt)  # only \" and \\ are escapes inside "..."
                i += 2
        elif c == "\\" and escape:
            if i + 1 >= n:
                raise ValueError("No escaped character")
            cur.append(text[i + 1])
            i += 2
        else:
            m = _UNQUOTED.match(text, i)
            if m:
                cur.append(m.group(0))
                i = m.end()
            else:  # a backslash with escapes off
                cur.append(c)
                i += 1
    if started:
        words.append("".join(cur))
    return words


def _git_subcommand(words: list[str]) -> tuple[str | None, str | None, list[str]]:
    """(subcommand, -C path, the words after the subcommand) for a `git ...` command, else (None, None, [])."""
    if not words or _prog(words[0]) != "git":
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
        try:
            with open(_path(body_file, cwd), "rb") as fh:
                body = _text(fh.read())
        except OSError:
            return None  # the PR check will judge the body; don't wedge on a path we can't read
    if body is None:
        return f"pass the PR body (--body or --body-file) with a '{LINE}: {key}' line and a 'Docs:' line (skill work-docs)"
    if not re.search(rf"(?mi)(?:^|\\n)\W*{re.escape(LINE)}:\s*{re.escape(key)}\b", body):
        return f"the PR body needs the line '{LINE}: {key}' so the tracker links it"
    if not re.search(r"(?mi)(?:^|\\n)\W*Docs:\s*\S", body):
        return "the PR body needs a 'Docs:' line: the files or page you updated, or 'none needed - <why>' (skill work-docs)"
    return None


def _text(data: bytes) -> str:
    """Text from bytes written by any editor or shell: UTF-8 (with or without a BOM) or UTF-16 with a BOM, which
    Windows PowerShell 5 writes by default."""
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16", errors="replace")
    return data.decode("utf-8-sig", errors="replace")


def _pr_merge(words: list[str]) -> str | None:
    if "--admin" in words:
        return "never merge with --admin: it bypasses branch protection"
    if MERGE_RULE != "allowed":
        return NEVER_MERGE
    return None


def _bindings() -> dict[str, set[str]] | None:
    """role -> bound server names (normalised), from the rendered profile and WORK_SYSTEM_MCP_BINDINGS; None when
    either is set but is not a JSON object of role -> list of names (the caller refuses: fail closed)."""
    out: dict[str, set[str]] = {r: set() for r in ROLES}
    for raw in (BINDINGS_RENDERED, os.environ.get("WORK_SYSTEM_MCP_BINDINGS") or ""):
        if not raw.strip() or raw.lstrip().startswith("{{"):
            continue  # unrendered source, or nothing set
        try:
            data = json.loads(raw)
        except ValueError:
            return None
        if not isinstance(data, dict) or not all(isinstance(v, list) for v in data.values()):
            return None
        for role, servers in data.items():
            if role in out:
                out[role] |= {_norm(str(s)) for s in servers}
    return out


def _norm(server: str) -> str:
    return server.lower().replace("-", "_")


def _roles(server: str, tool: str = "", args: dict | None = None) -> set[str]:
    """The roles an MCP server holds: its bindings, plus the roles the hints in its name give, plus tracker and wiki
    when the call itself looks like Atlassian's. A binding only adds roles, so binding an Atlassian-named server to
    another role (WORK_SYSTEM_MCP_BINDINGS included) never takes its guard away."""
    n = _norm(server)
    roles = {role for role, names in (_bindings() or {}).items() if n in names}
    roles |= {role for role, hint in SERVER_HINTS.items() if re.search(hint, n)}
    if AI_DLC_TOOL.match(tool):
        roles.add("ai-dlc")
    if _atlassian_call(tool, args or {}):
        roles |= {"tracker", "wiki"}
    return roles


def _atlassian_call(tool: str, args: dict) -> bool:
    """A call to Atlassian's MCP server under any server name: a tool named for Jira, Confluence or Atlassian, one of
    its execute dispatchers, any tool given an Atlassian site, or a router naming an Atlassian operation or server."""
    tokens = _tokens(tool)
    if ATLASSIAN_TOKENS & set(tokens) or _norm(tool).replace("_", "") in ATLASSIAN_DISPATCHERS:
        return True
    if any(ATLASSIAN_SITE.search(v) for v in _site_values(args)):
        return True  # createIssue {cloudId}, updatePage {cloudId}: the site says whose server this is
    if not _router(tokens):
        return False  # `run_workflow`, `call_api`: a tool of its own, judged by its own server's rules
    return any(ATLASSIAN_TOKENS & set(_op_tokens(v)) for v in _named(args, OP_KEYS | SERVER_KEYS))


def _router(tokens: list[str]) -> bool:
    """A tool that runs another tool named in its input: `run`, `execute`, `call_tool`, `callTool`, `use_tool`,
    `invoke_operation`, `RUBE_MULTI_EXECUTE_TOOL`. Not `run_workflow` or `call_api`, which are tools of their own."""
    return bool(ROUTER_VERBS & set(tokens)) and (len(tokens) == 1 or bool(DISPATCH_WORDS & set(tokens)))


def _key(k) -> str:
    return re.sub(r"[^a-z]", "", k.lower()) if isinstance(k, str) else ""


def _named(value, keys: set[str], depth: int = 0) -> list[str]:
    """Every string under one of `keys` (normalised) at any depth of a router's input, except inside what the
    operation is given (`inputs`, `arguments`, ...), where a `name` is data (a version's or a page's), not an op."""
    out: list[str] = []
    if depth > 8:
        return out
    items = value.items() if isinstance(value, dict) else enumerate(value) if isinstance(value, list) else []
    for k, v in items:
        key = _key(k)
        if key in PAYLOAD_KEYS:
            continue
        if key in keys and isinstance(v, str):
            out.append(v)
        elif isinstance(v, (dict, list)):
            out += _named(v, keys, depth + 1)
    return out


def _op_tokens(name: str) -> list[str]:
    """`jira.transition_issue`, `jira/transition_issue`, `JIRA_TRANSITION_ISSUE`, `transitionJiraIssue` -> tokens."""
    return [t for part in re.split(r"[^A-Za-z0-9]+", name) for t in _tokens(part)]


def _has_key(value, keys: set[str], depth: int = 0) -> bool:
    """Whether any key at any depth of the input normalises to one of `keys`."""
    if depth > 8:
        return False
    items = value.items() if isinstance(value, dict) else enumerate(value) if isinstance(value, list) else []
    for k, v in items:
        if _key(k) in keys and v not in (None, "", [], {}):
            return True
        if isinstance(v, (dict, list)) and _has_key(v, keys, depth + 1):
            return True
    return False


def _site_values(value, depth: int = 0) -> list[str]:
    """Every string under a cloudId-like key (any case, `cloud_id` too), at any depth of the call's input."""
    out: list[str] = []
    if depth > 8:
        return out
    items = value.items() if isinstance(value, dict) else enumerate(value) if isinstance(value, list) else []
    for k, v in items:
        if _key(k) == "cloudid" and isinstance(v, str):
            out.append(v)
        elif isinstance(v, (dict, list)):
            out += _site_values(v, depth + 1)
    return out


def _tokens(name: str) -> list[str]:
    """`addOrEditJiraIssueComment` -> [add, or, edit, jira, issue, comment]; `work_start` -> [work, start]."""
    return [t.lower() for t in re.findall(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|[0-9]+", name)]


def _verb(tokens: list[str]) -> str | None:
    """destructive, transition, read or write for a tool's name tokens; None when no verb is recognised."""
    if DESTRUCTIVE & set(tokens):
        return "destructive"
    if TRANSITION & set(tokens):
        return "transition"
    if WRITE & set(tokens):
        return "write"  # `get_and_update_issue` writes: a read word never hides a write one
    if READ & set(tokens):
        return "read"
    return None


def _mcp(tool: str, args: dict) -> str | None:
    """The verdict for an MCP call on a server bound to the tracker, the wiki or ai-dlc; None for any other server."""
    m = MCP_TOOL.match(tool)
    if not m:
        return None
    if _bindings() is None:
        return BAD_BINDINGS
    reason = _mcp_http(args)
    if reason:
        return reason
    roles = _roles(m.group(1), m.group(2), args)
    if not roles:
        return None
    tokens = _tokens(m.group(2))
    verb = _verb(tokens)
    if not (DISPATCH & set(tokens[:1]) or _router(tokens)):
        return _judge_op(roles, m.group(2), m.group(2), tokens, verb, args)
    # executeWrite {name: transitionJiraIssue}, call_tool {tool_name: jira.transition_issue}: every operation named in
    # the input is judged, and the first refusal stands, so a harmless `name` beside a transition in `operation` does
    # not hide it; a destructive dispatcher stays destructive. A router naming no operation is refused.
    ops = _named(args, OP_KEYS) or [""]
    for op in ops:
        op_tokens = _op_tokens(op)
        op_verb = "destructive" if verb == "destructive" else _verb(op_tokens)
        reason = _judge_op(roles, m.group(2), op, op_tokens, op_verb, args)
        if reason:
            return reason
    return None


def _judge_op(roles: set[str], tool: str, name: str, tokens: list[str], verb: str | None, args: dict) -> str | None:
    """The verdict for one operation (the tool itself, or one a dispatcher names) on a server holding `roles`."""
    where = " or ".join(sorted(roles))
    # ai-dlc's own wiki-role tools (wiki_upsert, ...) are walled like a wiki server's: any of its tools whose name says
    # wiki, Confluence or page, judged by verb, so a tool added later is covered too.
    ai_dlc_wiki = "ai-dlc" in roles and bool(WIKI_NOUNS & set(_tokens(tool) + tokens))
    if verb in ("write", "transition") and (("wiki" in roles and _is_wiki(roles, tokens)) or ai_dlc_wiki):
        return _wiki_write(args)
    if verb == "destructive":
        return "destructive tracker or wiki calls are not the agent's: ask a person"
    if verb == "transition":
        return ("agents don't move tickets: Jira automation moves them on branch, PR and merge, hangar moves the ones "
                "it runs, and people move the rest. Comment instead, or list the moves for confirmation "
                "(skills jira-ticket, decision-ticket)")
    if verb is None:
        return (f"{name or tool!r} on the {where} server is neither a read nor an ordinary write the hook "
                "knows, so it is refused (fail closed): use the role's read and write tools, or ask a person")
    # A write that sets a status on a tracker-bound server moves the ticket as surely as a transition does:
    # `set_status {status: Done}`, `update_ticket {state: closed}`, `editJiraIssue {fields: {status: ...}}`.
    if verb == "write" and "tracker" in roles and not NOT_LABELS & set(tokens) and \
            ({"status", "state", "resolution"} & set(tokens) or _has_key(args, STATUS_KEYS)):
        return ("agents don't move tickets, and a write that sets a status, state or resolution moves one: comment "
                "instead, or list the moves for confirmation (skills jira-ticket, decision-ticket)")
    # exec:* labels are guarded on every tracker-role write, whatever the tool is called: a bound tracker server's
    # writes, and ai-dlc's tracker and work tools (tracker_create, tracker_update, ...), not its knowledge notes.
    tracker_write = "tracker" in roles or ("ai-dlc" in roles and _tokens(tool)[:1] in (["tracker"], ["work"]))
    if verb == "write" and tracker_write and not NOT_LABELS & set(tokens):
        text = json.dumps(_canon_obj(args), ensure_ascii=False)  # exec\u200b:agent and exec\uff1aagent too
        if re.search(EXEC + r"\s*agent", text):
            return "only a person sets exec:agent: it decides what runs unattended. File it exec:pair or exec:human"
        if not {"create", "file"} & set(tokens[:2]) and re.search(EXEC, text):
            return "an execution label that is already set is a person's to change: comment instead"
    return None


def _mcp_http(args: dict) -> str | None:
    """An MCP tool that makes HTTP requests (`fetch {url, method: POST}`) is judged like curl: a write to Jira or
    Confluence over HTTP skips the tracker and wiki rules, whichever server carries it."""
    urls = [u for u in _named(args, URL_KEYS) if ATLASSIAN_URL.search(u.strip())]
    if not urls:
        return None
    methods = [v.strip().upper() for v in _named(args, {"method", "httpmethod", "verb"})]
    body = _has_key(args, {"body", "data", "json", "payload", "form"})
    write = any(v not in ("GET", "HEAD", "OPTIONS") for v in methods) or (not methods and body)
    if write:
        return ("a write to Jira or Confluence over HTTP skips the tracker and wiki rules: use the tracker MCP tools, "
                "or ask a person")
    return None


def _is_wiki(roles: set[str], tokens: list[str]) -> bool:
    """A write on a wiki-bound server is a wiki write unless its name says tracker (a server bound to both roles, such
    as Atlassian's): a name that says neither counts as wiki, so an unknown write is refused (fail closed)."""
    if "tracker" not in roles:
        return True
    return bool(WIKI_NOUNS & set(tokens)) or not TRACKER_NOUNS & set(tokens)


def _wiki_allow() -> list[tuple[str, str]]:
    raw = WIKI_ALLOW_RENDERED.strip()
    if not raw or raw.startswith("{{"):
        return []
    try:
        data = json.loads(raw)
    except ValueError:
        return []
    return [(_site(str(e.get("site") or "")), str(e.get("space") or "").lower())
            for e in (data if isinstance(data, list) else []) if isinstance(e, dict) and e.get("site") and e.get("space")]


def _site(value: str) -> str:
    """`https://x.atlassian.net/wiki` -> `x.atlassian.net`; a cloud id stays as it is."""
    return re.sub(r"^[a-z]+://", "", value.strip().lower()).split("/")[0]


def _field(args: dict, keys: tuple[str, ...]) -> str:
    for scope in (args, args.get("inputs") if isinstance(args.get("inputs"), dict) else {}):
        for k in keys:
            if scope.get(k) not in (None, ""):
                return str(scope[k])
    return ""


def _wiki_write(args: dict) -> str | None:
    allow = _wiki_allow()
    rule = ("sessions don't write the wiki: propose a knowledge record and the render job publishes it "
            "(skill work-docs)")
    if not allow:
        return rule
    site, space = _site(_field(args, SITE_KEYS)), _field(args, SPACE_KEYS).lower()
    if not site or not space:
        return rule + "; a write to an allowed space must name its site and space"
    if (site, space) in allow:
        return None
    return rule + f"; {site} space {space} is not in this harness's wiki_write_allow"


def why(event: dict) -> str | None:
    tool = str(event.get("tool_name") or "")
    args = event.get("tool_input") if isinstance(event.get("tool_input"), dict) else {}
    reason = _mcp(tool, args)
    if reason:
        return reason
    if MCP_TOOL.match(tool):
        reason = _github_mcp(MCP_TOOL.match(tool).group(2), args)
        if reason:
            return reason
    if re.match(r"^mcp__.+__create_pull_request$", tool):
        args = event.get("tool_input") or {}
        words = ["--title", str(args.get("title") or ""), "--body", str(args.get("body") or "")]
        return _pr_create(words, None)
    if tool not in SHELL_TOOLS:
        return None
    command = event["tool_input"].get("command") if isinstance(event.get("tool_input"), dict) else None
    if not isinstance(command, str):
        return "the shell call carries no command text, so it cannot be checked"
    if len(command) > MAX_COMMAND:
        return (f"the command is longer than {MAX_COMMAND >> 20} MB, too long to judge before the hook's timeout: "
                "put the code in a script file and run that")
    cwd = event.get("cwd") if isinstance(event.get("cwd"), str) else None
    _CALL.update(deadline=time.monotonic() + DEADLINE, scripts={})
    try:
        reason = _judge(command, _Ctx(cwd, command), 0)
        if reason or tool != "PowerShell":
            return reason
        ps = _powershell(command)  # PowerShell's own escapes, judged too: either reading may be how it runs
        _CALL["scripts"] = {}  # a script judged in the first reading may read differently in this one
        return _judge(ps, _Ctx(cwd, ps), 0) if ps != command else None
    except _TooLong:
        return (f"the call takes longer than {DEADLINE:g} s to judge, so it cannot be checked before the hook's "
                "timeout, which would let it through: run fewer or smaller scripts in one call")
    finally:
        _CALL.update(deadline=None, scripts={})


# A hook that runs past its timeout (10 s in settings.json) is killed, and Claude Code then runs the call. So judging
# stops at this deadline, well inside the timeout, and the call is blocked instead.
DEADLINE = 5.0
# The deadline is checked between commands, not inside a pass over the whole text, so a very long call could still
# overshoot it on a slow machine: a command this long is blocked unread.
MAX_COMMAND = 1 << 20  # characters
_CALL: dict = {"deadline": None, "scripts": {}}  # this call's deadline, and each script file's verdict once judged


class _TooLong(Exception):
    """Judging the call has passed DEADLINE."""


def _in_time() -> None:
    deadline = _CALL["deadline"]
    if deadline is not None and time.monotonic() > deadline:
        raise _TooLong


def _powershell(command: str) -> str:
    """A PowerShell line as a POSIX shell would read the same words: a backtick before a line end continues the line,
    and before any other character is just that character (`` gh pr `merge `` runs `gh pr merge`), except inside
    single quotes, where PowerShell keeps it."""
    out, i, n, quote = [], 0, len(command), False
    while i < n:
        c = command[i]
        if c == "'":
            quote = not quote
        elif c == "`" and not quote and i + 1 < n:
            nxt = command[i + 1]
            if nxt in "\r\n":
                i += 3 if command.startswith("\r\n", i + 1) else 2
                out.append(" ")
                continue
            out.append(nxt)
            i += 2
            continue
        out.append(c)
        i += 1
    text = "".join(out)
    # Invoke-Expression -Command '...' (or -C, -Com: PowerShell takes any prefix of a parameter name) and iex('...'):
    # the code iex runs, as `iex '...'` reads it. The call's closing parenthesis stays, which changes no verdict.
    text = PS_IEX_COMMAND.sub(r"\1 ", text)
    text = PS_IEX_CALL.sub(r"\1 ", text)
    return _script_blocks(text)


def _script_blocks(text: str) -> str:
    """Every script block's body, and every parenthesis's, as commands of their own: `{`, `}`, `(` and `)` outside
    quotes become `;`. Invoke-Command {...}, icm -ScriptBlock {...}, `% {...}`, Start-Job {...}, an `if` body,
    `$sb={...}`, a grouping `(gh ...)` or `$(gh ...)`, a `param(...)` with its default values and validation scripts,
    and the commands after it, then each have their commands judged, however deeply they nest, whatever is quoted
    inside, and whether or not the block runs.
    `${name}` is a variable, not a block, and stays. A quote still open at the end (a here-string, an escaped quote)
    means the quotes were misread, so the pass is made again with every brace, parenthesis and block-comment marker
    converted and the quotes dropped, which leaves each command's words to be judged. Linear time."""
    out = _blocks(text, track_quotes=True)
    if out is not None:
        return out
    # misread quotes: a block comment's markers become separators too, so the code between comments stands alone
    plain = text.replace("'", " ").replace('"', " ").replace("<#", " ; ").replace("#>", " ; ")
    return _blocks(plain, track_quotes=False)


def _blocks(text: str, track_quotes: bool) -> str | None:
    """With track_quotes, a `$(...)` inside double quotes is code, as PowerShell runs it, and a comment (`#` to the
    line's end, `<# ... #>`) is dropped, so a quote inside one can't hide the code after it."""
    out, i, n, quote = [], 0, len(text), ""
    subs: list[int] = []  # for each `$(` open inside a double-quoted string, the parentheses open inside it
    while i < n:
        c = text[i]
        if quote == '"' and text.startswith("$(", i):
            subs.append(0)
            quote = ""
            out.append('" ; ')  # the string closes here, so the code in it reads as commands
            i += 2
            continue
        if quote:
            quote = "" if c == quote else quote
        elif track_quotes and c in "'\"":
            quote = c
        elif track_quotes and c in "#<" and (not i or text[i - 1] in PS_TOKEN_BREAK):
            if c == "#":  # a comment to the line's end; the line end stays
                end = text.find("\n", i)
                i = n if end < 0 else end
                continue
            if text.startswith("<#", i):  # a block comment
                end = text.find("#>", i + 2)
                out.append(" ")
                i = n if end < 0 else end + 2
                continue
        elif c == "{" and i and text[i - 1] == "$":
            end = text.find("}", i)
            end = n - 1 if end < 0 else end
            out.append(text[i:end + 1])
            i = end + 1
            continue
        elif c == ")" and subs and not subs[-1]:  # the end of a `$(` in a string: back inside the string
            subs.pop()
            quote = '"'
            out.append(' ; "')
            i += 1
            continue
        elif c in "{}()":
            if subs:
                subs[-1] += 1 if c == "(" else -1 if c == ")" else 0
            # `(` leaves a word in its place, as its value: `--body-file (Join-Path . b.md)` keeps a value to judge
            out.append(" __value__ ; " if c == "(" else " ; ")
            i += 1
            continue
        out.append(c)
        i += 1
    return None if quote or subs else "".join(out)


PS_TOKEN_BREAK = " \t\r\n;|&(){}"  # what may come right before a comment's `#` or `<#`


PS_IEX_CALL = re.compile(r"(?i)\b(iex|invoke-expression)\s*@?\(\s*")
PS_IEX_COMMAND = re.compile(r"(?i)\b(iex|invoke-expression)\s+-c(?:o(?:m(?:m(?:a(?:n(?:d)?)?)?)?)?)?(?::|(?=[\s('\"]))")


# Claude Code's shell tools: Bash, and on Windows PowerShell (where Git Bash isn't installed). Both carry the command
# in tool_input.command, and both are judged the same way.
SHELL_TOOLS = frozenset({"Bash", "PowerShell"})

NEVER_MERGE = "agents never merge in this harness: approvers and hangar land PRs (skill github-pr)"
NEVER_APPROVE = ("agents never approve, auto-merge or dismiss reviews in this harness: approvers land PRs "
                 "(skill github-pr)")
APPROVE_VALUE = re.compile(r"(?i)\"(?:event|action|state|review_?event)\"\s*:\s*\"approve\"")


def _github_mcp(name: str, args: dict) -> str | None:
    """A GitHub-style MCP merge, auto-merge or approving review, judged by the merge rule; whatever the server is
    called (merge_pull_request, enable_pr_auto_merge, create_pull_request_review with event APPROVE, ...)."""
    if MERGE_RULE == "allowed":
        return None
    tokens = set(_tokens(name))
    if not {"pull", "pr"} & tokens:
        return None
    if "merge" in tokens and not {"branch", "get", "list", "read", "search", "status"} & tokens:
        return NEVER_MERGE
    if {"review", "approve"} & tokens:
        text = json.dumps(_canon_obj(args), ensure_ascii=False)
        if "approve" in tokens or APPROVE_VALUE.search(text) or "dismiss" in tokens:
            return NEVER_APPROVE
    return None


HEREDOC = re.compile(r"<<(-?)[ \t]*(['\"]?)([A-Za-z0-9_.-]+)\2")


def _split(command: str) -> tuple[list[str], list[str], dict[int, str]]:
    """(the commands, the substitutions, the heredoc bodies) of a shell line: commands split on newlines, ;, &&, ||, |
    and a background & outside quotes; substitutions are the bodies of $(...), <(...), >(...) and `...` outside single
    quotes, judged as commands of their own; a heredoc's body is data for the command that reads it (keyed by that
    command's index), not commands. Raises ValueError on an unbalanced quote or substitution."""
    segs, subs, cur = [], [], []
    bodies: dict[int, str] = {}
    pending: list[tuple[str, bool]] = []
    i, n, quote = 0, len(command), None
    while i < n:
        c = command[i]
        if quote == "'":
            quote = None if c == "'" else quote
            cur.append(c)
            i += 1
            continue
        if c == "\\" and i + 1 < n:
            cur.append(command[i:i + 2])
            i += 2
            continue
        if c == "`":
            j = command.find("`", i + 1)
            if j < 0:
                raise ValueError("unbalanced backtick")
            subs.append(command[i + 1:j])
            cur.append(command[i:j + 1])
            i = j + 1
            continue
        if command.startswith(("$(", "<(", ">("), i):
            depth, j = 1, i + 2
            while j < n and depth:
                depth += {"(": 1, ")": -1}.get(command[j], 0)
                j += 1
            if depth:
                raise ValueError("unbalanced substitution")
            subs.append(command[i + 2:j - 1])
            cur.append(command[i:j])
            i = j
            continue
        if c == '"':
            quote = None if quote == '"' else '"'
        elif c == "'" and quote is None:
            quote = "'"
        elif quote is None and c == "#" and (not i or command[i - 1] in " \t\r\n;&|()"):
            end = command.find("\n", i)  # a comment, to the line's end: a quote in it opens nothing
            i = n if end < 0 else end
            continue
        elif quote is None:
            m = HEREDOC.match(command, i) if command.startswith("<<", i) and not command.startswith("<<<", i) else None
            if m:
                pending.append((m.group(3), m.group(1) == "-"))
                cur.append(m.group(0))
                i = m.end()
                continue
            sep = next((t for t in ("\r\n", "\n", "&&", "||", ";", "|") if command.startswith(t, i)), None)
            if sep is None and c == "&" and command[i - 1:i] not in ("<", ">") and command[i + 1:i + 2] not in (">", "&"):
                sep = "&"
            if sep:
                segs.append("".join(cur))
                cur = []
                i += len(sep)
                if sep.endswith("\n") and pending:
                    i = _heredoc_bodies(command, i, pending, bodies, len(segs) - 1)
                continue
        cur.append(c)
        i += 1
    if quote:
        raise ValueError("unbalanced quote")
    segs.append("".join(cur))
    return segs, subs, bodies


def _heredoc_bodies(command: str, i: int, pending: list[tuple[str, bool]], bodies: dict[int, str], seg: int) -> int:
    """Read the bodies of the heredocs opened on the line just ended; returns where the next command starts."""
    lines = []
    while pending:
        delim, tabs = pending[0]
        end = command.find("\n", i)
        line = command[i:] if end < 0 else command[i:end]
        i = n = len(command) if end < 0 else end + 1
        if (line.lstrip("\t") if tabs else line).rstrip("\r") == delim:
            pending.pop(0)
        else:
            lines.append(line)
        if n >= len(command):
            break
    pending.clear()
    bodies[seg] = "\n".join(lines)
    return i


GROUP_WORDS = {"(", ")", "{", "}", "!", "then", "do", "else", "elif", "if", "while", "until", "time"}
PREFIXES = {"command", "builtin", "exec", "nohup", "nice", "sudo", "doas", "setsid", "stdbuf", "unbuffer", "chronic",
            "ionice", "caffeinate"}
SHELLS = {"bash", "sh", "zsh", "dash", "ksh", "ash", "fish", "mksh"}
INTERPRETERS = re.compile(r"^(?:python[0-9.]*|py|pypy[0-9.]*|node|nodejs|deno|bun|perl|ruby|php|lua|rscript|"
                          r"pwsh|powershell|osascript|tclsh|awk|gawk)$")
HTTP_CLIENTS = {"curl", "wget", "http", "https", "xh", "xhs", "invoke-restmethod", "invoke-webrequest", "irm", "iwr"}
ATLASSIAN_CLIS = {"acli", "jira", "jira-cli"}
ASSIGN = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$", re.S)
PS_ASSIGN = re.compile(r"^\$(?:\{([A-Za-z_][A-Za-z0-9_]*)\}|([A-Za-z_][A-Za-z0-9_]*))\s*=(?!=)\s*(.*)$", re.S)
REDIRECT = re.compile(r"^[0-9]*(?:<<<|<<-?|<>|<&|>&|&>>|&>|>>|>\||<|>)(.*)$")
VAR = re.compile(r"\$(?:\{([A-Za-z_][A-Za-z0-9_]*)\}|([A-Za-z_][A-Za-z0-9_]*))")
PARAM_DEFAULT = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(:?[-=])([^{}]*)\}")
ANSI_C = re.compile(r"\$'((?:[^'\\]|\\.)*)'")
GH_BUILTINS = {"agent-task", "alias", "api", "attestation", "auth", "browse", "cache", "codespace", "completion",
               "config", "copilot", "extension", "ext", "gist", "gpg-key", "help", "issue", "label", "org", "pr",
               "preview", "project", "release", "repo", "ruleset", "run", "search", "secret", "ssh-key", "status",
               "variable", "version", "workflow"}
GIT_BUILTINS = {"add", "am", "apply", "archive", "bisect", "blame", "branch", "bundle", "cat-file", "check-ignore",
                "checkout", "cherry", "cherry-pick", "clean", "clone", "commit", "config", "describe", "diff",
                "difftool", "fetch", "for-each-ref", "format-patch", "fsck", "gc", "grep", "help", "init", "log",
                "ls-files", "ls-remote", "ls-tree", "merge", "merge-base", "mv", "notes", "pull", "push", "range-diff",
                "rebase", "reflog", "remote", "reset", "restore", "rev-list", "rev-parse", "revert", "rm", "shortlog",
                "show", "show-ref", "sparse-checkout", "stash", "status", "submodule", "switch", "symbolic-ref", "tag",
                "update-index", "update-ref", "version", "worktree", "lfs", "credential", "hash-object", "maintenance"}
GH_MUTATIONS = re.compile(r"mergePullRequest|enablePullRequestAutoMerge|dismissPullRequestReview|"
                          r"approvePullRequest")
GH_REVIEW_MUTATION = re.compile(r"(?i)(?:add|submit)PullRequestReview")
APPROVE_WORD = re.compile(r"(?i)\bAPPROVE\b")
GH_APPROVE_EVENT = re.compile(r"(?i)event[\"']?\s*[=:]\s*[\"']?APPROVE\b")
GH_DISMISS = re.compile(r"(?:^|/)pulls/[^/\s]+/reviews/[^/\s]+/dismissals/?$")
ATLASSIAN_URL = re.compile(r"(?i)^(?:https?://)?[^/\s]*(?:atlassian\.net|atlassian\.com|jira|confluence)[^/\s]*(?:/|$)"
                           r"|/rest/api/|/rest/agile/|/wiki/rest/|/wiki/api/")
MAX_SCRIPT = 1 << 20  # bytes of a script file read to judge it


class _Ctx:
    """What one Bash call has set up so far: the directory, and the aliases and variables it defined itself."""

    def __init__(self, cwd: str | None, full: str):
        self.cwd = cwd
        self.full = full  # the whole call, scanned when a command reads code the hook cannot see
        self.aliases: dict[str, str] = {}
        self.git_aliases: dict[str, str] = {}
        self.vars: dict[str, str] = {}
        self.ps_vars: dict[str, str] = {}  # PowerShell's, by lower-case name: its variable names ignore case
        self.stdin: str | None = None  # the heredoc body the current command reads
        self.scanned: list[str | None] = []  # _scan of the whole call, once: each bare iex asks again


def _canon(text: str) -> str:
    """NFKC, without format characters (Unicode Cf: zero-width and the like), as ai-dlc compares labels: `exec:agent`
    with a zero-width space or a fullwidth colon in it reads as `exec:agent`."""
    return "".join(c for c in unicodedata.normalize("NFKC", text) if unicodedata.category(c) != "Cf")


def _canon_obj(value):
    if isinstance(value, str):
        return _canon(value)
    if isinstance(value, dict):
        return {_canon(str(k)): _canon_obj(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_canon_obj(v) for v in value]
    return value


def _expand(segment: str, ctx: _Ctx) -> str:
    """$'...' decoded and the variables this call set substituted, so `X=merge; gh pr $X` reads as it runs."""
    def ansi(m: re.Match) -> str:
        try:
            body = m.group(1).encode("latin-1", "backslashreplace").decode("unicode_escape")
        except (UnicodeDecodeError, UnicodeEncodeError):
            body = m.group(1)
        return shlex.quote(body)
    segment = ANSI_C.sub(ansi, segment)

    def default(m: re.Match) -> str:  # ${X:-pr}, ${X:=pr}: the value if this call set X, else the default
        name, op, word = m.group(1), m.group(2), m.group(3)
        if name in ctx.vars and (ctx.vars[name] or ":" not in op):
            return ctx.vars[name]
        if "=" in op:
            ctx.vars[name] = word
        return word
    segment = PARAM_DEFAULT.sub(default, segment)
    if ctx.vars:
        segment = VAR.sub(lambda m: ctx.vars.get(m.group(1) or m.group(2), m.group(0)), segment)
    if ctx.ps_vars:
        segment = VAR.sub(lambda m: ctx.ps_vars.get((m.group(1) or m.group(2)).lower(), m.group(0)), segment)
    return segment


def _positional(words: list[str]) -> list[str]:
    """`words` without redirections (`> out`, `2>&1`, `<<EOF`, `<<<"text"`)."""
    out, skip = [], False
    for w in words:
        if skip:
            skip = False
            continue
        m = REDIRECT.match(w)
        if m:
            skip = not m.group(1)
            continue
        out.append(w)
    return out


def _unwrap(words: list[str]) -> list[str]:
    """The command a segment runs once groups, function headers, `env`, `command` and similar prefixes are taken
    off."""
    while words:
        before = words
        words = _strip_env(words)
        if words and words[0] == "function" and len(words) > 1:
            words = words[2:]
        elif words and re.match(r"^[A-Za-z_][A-Za-z0-9_.:-]*\(\)$", words[0]):
            words = words[1:]  # f() { gh pr merge 5; }: the body is judged where it is written
        if words and (words[0] in GROUP_WORDS or words[0][:1] in ("(", "{")):
            words = words[1:] if words[0] in GROUP_WORDS else [words[0].lstrip("({")] + words[1:]
        if words and words[-1][-1:] in (")", "}") and not words[-1].startswith("$"):
            words = words[:-1] + ([words[-1].rstrip(")}")] if words[-1].rstrip(")}") else [])
        if words and _prog(words[0]) == "env":
            words = words[1:]
            while words and words[0].startswith("-"):  # env -i, -u NAME, -C DIR
                words = words[2:] if words[0] in ("-u", "-C", "--unset", "--chdir") else words[1:]
        elif words and _prog(words[0]) in PREFIXES:
            words = words[1:]
            while words and words[0].startswith("-"):
                words = words[2:] if words[0] in ("-u", "-g", "-n", "-c", "-t", "-o", "-e", "-i") else words[1:]
        elif words and _prog(words[0]) == "timeout":
            words = words[1:]
            while words and words[0].startswith("-"):
                words = words[2:] if words[0] in ("-s", "-k", "--signal", "--kill-after") else words[1:]
            words = words[1:]  # the duration
        if words == before:
            return words
    return words


def _judge(command: str, ctx: _Ctx, depth: int) -> str | None:
    """The reason to block a shell command line, judging every command in it, nested ones included."""
    if depth > 6:
        return "the command nests shells, scripts and substitutions too deeply to be checked"
    _in_time()
    command = CONTINUATION.sub(" ", command)
    try:
        segments, subs, bodies = _split(command)
    except ValueError:  # unbalanced: judge the pieces as the old splitter did
        segments, subs, bodies = SEGMENT_SPLIT.split(command), [], {}
    for sub in subs:
        reason = _judge(sub, ctx, depth + 1)
        if reason:
            return reason
    for k, segment in enumerate(segments):
        _in_time()
        ctx.stdin = bodies.get(k)
        reason = _segment(_expand(segment.strip(), ctx), ctx, depth)
        if reason:
            return reason
    return None


def _segment(segment: str, ctx: _Ctx, depth: int) -> str | None:
    words = _words(segment)
    if words and words[0] in ("export", "declare", "typeset", "local", "readonly"):
        words = [w for w in words[1:] if not w.startswith("-")]
    m = PS_ASSIGN.match(segment)  # PowerShell's $c = 'merge' (or $c='merge'): remembered as c=merge is
    if m:
        value = _words(m.group(3))
        ctx.vars[m.group(1) or m.group(2)] = " ".join(value) if value else ""
        ctx.ps_vars[(m.group(1) or m.group(2)).lower()] = ctx.vars[m.group(1) or m.group(2)]  # $C is $c there
        return None
    for w in words:  # X=merge on its own (or before a command) is remembered for the rest of the call
        m = ASSIGN.match(w)
        if not m:
            break
        ctx.vars[m.group(1)] = m.group(2)
    words = _unwrap(words)
    if words and words[0] in ctx.aliases:  # an alias this call defined
        words = _unwrap(_words(ctx.aliases[words[0]]) + words[1:])
    if not words:
        return None
    prog = _prog(words[0])
    if words[0] == "cd" and len(words) > 1:
        ctx.cwd = _path(words[1], ctx.cwd)
        return None
    if prog == "alias":
        for w in words[1:]:
            m = ASSIGN.match(w)
            if m:
                ctx.aliases[m.group(1)] = m.group(2)
        return None
    if prog in ("iex", "invoke-expression"):  # PowerShell's eval; with no argument, the code comes down the pipeline
        return _judge(" ".join(words[1:]), ctx, depth + 1) or \
            (_scan_full(ctx) if len(words) == 1 or re.search(r"\$[({A-Za-z_]", " ".join(words[1:])) else None)
    if prog == "cmd":
        code = next((i for i, w in enumerate(words[1:], 1) if w.lower() in ("/c", "/k", "/r")), None)
        return _judge(" ".join(words[code + 1:]), ctx, depth + 1) if code else None
    if prog in ("start-process", "saps", "start"):
        return _start_process(words, ctx, depth)
    if prog == "eval":
        code = " ".join(words[1:])
        return _judge(code, ctx, depth + 1) or (_scan_full(ctx) if re.search(r"\$[({A-Za-z_]|`", code) else None)
    if prog in ("source", ".") and len(words) > 1:
        return _script(words[1], ctx, depth, "shell")
    if prog in SHELLS:
        return _shell(words, ctx, depth)
    if INTERPRETERS.match(prog):
        return _interpreter(prog, words, ctx, depth)
    if prog == "xargs":
        return _xargs(words, ctx, depth)
    if prog == "find":
        return _find(words, ctx, depth)
    if prog in ("watch", "su", "script", "runuser"):
        return _wrapped(prog, words, ctx, depth)
    if prog in HTTP_CLIENTS:
        return _http(words, ctx.full)
    if prog in ATLASSIAN_CLIS:
        return _atlassian_cli(words)
    if words[0].startswith("$"):  # a program the hook cannot resolve: judge it as git and as gh
        return _command(["git"] + words[1:], ctx) or _command(["gh"] + words[1:], ctx)
    if prog not in ("git", "gh") and re.search(r"[\\/]", words[0]):
        return _program(words[0], ctx, depth)
    return _command(words, ctx)


def _start_process(words: list[str], ctx: _Ctx, depth: int) -> str | None:
    """PowerShell's Start-Process gh -ArgumentList 'pr','merge','5' (or -FilePath gh -Args ...): the program and its
    argument list judged as the command they make."""
    args, prog, rest, i = words[1:], None, [], 0
    while i < len(args):
        low = args[i].lower()
        if low in ("-filepath", "-file", "-path") and i + 1 < len(args):
            prog, i = args[i + 1], i + 2
        elif low in ("-argumentlist", "-args", "-arguments") and i + 1 < len(args):
            j = i + 1
            while j < len(args) and not args[j].startswith("-"):
                rest += [a for a in re.split(r"[,\s]+", args[j]) if a]
                j += 1
            i = j
        elif low.startswith("-"):
            i += 2 if low in ("-workingdirectory", "-verb", "-windowstyle", "-redirectstandardoutput",
                              "-redirectstandarderror", "-redirectstandardinput", "-credential") else 1
        elif prog is None:
            prog, i = args[i], i + 1
        else:
            rest += [a for a in re.split(r"[,\s]+", args[i]) if a]  # positional: the argument list
            i += 1
    return _judge(shlex.join([prog] + rest), ctx, depth + 1) if prog else None


def _program(word: str, ctx: _Ctx, depth: int) -> str | None:
    """A program named by its path (./deploy.sh): an executable script is judged by its contents, and one this same
    call writes first (`printf ... > x.sh && ./x.sh`) by scanning the call. A plain file that is not executable, such
    as a path at the start of a line of commit message text, is not a program."""
    path = _path(word, ctx.cwd)
    if os.path.isfile(path):
        return _script(word, ctx, depth, None) if WINDOWS or os.access(path, os.X_OK) else None
    name = re.escape(re.split(r"[\\/]", word)[-1])
    if name and re.search(rf"(?:>|\btee\b[^|;&\n]*?|\b(?:cp|mv|install|ln)\b[^|;&\n]*?)\s*['\"]?[^\s'\"|;&]*{name}\b",
                          ctx.full):
        return _scan_full(ctx)
    return None


def _shell(words: list[str], ctx: _Ctx, depth: int) -> str | None:
    args = _positional(words[1:])
    i = 0
    while i < len(args):
        a = args[i]
        if re.match(r"^-[A-Za-z]*c[A-Za-z]*$", a):
            return _judge(args[i + 1], ctx, depth + 1) if i + 1 < len(args) else None
        if a in ("--rcfile", "--init-file") or re.match(r"^[-+][A-Za-z]*[oO]$", a):
            i += 2
            continue
        if a.startswith(("-", "+")) and a not in ("-", "--"):
            if "s" in a.lstrip("-+"):
                break  # -s: the script comes from stdin
            i += 1
            continue
        if a == "--":
            i += 1
            continue
        return _script(a, ctx, depth, "shell") if a != "-" else _stdin(ctx, depth, "shell")
    return _stdin(ctx, depth, "shell")


def _stdin(ctx: _Ctx, depth: int, kind: str) -> str | None:
    """A shell or interpreter reading its program from stdin: a heredoc body is judged as that program; anything else
    (a pipe, a here-string) by scanning the whole call."""
    body = ctx.stdin
    if body is not None and kind == "shell":
        return _judge(body, ctx, depth + 1) or _scan(body, ctx)
    return _scan(body if body is not None else ctx.full, ctx)


def _interpreter(prog: str, words: list[str], ctx: _Ctx, depth: int) -> str | None:
    """python -c, node -e, perl -e, pwsh -Command, a script file, or code on stdin: scanned for the guarded commands
    and endpoints it names."""
    args = _positional(words[1:])
    if prog.startswith("py"):
        def code_flag(a: str) -> bool:
            return bool(re.match(r"^-[A-Za-z]*c$", a))
    elif prog in ("perl", "ruby", "lua", "rscript", "osascript"):
        def code_flag(a: str) -> bool:
            return bool(re.match(r"^-[A-Za-z]*[eE]$", a))
    elif prog == "php":
        def code_flag(a: str) -> bool:
            return a == "-r"
    else:  # node, deno, bun
        def code_flag(a: str) -> bool:
            return a in ("-e", "--eval", "-p", "--print", "-pe")
    i = 0
    while i < len(args):
        a = args[i]
        low = a.lower()
        if prog in ("pwsh", "powershell"):
            if low in ("-command", "-c", "-commandwithargs", "-cwa"):
                return _scan(" ".join(args[i + 1:]), ctx)
            if low in ("-encodedcommand", "-enc", "-e", "-ec") and i + 1 < len(args):
                try:
                    code = base64.b64decode(args[i + 1]).decode("utf-16-le", errors="replace")
                except ValueError:
                    return "an encoded PowerShell command cannot be checked: run the command itself"
                return _scan(code, ctx)
            if low in ("-file", "-f") and i + 1 < len(args):
                return _script(args[i + 1], ctx, depth, "code")
            if a.startswith("-"):
                i += 1
                continue
            return _scan(" ".join(args[i:]), ctx)  # pwsh's bare words are a command
        if prog in ("awk", "gawk"):
            return _scan(" ".join(args), ctx)  # system("gh pr merge 5")
        if prog.startswith("py") and re.match(r"^-[A-Za-z]*m", a):
            return None  # python -m pytest: a module; what it runs is not in the call
        if code_flag(a):
            return _scan(args[i + 1], ctx) if i + 1 < len(args) else None
        if a in ("-W", "-X", "-r", "--require", "--import", "--loader") and prog != "php":
            i += 2
            continue
        if a.startswith("-") and a != "-":
            i += 1
            continue
        if prog in ("deno", "bun") and a in ("run", "x"):
            i += 1
            continue
        if prog == "deno" and a == "eval":
            return _scan(" ".join(args[i + 1:]), ctx)
        if a == "-":
            break
        return _script(a, ctx, depth, "code")
    return _stdin(ctx, depth, "code")


def _script(path: str, ctx: _Ctx, depth: int, kind: str | None) -> str | None:
    """A script file the call runs, judged by its contents: shell scripts command by command, other code scanned. A
    script the hook cannot read (written by this same call, say) is judged by scanning the whole call. A file is
    judged once for each state of the call (directory, variables, aliases) it runs in: running it again costs nothing."""
    key = (os.path.realpath(_path(path, ctx.cwd)), kind, ctx.cwd, ctx.stdin,
           *(tuple(sorted(d.items())) for d in (ctx.vars, ctx.ps_vars, ctx.aliases, ctx.git_aliases)))
    scripts = _CALL["scripts"]  # the same file judged in the same state gets the same verdict
    if key not in scripts:
        scripts[key] = _script_verdict(path, ctx, depth, kind)
    return scripts[key]


def _script_verdict(path: str, ctx: _Ctx, depth: int, kind: str | None) -> str | None:
    try:
        with open(_path(path, ctx.cwd), "rb") as fh:
            data = fh.read(MAX_SCRIPT)
    except OSError:
        return _scan_full(ctx)
    if b"\x00" in data[:4096]:
        return None  # a binary: not a script
    text = _text(data)
    first = text.split("\n", 1)[0]
    if kind is None:
        shebang = first.startswith("#!")
        kind = "shell" if (path.endswith((".sh", ".bash", ".zsh")) and not shebang) or \
            (shebang and re.search(r"\b(?:ba|z|k|da|a|mk)?sh\b", first)) else "code"
    if kind == "shell":
        return _judge(text, ctx, depth + 1) or _scan(text, ctx)
    return _scan(text, ctx)


def _xargs(words: list[str], ctx: _Ctx, depth: int) -> str | None:
    args, i = words[1:], 0
    while i < len(args) and args[i].startswith("-"):
        a = args[i]
        i += 2 if a in ("-I", "-n", "-P", "-L", "-d", "-E", "-s", "-a", "--arg-file", "--delimiter", "--max-args",
                        "--max-procs", "--max-lines", "--eof", "--max-chars", "--replace") else 1
    return _hidden_args(args[i:] or ["echo"], ctx, depth, "xargs")


def _find(words: list[str], ctx: _Ctx, depth: int) -> str | None:
    i = 0
    while i < len(words):
        if words[i] in ("-exec", "-execdir", "-ok", "-okdir"):
            j = i + 1
            while j < len(words) and words[j] not in (";", "\\;", "+"):
                j += 1
            reason = _hidden_args(words[i + 1:j], ctx, depth, "find -exec")
            if reason:
                return reason
            i = j
        i += 1
    return None


def _hidden_args(inner: list[str], ctx: _Ctx, depth: int, how: str) -> str | None:
    """A command that another program runs with arguments it adds (xargs, find -exec): judged as written, and refused
    when it is a guarded command, since the arguments that decide it are not in the call."""
    reason = _judge(shlex.join(inner), ctx, depth + 1)
    if reason:
        return reason
    run = _unwrap(list(inner))
    if not run:
        return None
    sub, _, _ = _git_subcommand(run)
    gh = _gh_args(run) if _prog(run[0]) == "gh" else []
    if sub in ("push", "commit") or gh[:1] in (["api"], ["alias"]) or \
            gh[:2] in (["pr", "merge"], ["pr", "create"], ["pr", "review"]):
        return f"{how} adds arguments the hook cannot see to `{' '.join(run[:3])}`: run the command itself"
    return None


def _wrapped(prog: str, words: list[str], ctx: _Ctx, depth: int) -> str | None:
    """watch 'cmd', su -c 'cmd', script -c 'cmd': the command is a shell string."""
    args = words[1:]
    code = _flag(args, "-c", "--command")
    if code is not None:
        return _judge(code, ctx, depth + 1)
    if prog == "watch":
        i = 0
        while i < len(args) and args[i].startswith("-"):
            i += 2 if args[i] in ("-n", "--interval", "-d", "-q") and not args[i].startswith("--differences") else 1
        return _judge(" ".join(args[i:]), ctx, depth + 1)
    return None


def _scan_full(ctx: _Ctx) -> str | None:
    """_scan of the whole call, worked out once per call, so many commands that read hidden code stay linear."""
    if not ctx.scanned:
        ctx.scanned.append(_scan(ctx.full, ctx))
    return ctx.scanned[0]


def _scan(text: str, ctx: _Ctx) -> str | None:
    """Code the hook cannot parse as shell (python -c, a script file, stdin) scanned for what it would run: a git or gh
    command written as words or a list (`["gh", "pr", "merge", n]`), an HTTP write to Jira or Confluence, and GitHub's
    merge and approve endpoints and mutations."""
    _in_time()
    text = _canon(text)
    for line in re.split(r"[\r\n;]+", text):
        toks = re.findall(r"[^\s'\"`,\[\](){}]+", line)
        for i, t in enumerate(toks):
            p = _prog(t)
            if p in ("git", "gh"):
                _in_time()
                reason = _command(toks[i:i + 16], ctx, scan=True)
            elif p in HTTP_CLIENTS:
                reason = _http(toks[i:i + 40])
            else:
                continue
            if reason:
                return reason
    if MERGE_RULE != "allowed":
        if GH_MUTATIONS.search(text) or any(_after(t, "pulls/", MERGE_TAIL, 6) for t in _runs(text)):
            return NEVER_MERGE
        if re.search(r"(?i)PullRequestReview", text) and re.search(r"\bAPPROVE\b", text):
            return NEVER_APPROVE
    if any(_after(t.lower(), "http", ATLASSIAN_HOST, 0, r"https?://") for t in _runs(text)) and \
            (re.search(r"(?i)/transitions\b", text) or
             re.search(r"(?i)\b(?:post|put|patch|delete)\b|method\s*[=:]|--data|--json|\bdata\s*=|\bjson\s*=", text)):
        return ("this code writes to Jira or Confluence over HTTP, past the tracker and wiki rules: use the tracker "
                "MCP tools, or ask a person")
    return None


MERGE_TAIL = re.compile(r"/merge\b")
ATLASSIAN_HOST = re.compile(r"atlassian\.net|jira|confluence")


def _runs(text: str):
    """The runs of text between whitespace and quotes, which a URL or an API path can't cross."""
    return (m.group(0) for m in re.finditer(r"[^\s'\"]+", text))


def _after(word: str, start: str, tail: re.Pattern, gap: int, head: str | None = None) -> bool:
    """Whether `tail` occurs in `word` at or after `gap` characters past the first `start` (that also matches `head`
    there). Linear: a regex like `pulls/[^\\s]*/merge` restarts at every `pulls/` and is quadratic on a long word,
    which could hold the hook past its timeout."""
    i = word.find(start)
    while i >= 0 and head and not re.match(head, word[i:i + 8]):
        i = word.find(start, i + 1)
    return i >= 0 and tail.search(word, i + gap) is not None


def _approves(payload: str) -> bool:
    """GH_APPROVE without its quadratic `[\\s\\S]*`: APPROVE after the first addPullRequestReview or
    submitPullRequestReview, or an `event: APPROVE` field."""
    m = GH_REVIEW_MUTATION.search(payload)
    return bool(m and APPROVE_WORD.search(payload, m.end())) or bool(GH_APPROVE_EVENT.search(payload))


def _http(words: list[str], stdin: str = "") -> str | None:
    """curl, wget, httpie or Invoke-RestMethod: a write to Jira or Confluence, or a GitHub merge, approve or dismiss."""
    curl = _prog(words[0]) == "curl"
    method, data, urls = None, [], []
    i = 1
    while i < len(words):
        w, low = words[i], words[i].lower()
        nxt = words[i + 1] if i + 1 < len(words) else ""
        if w == "-X" or low in ("--request", "--method", "-method"):
            method, i = nxt.upper(), i + 2
            continue
        if curl and re.match(r"^-[A-Za-z]*X.+$", w):
            method = w.split("X", 1)[1].upper()
        elif low.startswith(("--request=", "--method=")):
            method = w.split("=", 1)[1].upper()
        elif w in ("-d", "-F", "-T") or low in ("--data", "--data-raw", "--data-binary", "--data-urlencode", "--json",
                                                 "--form", "--upload-file", "--post-data", "--post-file", "--body-data",
                                                 "--body-file", "-body", "-infile", "--raw"):
            data.append(nxt)
            i += 2
            continue
        elif low.startswith(("--data", "--json", "--form", "--post-", "--body-", "--upload-file=")) or \
                (curl and re.match(r"^-[A-Za-z]{1,5}$", w) and re.search(r"[dFT]", w)):
            data.append(w.split("=", 1)[1] if "=" in w else nxt)
        elif re.match(r"^(?:GET|HEAD|OPTIONS|POST|PUT|PATCH|DELETE)$", w):
            method = w
        elif re.match(r"(?i)^(?:https?://|[^/\s]*(?:atlassian\.net|github\.com)|/rest/|/wiki/)", w):
            urls.append(w)
        elif urls and not curl and re.match(r"^[A-Za-z0-9_.-]+(?::=|=|@)", w):
            data.append(w)  # httpie's field=value items make it a POST
        i += 1
    write = (method or ("POST" if data else "GET")) not in ("GET", "HEAD", "OPTIONS")
    if any(d in ("-", "@-") for d in data):
        data.append(stdin)  # --data-binary @-: the body is piped in, so the whole call is the payload
    payload = _canon(" ".join(data))
    for url in urls:
        path = re.sub(r"^[a-z]+://[^/]*", "", url, flags=re.I).split("?")[0]
        if MERGE_RULE != "allowed" and "github" in url.lower():
            if GH_API_MERGE.search(path) or GH_MUTATIONS.search(payload):
                return NEVER_MERGE
            if GH_DISMISS.search(path) or (path.rstrip("/").endswith("/reviews") and _approves(payload)):
                return NEVER_APPROVE
        if ATLASSIAN_URL.search(url) and write:
            return ("a write to Jira or Confluence over HTTP skips the tracker and wiki rules: use the tracker MCP "
                    "tools, or ask a person")
    return None


def _atlassian_cli(words: list[str]) -> str | None:
    """acli and jira-cli: transitions, deletes, execution labels and wiki writes, as on the MCP servers."""
    toks = [_canon(w).lower() for w in words[1:]]
    flat = set(re.findall(r"[a-z]+", " ".join(toks)))
    if (TRANSITION | DESTRUCTIVE) & flat:
        return "agents don't move or delete tickets from the Jira command line: comment instead, or ask a person"
    if re.search(EXEC, " ".join(toks)):
        return "only a person sets or changes an execution label (exec:agent)"
    if "confluence" in flat and (WRITE & flat):
        return "sessions don't write the wiki: propose a knowledge record and the render job publishes it"
    return None


def _gh_args(words: list[str]) -> list[str]:
    """A gh command's arguments with the repository flag (-R/--repo, anywhere) taken out: `gh -R o/r pr merge 5`
    reads as `pr merge 5`."""
    out, i = [], 1
    while i < len(words):
        w = words[i]
        if w in ("-R", "--repo", "--hostname"):
            i += 2
            continue
        if w.startswith(("--repo=", "-R=")) or (w.startswith("-R") and len(w) > 2 and not w.startswith("--")):
            i += 1
            continue
        out.append(w)
        i += 1
    return out


def _gh_aliases() -> dict[str, str]:
    """gh's own aliases (`gh alias set m 'pr merge'`), from its config file; empty when there is none."""
    base = os.environ.get("GH_CONFIG_DIR") or os.path.join(
        os.environ.get("XDG_CONFIG_HOME") or (os.environ.get("AppData") if WINDOWS else "") or
        os.path.join(os.path.expanduser("~"), ".config"), "GitHub CLI" if WINDOWS and not
        os.environ.get("XDG_CONFIG_HOME") else "gh")
    try:
        with open(os.path.join(base, "config.yml"), "rb") as fh:
            text = _text(fh.read(MAX_SCRIPT))
    except OSError:
        return {}
    out, inside = {}, False
    for line in text.splitlines():
        if re.match(r"^aliases:\s*$", line):
            inside = True
            continue
        if inside and line and not line[0].isspace():
            break
        m = re.match(r"^\s+([^:#\s]+):\s*(.*)$", line) if inside else None
        if m:
            out[m.group(1).strip("'\"")] = m.group(2).strip().strip("'\"")
    return out


def _git_alias(name: str, ctx: _Ctx, git_c: str | None) -> str | None:
    if name in ctx.git_aliases:
        return ctx.git_aliases[name]
    if name in GIT_BUILTINS or not re.match(r"^[A-Za-z0-9][A-Za-z0-9_-]*$", name):
        return None
    where = _path(git_c, ctx.cwd) if git_c else (ctx.cwd or ".")
    try:
        r = subprocess.run(["git", "-C", where, "config", "--get", f"alias.{name}"], capture_output=True,
                           encoding="utf-8", errors="replace", timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.strip() if r.returncode == 0 and r.stdout.strip() else None


def _command(words: list[str], ctx: _Ctx, scan: bool = False, hops: int = 0) -> str | None:
    """The verdict for one git or gh command. `scan`: the words were found in code, so only what is never right
    (a merge, an approval, a push to main or a force push) is judged, not the PR contract or the commit branch."""
    prog = _prog(words[0]) if words else ""
    if prog == "git":
        for i, w in enumerate(words[:-1]):  # git -c alias.p='push --force' p
            m = re.match(r"^alias\.([^=]+)=(.*)$", words[i + 1], re.S) if w == "-c" else None
            if m:
                ctx.git_aliases[m.group(1)] = m.group(2)
    sub, git_c, rest = _git_subcommand(words)
    if sub == "config":
        m = next((re.match(r"^alias\.(.+)$", w) for w in rest if w.startswith("alias.")), None)
        value = rest[rest.index(m.group(0)) + 1] if m and rest.index(m.group(0)) + 1 < len(rest) else None
        if m and value is not None:
            ctx.git_aliases[m.group(1)] = value
            return _alias_value("git", value, [], ctx, scan, hops)
        return None
    if sub and hops < 3:
        value = _git_alias(sub, ctx, git_c)
        if value is not None:
            return _alias_value("git", value, rest, ctx, scan, hops)
    if sub == "commit" and not scan:
        return _commit(ctx.cwd, git_c)
    if sub == "push":
        return _push(rest)
    if prog != "gh":
        return None
    args = _gh_args(words)
    if args[:1] == ["alias"] and args[1:2] == ["set"] and len(args) > 3:
        return _alias_value("gh", args[3], [], ctx, scan, hops, shell="--shell" in args or "-s" in args)
    if args[:1] == ["alias"] and args[1:2] == ["import"]:
        return _script(args[2], ctx, 0, "code") if len(args) > 2 and args[2] != "-" else _scan_full(ctx)
    if args and args[0] not in GH_BUILTINS and hops < 3:
        value = _gh_aliases().get(args[0])
        if value is not None:
            return _alias_value("gh", value, args[1:], ctx, scan, hops)
    if args[:2] == ["pr", "create"] and not scan:
        return _pr_create(args[2:], ctx.cwd)
    if args[:2] == ["pr", "merge"]:
        return _pr_merge(args[2:])
    if args[:2] == ["pr", "review"] and MERGE_RULE != "allowed" and \
            any(w in ("--approve", "-a") or re.match(r"^-[A-Za-z]*a[A-Za-z]*$", w) for w in args[2:]):
        return NEVER_APPROVE
    if args[:1] == ["api"]:
        return _gh_api(args[1:], ctx)
    return None


def _alias_value(prog: str, value: str, rest: list[str], ctx: _Ctx, scan: bool, hops: int,
                 shell: bool = False) -> str | None:
    """A git or gh alias, judged as what it runs: `!...` (or gh --shell) is a shell line, anything else a subcommand."""
    if value.startswith("!") or shell:
        return _judge(value.lstrip("!") + " " + shlex.join(rest), ctx, 1)
    return _command([prog] + _words(value) + rest, ctx, scan, hops + 1)


def _gh_api(args: list[str], ctx: _Ctx) -> str | None:
    """gh api: the REST merge, dismissal and approving-review endpoints and the GraphQL merge, auto-merge and approve
    mutations, by the merge rule; --admin never matters here."""
    if MERGE_RULE == "allowed":
        return None
    fields = []
    for i, w in enumerate(args):
        if w in ("-f", "-F", "--field", "--raw-field", "--input") and i + 1 < len(args):
            value = args[i + 1]
            if w == "--input" or "=@" in value:
                path = value.split("=@", 1)[1] if "=@" in value else value
                if path == "-":
                    value += " " + ctx.full  # --input - or query=@-: the query is piped in from this call
                else:
                    try:
                        with open(_path(path, ctx.cwd), "rb") as fh:
                            value += " " + _text(fh.read(MAX_SCRIPT))
                    except OSError:
                        pass
            fields.append(value)
        elif w.startswith(("--field=", "--raw-field=")):
            fields.append(w.split("=", 1)[1])
    payload = _canon(" ".join(fields + args))
    endpoints = [w for w in args if not w.startswith("-") and w not in fields]
    if any(GH_API_MERGE.search(w) for w in endpoints) or GH_MUTATIONS.search(payload):
        return NEVER_MERGE
    if any(GH_DISMISS.search(w) for w in endpoints) or _approves(payload):
        return NEVER_APPROVE
    return None


def main() -> int:
    try:
        return _main()
    except Exception as e:  # noqa: BLE001 - a hook that crashes exits 1, which lets the call through: fail closed
        return _block(f"the hook failed ({type(e).__name__}), so the call cannot be checked")


def _main() -> int:
    try:
        # bytes, not sys.stdin: on Windows its text layer decodes with the console code page, not UTF-8
        data = sys.stdin.buffer.read()
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return _block("the tool call is not valid UTF-8, so it cannot be checked")  # fail closed
    except (OSError, AttributeError, ValueError):  # AttributeError: no stdin at all; ValueError: it is closed
        return _block("the tool call could not be read, so it cannot be checked")  # fail closed
    try:
        event = json.loads(text)
    except ValueError:
        return _block("the tool call is not valid JSON, so it cannot be checked")  # fail closed
    if not isinstance(event, dict):
        return _block("the tool call is not a JSON object, so it cannot be checked")  # fail closed
    reason = why(event)
    return _block(reason) if reason else 0


def _block(reason: str) -> int:
    # Exit 2 with the reason on stderr is the verdict: Claude Code blocks the call and shows the agent the reason.
    # PowerShell's -Command turns a native exit 2 into 1, so the installer's Windows hook commands end in
    # `exit $LASTEXITCODE` to keep the 2. The same reason also goes to stdout as a PreToolUse deny, which Claude Code
    # reads alongside exit 2. Where a shell turns the 2 into 1 anyway, valid JSON decides the call, except on Windows
    # without Git Bash, where any code but 0 or 2 is a hook failure. If something else writes to stdout (a shell
    # profile) the JSON is not read, and the non-zero exit still blocks.
    message = f"blocked by the work-system hook: {reason}."
    deny = {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                   "permissionDecisionReason": message}}
    try:
        sys.stdout.flush()
        sys.stdout.buffer.write(json.dumps(deny, ensure_ascii=True).encode("ascii") + b"\n")
        sys.stdout.buffer.flush()
    except (OSError, ValueError):
        pass  # the exit code below still blocks
    sys.stderr.flush()
    sys.stderr.buffer.write((message + "\n").encode("utf-8"))
    sys.stderr.buffer.flush()
    return 2


if __name__ == "__main__":
    sys.exit(main())
