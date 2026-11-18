#!/usr/bin/env python3
"""Can this laptop run a harness end to end? One readable preflight for a fresh work laptop or a new teammate.

    python scripts/doctor.py harnesses/work-default --scope project --target ~/src/svc
    python scripts/doctor.py harnesses/work-default --json            # for hangar's preflight and flightdeck
    python scripts/doctor.py harnesses/work-default --live            # also one model call and one tools/list each

`install_local.py --check` says whether the installed files still match the manifest. This says whether the rest of
the machine is ready: Claude Code at the lock's version, the interpreter the hooks run with, the lock's MCP servers
added and answering, `gh` signed in with repo scope, the company's org overlay applied, the installed lock on its
channel, the guide imported, the repository's own test and check commands allowed, and trace capture for flightdeck.

Each check prints one line, `ok`, `fix` or `skip`, and every `fix` carries the exact command or edit that fixes it.
It reads and runs read-only commands only: it installs, adds, signs in and writes nothing. No credential value is
printed: a credential variable is reported as set or unset, and `--live` sends it only to the server it is for.
`--live` is the exception to writing nothing: its one `claude -p` call is a real session, so it writes a transcript
and runs the harness's session hooks.

Without `--scope` it looks for an install in `<target>/.claude` (project scope), then `<home>/.claude` (user scope).
`--skip ID` leaves a check out (`--skip capture` on a laptop without flightdeck); skipped checks still print.
`--test-cmd CMD` (repeatable) names a command that must be allowed; the target's `ai-dlc.toml` `[checks.commands]`
are read too. Windows: runs natively under PowerShell or cmd (`py -3 scripts\\doctor.py ...`); the hook interpreter
there is `py -3`.

Exit codes: 0 nothing to fix, 1 something to fix, 2 bad input. Needs Python 3.10+ and PyYAML.
"""

from __future__ import annotations

import argparse
import http.client
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import install_local as il  # noqa: E402

SCHEMA = "team-harness.doctor/v1"
OK, FIX, SKIP = "ok", "fix", "skip"
WINDOWS = il.WINDOWS
# What the public example org leaves in a work harness until a company's overlay replaces it (orgs/README.md).
ORG_PLACEHOLDERS = ("COMPANY-SITE", "COMPANY-SPACE", "COMPANY-ORG", "WORKPROJ", "SREPROJ", "SECPROJ", "ESSPROJ",
                    "ARCHPROJ", "CHGPROJ", "The org overlay is not applied")
# `claude mcp list`: `name: <url or command> (HTTP) - ✓ Connected` (or `× Failed to connect — why`, `! Needs ...`)
MCP_LINE = re.compile(r"^(?P<name>[^\s:][^:]*): (?P<target>.*?)(?: \((?P<kind>HTTP|SSE|stdio)\))? - (?P<status>.+)$")
VERSION = re.compile(r"(\d+)\.(\d+)\.(\d+)")
TOML_LINE = re.compile(r'^[\w.-]+\s*=\s*"((?:[^"\\]|\\.)*)"\s*(#.*)?$')  # `name = "command"`, for Python 3.10
OPERATORS = {"&&", "||", ";", "|", "&", ";;", "|&"}  # a compound command's parts are each allowed on their own
# Where an admin's managed settings live (they override every other settings file).
MANAGED_SETTINGS = {
    "darwin": Path("/Library/Application Support/ClaudeCode/managed-settings.json"),
    "win32": Path(r"C:\Program Files\ClaudeCode\managed-settings.json"),
}.get(sys.platform, Path("/etc/claude-code/managed-settings.json"))

Runner = Callable[..., "tuple[int | None, str]"]  # (argv, timeout, cwd=None) -> (exit code or None, output)


@dataclass
class Check:
    id: str
    status: str
    summary: str
    fix: str = ""


def run_cmd(argv: list[str], timeout: float = 60, cwd: Path | None = None) -> tuple[int | None, str]:
    """(exit code, stdout and stderr), or (None, why) when the program can't start. A Windows `claude.cmd` is found
    through PATHEXT, which subprocess alone doesn't do. `cwd` matters for `claude`: project-scope servers in
    `.mcp.json` are listed only from inside the project."""
    exe = shutil.which(argv[0]) or argv[0]
    try:
        r = subprocess.run([exe, *argv[1:]], capture_output=True, text=True, timeout=timeout, check=False,  # noqa: S603
                           encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL,
                           cwd=str(cwd) if cwd else None)
    except FileNotFoundError:
        return None, f"{argv[0]} not found on PATH"
    except subprocess.TimeoutExpired:
        return None, f"{argv[0]} timed out after {timeout:.0f}s"
    except OSError as e:
        return None, f"{argv[0]}: {e.strerror or e}"
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def _ver(text: str) -> tuple[int, ...] | None:
    m = VERSION.search(text or "")
    return tuple(int(x) for x in m.groups()) if m else None


@dataclass
class Ctx:
    harness: Path  # harnesses/<name> in the team-harness checkout
    lock: dict[str, Any]
    scope: str | None
    base: Path | None  # the .claude directory the harness is installed in, when it is
    home: Path
    target: Path
    manifest: dict[str, Any] | None
    run: Runner
    env: dict[str, str]
    live: bool = False
    exact_runtime: bool = False
    github_host: str = "github.com"
    test_cmds: tuple[str, ...] = ()
    managed: Path = MANAGED_SETTINGS
    hook_problems: list[str] | None = None  # what the install check's probe found, so hooks are probed once

    @property
    def py(self) -> str:
        return "py -3" if WINDOWS else "python3"

    def script(self, name: str) -> str:
        """The command that runs one of team-harness's scripts from anywhere (the doctor runs in the project)."""
        return f"{self.py} {_q(self.repo / 'scripts' / name)}"

    @property
    def repo(self) -> Path:
        return self.harness.parent.parent

    @property
    def name(self) -> str:
        return str(self.lock["name"])

    def install_cmd(self, harness: str | None = None, scope: str | None = None, action: str = "--apply") -> str:
        scope = scope or self.scope or "project"
        where = f" --target {_q(self.target)}" if scope == "project" else ""
        return (f"{self.script('install_local.py')} {_q(self.repo / 'harnesses' / (harness or self.name))} "
                f"--scope {scope}{where} {action}")


def _q(p: Path | str) -> str:
    return subprocess.list2cmdline([str(p)]) if WINDOWS else shlex.quote(str(p))


def _not_installed(c: Ctx, check_id: str) -> Check:
    return Check(check_id, SKIP, f"{c.name} is not installed yet (the install line says how)")


# --- the checks, in the order they print --------------------------------------------------------------------------

def check_claude(c: Ctx) -> list[Check]:
    want = str((c.lock.get("runtime") or {}).get("version") or "")
    rc, out = c.run(["claude", "--version"], 30)
    pin = f"claude install {want}" if want else "claude update"
    if rc != 0:
        return [Check("claude", FIX, f"Claude Code doesn't run ({out.strip()[:120] or f'exit {rc}'})",
                      "install Claude Code (https://docs.anthropic.com/en/docs/claude-code/setup), then " + pin)]
    have, need = _ver(out), _ver(want)
    if not need:
        return [Check("claude", OK, f"Claude Code {out.strip()}; the lock pins no version")]
    if have == need:
        return [Check("claude", OK, f"Claude Code {want}, the lock's version")]
    if have and have > need and not c.exact_runtime:
        return [Check("claude", OK, f"Claude Code {'.'.join(map(str, have))}, newer than the lock's {want} "
                                    f"(the harness was tested on {want}; `{pin}` pins it)")]
    got = ".".join(map(str, have)) if have else out.strip()[:40]
    return [Check("claude", FIX, f"Claude Code {got}, the lock pins {want}", pin)]


def check_model(c: Ctx) -> list[Check]:
    model = str((c.lock.get("model") or {}).get("id") or "")
    if not model:
        return [Check("model", SKIP, "the lock names no model")]
    if not c.live:
        return [Check("model", SKIP, f"the lock's model is {model}; not asked (one model call)", "rerun with --live")]
    rc, out = c.run(["claude", "-p", "--model", model, "--max-turns", "1", "Reply with the single word: ok"], 180,
                    cwd=c.target)
    if rc == 0:
        return [Check("model", OK, f"{model} answered")]
    return [Check("model", FIX, f"{model} did not answer ({out.strip()[:160] or f'exit {rc}'})",
                  f"sign in (`claude` then /login) with an account that has {model}, or ask your admin to enable it")]


def check_python(c: Ctx) -> list[Check]:
    interp = ["py", "-3"] if WINDOWS else ["python3"]
    name = " ".join(interp)
    rc, out = c.run([*interp, "-c", "import sys; print('%d.%d' % sys.version_info[:2]); import yaml; print('yaml')"],
                    30)
    if rc is None:
        how = "install Python 3.10+ from python.org (it adds the py launcher)" if WINDOWS else \
            "install Python 3.10+ so that `python3` is on PATH (macOS: brew install python)"
        return [Check("python", FIX, f"`{name}` doesn't start, so every hook is off ({out})", how),
                Check("pyyaml", SKIP, f"needs `{name}` first")]
    m = re.search(r"^(\d+)\.(\d+)$", out, re.M)
    have = (int(m[1]), int(m[2])) if m else (0, 0)
    py = Check("python", OK, f"`{name}` is Python {'.'.join(map(str, have[:2]))} (the hooks run with it)") \
        if have[:2] >= (3, 10) else \
        Check("python", FIX, f"`{name}` is Python {'.'.join(map(str, have[:2]))}; the hooks and scripts need 3.10+",
              "install Python 3.10+ and put it first on PATH")
    yml = Check("pyyaml", OK, "PyYAML imports") if "yaml" in out.split() else \
        Check("pyyaml", FIX, f"PyYAML is missing under `{name}`", f"{name} -m pip install --user pyyaml")
    return [py, yml]


def check_install(c: Ctx) -> list[Check]:
    if not c.manifest:
        where = f"{c.target / '.claude'} or {c.home / '.claude'}"
        return [Check("install", FIX, f"no team-harness install in {where}", c.install_cmd())]
    if c.manifest.get("harness") != c.name:
        return [Check("install", FIX, f"{c.base} has {c.manifest.get('harness')} installed, not {c.name}",
                      f"{c.install_cmd(str(c.manifest.get('harness')), action='--uninstall')}, then "
                      + c.install_cmd())]
    hook_msgs = ("hook did not run", "guard's block", "hook sees no")
    found = il.check(None, None, None, c.base)
    c.hook_problems = [d for d in found if d.startswith(hook_msgs)]
    drift = [d for d in found if not d.startswith(hook_msgs)]
    if drift:
        return [Check("install", FIX, f"the install drifted: {'; '.join(drift[:3])}"
                                      + (f" (+{len(drift) - 3} more)" if len(drift) > 3 else ""), c.install_cmd())]
    return [Check("install", OK, f"{c.name} r{c.manifest.get('revision')} installed in {c.base}, files unchanged")]


def check_hooks(c: Ctx) -> list[Check]:
    if not c.manifest:
        return [_not_installed(c, "hooks")]
    entries = []
    for name, sec in il.SECTION.items():
        s = il._read_settings(c.base, name) or {}
        entries += [r for r in (c.manifest.get(sec) or {}).get("entries") or [] if il._has(s, il._unrecord(r))]
    hooks = [r for r in entries if r.get("section") == "hooks"]
    if not hooks:
        return [Check("hooks", SKIP, "the harness installs no hooks")]
    dead = c.hook_problems if c.hook_problems is not None else il.probe_hooks(c.base, c.scope or "user", entries)
    if dead:
        return [Check("hooks", FIX, "; ".join(dead[:2]),
                      "fix the interpreter (the python check above) or the hook path, then " + c.install_cmd())]
    return [Check("hooks", OK, f"each installed hook runs, and each guard blocks with exit 2 ({len(hooks)} entries)")]


def check_channel(c: Ctx) -> list[Check]:
    if not c.manifest:
        return [_not_installed(c, "channel")]
    chan = c.manifest.get("channel") or "stable"
    if chan == "checkout":
        return [Check("channel", FIX, "installed from the checkout as it is, not from a channel",
                      c.install_cmd() + " --channel stable")]
    try:
        want = il.channel_digest(c.harness, c.name, chan)
    except il.Refused as e:
        return [Check("channel", FIX, str(e), "git pull in the team-harness checkout")]
    if want != c.manifest.get("harness_digest"):
        return [Check("channel", FIX, f"{c.name}@{chan} moved: r{c.manifest.get('revision')} installed, the channel "
                                      f"is {want[:19]}...", c.install_cmd() + f" --channel {chan}")]
    note = "" if chan == "stable" else " (not stable: a release candidate)"
    return [Check("channel", OK, f"the installed lock is {c.name}@{chan}'s digest{note}")]


def check_checkout(c: Ctx) -> list[Check]:
    paths = [f"harnesses/{c.name}", "channels.yaml", f"bindings/{c.name}.yaml"]
    rc, out = c.run(["git", "--no-optional-locks", "-C", str(c.repo), "status", "--porcelain", "--", *paths], 30)
    if rc is None or (rc != 0 and "not a git repository" in out):
        return [Check("checkout", SKIP, f"{c.repo} is not a git checkout")]
    if rc != 0:
        return [Check("checkout", SKIP, f"git status failed: {out.strip()[:120]}")]
    dirty = [ln[3:] for ln in out.splitlines() if ln.strip()]
    if dirty:
        return [Check("checkout", FIX, f"the team-harness checkout has local changes: {', '.join(dirty[:4])}",
                      f"git -C {_q(c.repo)} stash   (or commit them on a branch)")]
    return [Check("checkout", OK, f"the team-harness checkout is clean for {c.name}")]


def check_one_harness(c: Ctx) -> list[Check]:
    if not c.manifest:
        return [_not_installed(c, "one-harness")]
    other_scope = "user" if c.scope == "project" else "project"
    other = il.base_dir(other_scope, c.home, c.target)
    if other.resolve() == c.base.resolve():
        return [Check("one-harness", OK, "one install found")]
    try:
        m = il.read_manifest(other)
    except il.Refused as e:
        return [Check("one-harness", FIX, str(e), f"look at {other / il.MANIFEST}")]
    if m:
        h = m.get("harness")
        return [Check("one-harness", FIX, f"{h} is also installed in {other_scope} scope ({other}); its hooks and "
                                          f"rules mix with {c.name}'s",
                      c.install_cmd(str(h), other_scope, "--uninstall"))]
    return [Check("one-harness", OK, f"no other harness in {other_scope} scope")]


def check_guide(c: Ctx) -> list[Check]:
    if not c.manifest:
        return [_not_installed(c, "guide")]
    out = []
    gi = c.manifest.get("guide_import") or {}
    md = c.base / gi.get("file", "CLAUDE.md")
    if gi.get("line") and not il._imports(md, gi["line"]):
        out.append(Check("guide", FIX, f"{md} lacks {gi['line']}, so the harness guide isn't loaded",
                         f"add the line {gi['line']} to {md}, or " + c.install_cmd()))
    elif gi.get("line"):
        out.append(Check("guide", OK, f"{md.name} imports the guide ({gi['line']})"))
    else:
        out.append(Check("guide", SKIP, "the harness has no guide"))
    s = c.base / il.SETTINGS
    if s.is_symlink():
        real = s.resolve()
        how = (f"Remove-Item {_q(s)}; Copy-Item {_q(real)} {_q(s)}" if WINDOWS
               else f"rm {_q(s)} && cp {_q(real)} {_q(s)}")
        out.append(Check("settings", FIX, f"{s} is a symlink, so another tool can swap the deny rules and hooks",
                         f"replace it with a copy of its target: {how}"))
    else:
        out.append(Check("settings", OK, f"{s.name} is a real file" if s.exists() else f"no {s.name} yet"))
    return out


def _mcp_list(c: Ctx) -> tuple[dict[str, dict[str, str]] | None, str]:
    rc, out = c.run(["claude", "mcp", "list"], 120, cwd=c.target)
    if rc is None:
        return None, out
    servers = {}
    for line in out.splitlines():
        m = MCP_LINE.match(line.strip())
        if m:
            servers[m["name"].strip()] = {k: (m[k] or "").strip() for k in ("target", "kind", "status")}
    return servers, out


def _binding(c: Ctx) -> dict[str, Any]:
    f = c.repo / "bindings" / f"{c.name}.yaml"
    return (yaml.safe_load(f.read_text(encoding="utf-8")) or {}) if f.is_file() else {}


def _shown(target: str) -> str:
    """A server's URL or command as printed, with any query string cut (it may carry a token)."""
    return re.sub(r"\?\S*", "?…", target)


def _same_target(m: dict[str, Any], got: str) -> bool:
    if m.get("transport") in ("http", "sse"):
        return got.rstrip("/") == str(m.get("endpoint") or "").rstrip("/")
    want = " ".join([str(m.get("command") or ""), *map(str, m.get("args") or [])])
    return got.split() == want.split()


def check_mcp(c: Ctx) -> list[Check]:
    servers_wanted = (c.lock.get("binding") or {}).get("mcp") or []
    if not servers_wanted:
        return [Check("mcp", SKIP, "the lock binds no MCP server")]
    have, raw = _mcp_list(c)
    scope = c.scope or "project"
    adds = il.mcp_commands(SimpleNamespace(root=c.harness, name=c.name, lock=c.lock), scope)
    binding = _binding(c)
    out = []
    for i, m in enumerate(servers_wanted):
        name, cid = m["name"], f"mcp:{m['name']}"
        add = adds[i] if i < len(adds) else f"claude mcp add {name} ..."
        readd = f"claude mcp remove {name} --scope {scope}; then {add}"
        if have is None:
            out.append(Check(cid, SKIP, f"can't list MCP servers ({raw.strip()[:100]})", "fix the claude check first"))
            continue
        got = have.get(name)
        if not got:
            out.append(Check(cid, FIX, f"{name} is not added", add))
            continue
        want_kind = str(m.get("transport") or "stdio").lower()
        got_kind = (got["kind"] or "stdio").lower()
        if got_kind != want_kind:
            out.append(Check(cid, FIX, f"{name} is added over {got_kind}, the lock binds {want_kind}", readd))
            continue
        if not _same_target(m, got["target"]):
            want = m.get("endpoint") if want_kind in ("http", "sse") else \
                " ".join([str(m.get("command") or ""), *map(str, m.get("args") or [])])
            out.append(Check(cid, FIX, f"{name} points at {_shown(got['target'])}, the lock binds {want}", readd))
            continue
        variables = [il._var(name, h, binding) for h in m.get("header_names") or []] + list(m.get("env_names") or [])
        unset = [v for v in variables if not c.env.get(v)]
        status = got["status"]
        if "auth" in status.lower():
            out.append(Check(cid, FIX, f"{name} needs you to sign in",
                             f"in Claude Code, run /mcp, pick {name} and sign in (a remote server may use OAuth "
                             "rather than a header token)"))
        elif not re.match(r"^[✓✔]\s*Connected\b", status):
            why = re.sub(r"^\W+", "", status)[:140]
            hint = f"set {', '.join(unset)} from your secret manager and restart Claude Code" if unset and \
                scope == "project" else "check the credential and the network, then `claude mcp list` again"
            out.append(Check(cid, FIX, f"{name} doesn't answer ({why})", hint))
        elif c.live and want_kind == "http" and m.get("header_names"):
            var = il._var(name, m["header_names"][0], binding)
            if not c.env.get(var):
                out.append(Check(cid, SKIP, f"{name} connected; tools/list not sent ({var} is unset here, the server "
                                            "has its own copy)", f"set {var} in this shell to send it"))
            else:
                n, err = tools_list(m["endpoint"], m["header_names"][0], c.env[var])
                out.append(Check(cid, OK, f"{name} connected; tools/list returned {n} tools") if err is None else
                           Check(cid, FIX, f"{name} tools/list failed: {err}", f"check {var} (whole header value, such "
                                                                               "as `Bearer <token>`)"))
        else:
            vs = f"; {', '.join(variables)} {'set' if not unset else 'unset here'}" if variables else ""
            live = " (tools/list goes only to header-token HTTP servers)" if c.live else ""
            out.append(Check(cid, OK, f"{name} connected ({got_kind}){vs}{live}"))
    return out


def tools_list(endpoint: str, header: str, value: str, timeout: float = 30) -> tuple[int, str | None]:
    """One MCP streamable-HTTP handshake and tools/list. (tool count, None) or (0, why); the value is sent only to
    endpoint and never shown."""
    session: dict[str, str] = {"MCP-Protocol-Version": "2025-06-18"}

    def post(body: dict[str, Any]) -> Any:
        h = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream", header: value,
             **session}
        req = urllib.request.Request(endpoint, data=json.dumps(body).encode(), headers=h, method="POST")  # noqa: S310
        with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310
            if r.headers.get("Mcp-Session-Id"):
                session["Mcp-Session-Id"] = r.headers["Mcp-Session-Id"]
            text = r.read().decode("utf-8", "replace")
            if "text/event-stream" in (r.headers.get("Content-Type") or ""):
                data = [ln[5:].strip() for ln in text.splitlines() if ln.startswith("data:")]
                text = data[-1] if data else ""
            return json.loads(text) if text.strip() else None

    try:
        init = post({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                     "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                                "clientInfo": {"name": "team-harness-doctor", "version": "1"}}})
        if not isinstance(init, dict) or not isinstance(init.get("result"), dict):
            err = init.get("error") if isinstance(init, dict) else None
            why = err.get("message", "empty") if isinstance(err, dict) else "empty"
            return 0, f"initialize returned no result ({why})"
        if isinstance(init["result"].get("protocolVersion"), str):
            session["MCP-Protocol-Version"] = init["result"]["protocolVersion"]  # the version the server chose
        post({"jsonrpc": "2.0", "method": "notifications/initialized"})
        res = post({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    except urllib.error.HTTPError as e:
        return 0, f"HTTP {e.code}" + (" (the credential was refused)" if e.code in (401, 403) else "")
    except (urllib.error.URLError, OSError, ValueError, http.client.HTTPException) as e:
        return 0, str(getattr(e, "reason", e))[:120]
    tools = (res.get("result") or {}).get("tools") if isinstance(res, dict) else None
    if not isinstance(tools, list):
        return 0, "tools/list returned no tool list"
    return len(tools), None


def _gh_accounts(out: str) -> list[dict[str, Any]]:
    """`gh auth status` as one entry per signed-in account: login, active, scopes (None when not listed)."""
    accounts: list[dict[str, Any]] = []
    for line in out.splitlines():
        m = re.search(r"Logged in to \S+ (?:account|as) (\S+)", line)
        if m:
            accounts.append({"login": m[1], "active": None, "scopes": None})
        elif accounts and re.search(r"Active account:\s*(true|false)", line, re.I):
            accounts[-1]["active"] = "true" in line.lower()
        elif accounts and "scopes" in line.lower():
            accounts[-1]["scopes"] = set(re.findall(r"'([a-z:_]+)'", line))
    return accounts


def check_gh(c: Ctx) -> list[Check]:
    host = c.github_host
    rc, out = c.run(["gh", "auth", "status", "--hostname", host], 60)
    login = f"gh auth login --hostname {host} --scopes repo"
    if rc is None:
        return [Check("gh", FIX, f"the GitHub CLI doesn't run ({out})",
                      "install gh (https://cli.github.com, or your company's software portal), then " + login)]
    if rc != 0:
        return [Check("gh", FIX, f"gh is not signed in to {host}", login)]
    accounts = _gh_accounts(out)
    active = [a for a in accounts if a["active"]] or accounts[:1]
    if not active:
        return [Check("gh", SKIP, f"gh is signed in to {host}, but its account couldn't be read from `gh auth status`")]
    acct = active[0]
    scopes = acct["scopes"]
    if scopes is None:
        return [Check("gh", SKIP, f"gh is signed in to {host} as {acct['login']}; its token lists no scopes (a "
                                  "fine-grained or app token), so repo access isn't confirmed",
                      f"if pushes fail: {login}")]
    if "repo" not in scopes:
        return [Check("gh", FIX, f"gh is signed in to {host} as {acct['login']} without repo scope "
                                 f"({', '.join(sorted(scopes)) or 'no scopes'})",
                      f"gh auth refresh --hostname {host} --scopes repo")]
    return [Check("gh", OK, f"gh is signed in to {host} as {acct['login']} with repo scope")]


def _org_of(c: Ctx) -> tuple[str | None, dict | None]:
    """The org overlay targets.yaml gives this harness, and its org.yaml (None when unreadable)."""
    targets = c.repo / "shared" / "work-system" / "targets.yaml"
    if not targets.is_file():
        return None, None
    entry = ((yaml.safe_load(targets.read_text(encoding="utf-8")) or {}).get("harnesses") or {}).get(c.name) or {}
    rel = entry.get("org") if isinstance(entry, dict) else None
    if not rel:
        return None, None
    f = c.repo / rel / "org.yaml"
    return rel, (yaml.safe_load(f.read_text(encoding="utf-8")) if f.is_file() else None)


def check_org(c: Ctx) -> list[Check]:
    if not c.manifest:
        return [_not_installed(c, "org")]
    files = c.manifest.get("files") or {}
    rel, org = _org_of(c)
    if not rel and not any(r.startswith(("skills/release-approvals/", "skills/org-process/")) for r in files):
        return [Check("org", SKIP, f"{c.name} takes no org overlay")]
    found: set[str] = set()
    for f_rel in files:
        if not f_rel.startswith("skills/"):
            continue
        try:
            text = (c.base / f_rel).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        found |= {p for p in ORG_PLACEHOLDERS if p in text}
    fix = ("add your company's org in its private fork (orgs/README.md, 'Add your company's org'), point "
           f"{c.name} at it in shared/work-system/targets.yaml and merge; once main has built it, "
           f"{c.install_cmd()} --channel candidate (or stable, after a promotion)")
    if isinstance(org, dict) and org.get("placeholder") is True:
        return [Check("org", FIX, f"the company's org overlay is not applied: {c.name} uses {rel}, which is marked "
                                  "placeholder: true", fix)]
    if found:
        what = ", ".join(sorted(p for p in found if p.isupper() or "-" in p)) or "the placeholder org's status"
        return [Check("org", FIX, f"the installed skills still hold the placeholder org's values ({what})",
                      fix if not rel or "example-co" in rel else
                      f"rebuild with your org, then {c.install_cmd()} --channel candidate")]
    return [Check("org", OK, f"the company's org overlay is applied ({rel or 'org-process'}; no placeholder left "
                             "in the installed skills)")]


def _commands_from_toml(project: Path) -> tuple[list[str], str | None]:
    f = project / "ai-dlc.toml"
    if not f.is_file():
        return [], None
    try:
        text = f.read_text(encoding="utf-8")
    except OSError as e:
        return [], f"{f.name}: {e.strerror or e}"
    try:
        import tomllib
    except ImportError:  # Python 3.10: read only `name = "command"` lines of [checks.commands]
        section, cmds = "", []
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("["):
                section = line.strip("[] ")
            elif section == "checks.commands" and (m := TOML_LINE.match(line)):
                cmds.append(m[1].replace('\\"', '"').replace("\\\\", "\\"))
        return cmds, None
    try:
        cmds = (tomllib.loads(text).get("checks") or {}).get("commands") or {}
    except ValueError as e:
        return [], f"{f.name}: {e}"
    return [str(v) for v in cmds.values() if isinstance(v, str)], None


@dataclass
class Rules:
    allow: list[str]
    ask: list[str]
    deny: list[str]
    bypass: bool
    managed_only: bool  # allowManagedPermissionRulesOnly: only the admin's allow rules count


def _rules(c: Ctx) -> Rules:
    """The permission rules that apply here: the admin's managed settings, then user and project settings."""
    managed: dict = {}
    if c.managed.is_file():
        managed = json.loads(c.managed.read_text(encoding="utf-8")) or {}
    layers = [managed]
    for d in dict.fromkeys([c.home / ".claude", c.target / ".claude"]):
        for name in (il.SETTINGS, il.SETTINGS_LOCAL):
            try:
                layers.append(il._read_settings(d, name) or {})
            except il.Refused:
                continue
    managed_only = managed.get("allowManagedPermissionRulesOnly") is True
    r = Rules([], [], [], False, managed_only)
    for i, s in enumerate(layers):
        p = s.get("permissions") or {}
        if not (managed_only and i > 0):  # with managed rules only, user and project rules don't allow or ask
            r.allow += [x for x in p.get("allow") or [] if isinstance(x, str)]
            r.ask += [x for x in p.get("ask") or [] if isinstance(x, str)]
            r.bypass |= p.get("defaultMode") == "bypassPermissions"
        r.deny += [x for x in p.get("deny") or [] if isinstance(x, str)]
    if "disable" in (managed.get("disableBypassPermissionsMode"),
                     (managed.get("permissions") or {}).get("disableBypassPermissionsMode")):
        r.bypass = False
    return r


def shell_tool(env: dict[str, str]) -> str:
    """The tool the agent's commands go through: Bash, or on Windows without Git Bash, PowerShell."""
    if not WINDOWS:
        return "Bash"
    git_bash = env.get("CLAUDE_CODE_GIT_BASH_PATH") or r"C:\Program Files\Git\bin\bash.exe"
    return "Bash" if Path(git_bash).is_file() else "PowerShell"


def _wild(pat: str, command: str) -> bool:
    """Claude Code's `*` is the only wildcard: `?` and `[` are literal."""
    return re.fullmatch(".*".join(re.escape(x) for x in pat.split("*")), command, re.S) is not None


def rule_matches(rule: str, command: str, tool: str = "Bash") -> bool:
    """Whether a shell permission rule covers one simple command, as Claude Code reads it: `Bash` or `Bash(*)` is
    every command, `Bash(npm test:*)` or `Bash(npm test *)` a prefix on a word boundary (the bare `npm test` too),
    `*` elsewhere a wildcard. Only rules for `tool` count."""
    m = re.fullmatch(r"(Bash|PowerShell)(?:\((.*)\))?", rule.strip(), re.S)
    if not m or m[1] != tool:
        return False
    pat = (m[2] or "*").strip()
    if pat in ("*", ""):
        return True
    for tail in (":*", " *"):
        if pat.endswith(tail) and "*" not in pat[:-len(tail)]:
            pre = pat[:-len(tail)].strip()
            return command == pre or command.startswith(pre + " ")
    if "*" in pat:
        return _wild(pat, command)
    return command == pat


def command_parts(cmd: str) -> list[str]:
    """A compound command's simple commands (split on && || ; | & and newlines, not inside quotes)."""
    parts: list[str] = []
    for line in cmd.splitlines():
        lex = shlex.shlex(line, posix=True, punctuation_chars=True)
        lex.whitespace_split = True
        try:
            words = list(lex)
        except ValueError:  # unbalanced quotes: judge the line whole
            parts.append(line.strip())
            continue
        cur: list[str] = []
        for w in words:
            if w in OPERATORS:
                parts.append(" ".join(cur))
                cur = []
            else:
                cur.append(w)
        parts.append(" ".join(cur))
    return [p for p in (x.strip() for x in parts) if p]


def check_allowlist(c: Ctx) -> list[Check]:
    from_toml, note = _commands_from_toml(c.target)
    cmds = list(dict.fromkeys([*c.test_cmds, *from_toml]))
    if not cmds:
        why = note or f"no --test-cmd and no ai-dlc.toml [checks.commands] in {c.target}"
        return [Check("allowlist", SKIP, f"no test or check commands to look for ({why})",
                      "rerun with --test-cmd '<your test command>'")]
    tool = shell_tool(c.env)
    r = _rules(c)
    missing, asked, denied = [], [], []
    for cmd in cmds:
        for part in command_parts(cmd):
            if any(rule_matches(x, part, tool) for x in r.deny):
                denied.append(part)
            elif any(rule_matches(x, part, tool) for x in r.ask):
                asked.append(part)
            elif not r.bypass and not any(rule_matches(x, part, tool) for x in r.allow):
                missing.append(part)
    missing, asked, denied = (list(dict.fromkeys(x)) for x in (missing, asked, denied))
    settings = c.target / ".claude" / il.SETTINGS
    where = f"{settings}, {c.home / '.claude' / il.SETTINGS}" + (f" and {c.managed}" if c.managed.is_file() else "")
    if denied:
        return [Check("allowlist", FIX, f"a deny rule blocks {', '.join(denied[:3])}",
                      f"look at permissions.deny in {where}")]
    if asked:
        return [Check("allowlist", FIX, f"an ask rule stops {', '.join(asked[:3])} for permission every time",
                      f"look at permissions.ask in {where}")]
    if missing:
        rules = ", ".join(json.dumps(f"{tool}({p}:*)") for p in missing)
        if r.managed_only:
            how = f"ask your admin to allow {rules} (managed settings allow only their own rules)"
        else:
            how = f"add to permissions.allow in {settings}: {rules}"
        return [Check("allowlist", FIX, f"{len(missing)} test or check command(s) would stop for permission: "
                                        f"{', '.join(missing[:3])}" + (" ..." if len(missing) > 3 else ""), how)]
    return [Check("allowlist", OK, f"the repository's {len(cmds)} test and check command(s) are allowed ({tool})")]


def check_capture(c: Ctx) -> list[Check]:
    problems, fixes = [], []
    rc, _ = c.run(["hangar", "trace", "import", "--help"], 60)
    if rc != 0:
        problems.append("`hangar trace import` doesn't run")
        fixes.append("install hangar from your company's approved source (work-laptop runbook)")
    rc, _ = c.run(["flightdeck", "ingest", "file", "--help"], 60)
    if rc != 0:
        problems.append("`flightdeck ingest file` doesn't run")
        fixes.append("install flightdeck from the same source")
    projects = c.home / ".claude" / "projects"
    if not projects.is_dir():
        problems.append(f"no transcripts yet in {projects}")
        fixes.append("run one Claude Code session in the repository")
    if problems:
        return [Check("capture", FIX, "trace capture for flightdeck isn't ready: " + "; ".join(problems),
                      "; ".join(fixes))]
    return [Check("capture", OK, "hangar trace import and flightdeck ingest run, and transcripts exist (local only)")]


CHECKS: list[tuple[str, Callable[[Ctx], list[Check]]]] = [
    ("claude", check_claude), ("model", check_model), ("python", check_python), ("install", check_install),
    ("hooks", check_hooks), ("channel", check_channel), ("checkout", check_checkout),
    ("one-harness", check_one_harness), ("guide", check_guide), ("mcp", check_mcp), ("gh", check_gh),
    ("org", check_org), ("allowlist", check_allowlist), ("capture", check_capture),
]


def find_install(scope: str | None, home: Path, target: Path) -> tuple[str | None, Path | None, dict | None]:
    """The scope, .claude directory and manifest of the install the doctor looks at."""
    for s in ([scope] if scope else ["project", "user"]):
        base = il.base_dir(s, home, target)
        m = il.read_manifest(base)
        if m or scope:
            return s, base, m
    return None, None, None


def diagnose(c: Ctx, skip: tuple[str, ...] = ()) -> list[Check]:
    out: list[Check] = []
    for cid, fn in CHECKS:
        if cid in skip:
            out.append(Check(cid, SKIP, "skipped (--skip)"))
            continue
        try:
            out += fn(c)
        except Exception as e:  # noqa: BLE001  one broken check must not cost the others (or the JSON)
            out.append(Check(cid, FIX, f"the check failed: {type(e).__name__}: {e}",
                             "fix what it names, then run the doctor again"))
    return out


def render(c: Ctx, checks: list[Check]) -> str:
    where = f"{c.scope} scope, {c.base}" if c.base else "not installed"
    lines = [f"team-harness doctor: {c.name} ({where})"]
    width = max(len(x.id) for x in checks)
    for x in checks:
        lines.append(f"  {x.status:<4}  {x.id:<{width}}  {x.summary}")
        if x.fix and x.status != OK:
            lines.append(f"        {'':<{width}}  {'fix' if x.status == FIX else 'to run it'}: {x.fix}")
    fixes = [x.id for x in checks if x.status == FIX]
    lines.append(f"{len(fixes)} to fix: {', '.join(fixes)}" if fixes else "ready: nothing to fix")
    return "\n".join(lines)


def main(argv: list[str] | None = None, run: Runner = run_cmd, env: dict[str, str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("harness", type=Path, help="the harness directory (holds harness.lock)")
    ap.add_argument("--scope", choices=("user", "project"), help="default: project if installed there, else user")
    ap.add_argument("--home", type=Path, default=Path.home(), help="the home whose .claude to look at")
    ap.add_argument("--target", type=Path, default=Path.cwd(), help="the project directory (default: here)")
    ap.add_argument("--json", action="store_true", help="print team-harness.doctor/v1 JSON (for hangar, flightdeck)")
    ap.add_argument("--live", action="store_true", help="also ask the model once and send tools/list to each server")
    ap.add_argument("--exact-runtime", action="store_true", help="a newer Claude Code than the lock's is a fix too")
    ap.add_argument("--github-host", default=None, help="the company's GitHub host (default $GH_HOST or github.com)")
    ap.add_argument("--test-cmd", action="append", default=[], help="a command the agent must be allowed to run")
    ap.add_argument("--skip", action="append", default=[], choices=[cid for cid, _ in CHECKS],
                    help="leave a check out (repeatable)")
    ap.add_argument("--managed-settings", type=Path, default=MANAGED_SETTINGS, help=argparse.SUPPRESS)
    a = ap.parse_args(argv)
    env = dict(os.environ if env is None else env)
    try:
        lock = il._lock_at(a.harness)
        home, target = a.home.expanduser(), a.target.expanduser().resolve()
        scope, base, manifest = find_install(a.scope, home, target)
    except il.Refused as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    c = Ctx(harness=a.harness.resolve(), lock=lock, scope=scope, base=base, home=home, target=target,
            manifest=manifest, run=run, env=env, live=a.live, exact_runtime=a.exact_runtime,
            github_host=a.github_host or env.get("GH_HOST") or "github.com", test_cmds=tuple(a.test_cmd),
            managed=a.managed_settings)
    checks = diagnose(c, tuple(a.skip))
    fixes = sum(1 for x in checks if x.status == FIX)
    if a.json:
        print(json.dumps({"schema": SCHEMA, "harness": c.name, "revision": lock.get("revision"), "scope": scope,
                          "base": str(base) if base else None, "ok": fixes == 0,
                          "checks": [asdict(x) for x in checks]}, indent=2))
    else:
        print(render(c, checks))
    return 1 if fixes else 0


if __name__ == "__main__":
    sys.exit(main())
