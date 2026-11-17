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

Without `--scope` it looks for an install in `<target>/.claude` (project scope), then `<home>/.claude` (user scope).
`--skip ID` leaves a check out (`--skip capture` on a laptop without flightdeck); skipped checks still print.
`--test-cmd CMD` (repeatable) names a command that must be allowed; the target's `ai-dlc.toml` `[checks.commands]`
are read too. Windows: runs natively under PowerShell or cmd (`py -3 scripts\\doctor.py ...`); the hook interpreter
there is `py -3`.

Exit codes: 0 nothing to fix, 1 something to fix, 2 bad input. Needs Python 3.10+ and PyYAML.
"""

from __future__ import annotations

import argparse
import fnmatch
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
ORG_PLACEHOLDERS = ("COMPANY-SITE", "COMPANY-SPACE", "WORKPROJ", "SREPROJ", "SECPROJ", "The org overlay is not applied")
# `claude mcp list`: `name: <url or command> (HTTP) - ✓ Connected` (or `× Failed to connect — why`, `! Needs ...`)
MCP_LINE = re.compile(r"^(?P<name>[^\s:][^:]*): (?P<target>.*?)(?: \((?P<kind>HTTP|SSE|stdio)\))? - (?P<status>.+)$")
VERSION = re.compile(r"(\d+)\.(\d+)\.(\d+)")
SPLIT = re.compile(r"\s*(?:&&|\|\||;|\|)\s*")  # a compound command's parts, each allowed on its own

Runner = Callable[[list[str], float], "tuple[int | None, str]"]


@dataclass
class Check:
    id: str
    status: str
    summary: str
    fix: str = ""


def run_cmd(argv: list[str], timeout: float = 60) -> tuple[int | None, str]:
    """(exit code, stdout and stderr), or (None, why) when the program can't start. A Windows `claude.cmd` is found
    through PATHEXT, which subprocess alone doesn't do."""
    exe = shutil.which(argv[0]) or argv[0]
    try:
        r = subprocess.run([exe, *argv[1:]], capture_output=True, text=True, timeout=timeout, check=False,  # noqa: S603
                           encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL)
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

    @property
    def repo(self) -> Path:
        return self.harness.parent.parent

    @property
    def name(self) -> str:
        return str(self.lock["name"])

    def install_cmd(self) -> str:
        where = f" --target {_q(self.target)}" if (self.scope or "project") == "project" else ""
        py = "py -3" if WINDOWS else "python3"
        return (f"{py} scripts/install_local.py harnesses/{self.name} --scope {self.scope or 'project'}{where} "
                "--apply")


def _q(p: Path | str) -> str:
    return subprocess.list2cmdline([str(p)]) if WINDOWS else shlex.quote(str(p))


def _not_installed(c: Ctx, check_id: str) -> Check:
    return Check(check_id, SKIP, f"{c.name} is not installed yet", c.install_cmd())


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
    rc, out = c.run(["claude", "-p", "--model", model, "--max-turns", "1", "Reply with the single word: ok"], 180)
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
                      f"uninstall it first (install_local.py harnesses/{c.manifest.get('harness')} --scope {c.scope} "
                      "--uninstall), then " + c.install_cmd())]
    drift = [d for d in il.check(None, None, None, c.base)
             if not d.startswith(("hook did not run", "guard's block", "hook sees no"))]
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
    dead = il.probe_hooks(c.base, c.scope or "user", entries)
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
    rc, out = c.run(["git", "-C", str(c.repo), "status", "--porcelain", "--", *paths], 30)
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
                      f"python3 scripts/install_local.py harnesses/{h} --scope {other_scope}"
                      + (f" --target {_q(c.target)}" if other_scope == "project" else "") + " --uninstall")]
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
        out.append(Check("settings", FIX, f"{s} is a symlink, so another tool can swap the deny rules and hooks",
                         f"replace it with a copy of its target: {'Copy-Item' if WINDOWS else 'cp'} "
                         f"{_q(s.resolve())} {_q(s)} after removing the link"))
    else:
        out.append(Check("settings", OK, f"{s.name} is a real file" if s.exists() else f"no {s.name} yet"))
    return out


def _mcp_list(c: Ctx) -> tuple[dict[str, dict[str, str]] | None, str]:
    rc, out = c.run(["claude", "mcp", "list"], 120)
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


def check_mcp(c: Ctx) -> list[Check]:
    servers_wanted = (c.lock.get("binding") or {}).get("mcp") or []
    if not servers_wanted:
        return [Check("mcp", SKIP, "the lock binds no MCP server")]
    have, raw = _mcp_list(c)
    adds = il.mcp_commands(SimpleNamespace(root=c.harness, name=c.name, lock=c.lock), c.scope or "project")
    binding = _binding(c)
    out = []
    for i, m in enumerate(servers_wanted):
        name, cid = m["name"], f"mcp:{m['name']}"
        add = adds[i] if i < len(adds) else f"claude mcp add {name} ..."
        if have is None:
            out.append(Check(cid, SKIP, f"can't list MCP servers ({raw.strip()[:100]})", "fix the claude check first"))
            continue
        got = have.get(name)
        if not got:
            out.append(Check(cid, FIX, f"{name} is not added", add))
            continue
        want_target = m.get("endpoint") if m.get("transport") == "http" else m.get("command")
        if want_target and want_target not in got["target"]:
            out.append(Check(cid, FIX, f"{name} points at {got['target']}, the lock binds {want_target}",
                             f"claude mcp remove {name}; then {add}"))
            continue
        variables = [il._var(name, h, binding) for h in m.get("header_names") or []] + list(m.get("env_names") or [])
        unset = [v for v in variables if not c.env.get(v)]
        status = got["status"]
        if "auth" in status.lower():
            out.append(Check(cid, FIX, f"{name} needs you to sign in",
                             f"in Claude Code, run /mcp, pick {name} and sign in (a remote server may use OAuth "
                             "rather than a header token)"))
        elif "connected" not in status.lower() or "fail" in status.lower():
            why = re.sub(r"^\W+", "", status)[:140]
            hint = f"set {', '.join(unset)} from your secret manager and restart Claude Code" if unset and \
                c.scope == "project" else "check the credential and the network, then `claude mcp list` again"
            out.append(Check(cid, FIX, f"{name} doesn't answer ({why})", hint))
        elif c.live and m.get("transport") == "http" and m.get("header_names"):
            var = il._var(name, m["header_names"][0], binding)
            if not c.env.get(var):
                out.append(Check(cid, OK, f"{name} connected; tools/list not sent ({var} unset here, the server "
                                          "has its own copy)"))
            else:
                n, err = tools_list(m["endpoint"], m["header_names"][0], c.env[var])
                out.append(Check(cid, OK, f"{name} connected; tools/list returned {n} tools") if err is None else
                           Check(cid, FIX, f"{name} tools/list failed: {err}", f"check {var} (whole header value, such "
                                                                               "as `Bearer <token>`)"))
        else:
            vs = f"; {', '.join(variables)} {'set' if not unset else 'unset here'}" if variables else ""
            out.append(Check(cid, OK, f"{name} connected ({got['kind'] or m.get('transport')}){vs}"))
    return out


def tools_list(endpoint: str, header: str, value: str, timeout: float = 30) -> tuple[int, str | None]:
    """One MCP streamable-HTTP handshake and tools/list. (tool count, None) or (0, why); the value is sent only to
    endpoint and never shown."""
    session: dict[str, str] = {}

    def post(body: dict[str, Any]) -> Any:
        h = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream", header: value,
             "MCP-Protocol-Version": "2025-06-18", **session}
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
        if not isinstance(init, dict) or "result" not in init:
            return 0, f"initialize returned no result ({(init or {}).get('error', {}).get('message', 'empty')})"
        post({"jsonrpc": "2.0", "method": "notifications/initialized"})
        res = post({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    except urllib.error.HTTPError as e:
        return 0, f"HTTP {e.code}" + (" (the credential was refused)" if e.code in (401, 403) else "")
    except (urllib.error.URLError, OSError, ValueError) as e:
        return 0, str(getattr(e, "reason", e))[:120]
    tools = ((res or {}).get("result") or {}).get("tools") if isinstance(res, dict) else None
    if not isinstance(tools, list):
        return 0, "tools/list returned no tool list"
    return len(tools), None


def check_gh(c: Ctx) -> list[Check]:
    host = c.github_host
    rc, out = c.run(["gh", "auth", "status", "--hostname", host], 60)
    login = f"gh auth login --hostname {host} --scopes repo"
    if rc is None:
        return [Check("gh", FIX, f"the GitHub CLI doesn't run ({out})",
                      "install gh (https://cli.github.com, or your company's software portal), then " + login)]
    if rc != 0:
        return [Check("gh", FIX, f"gh is not signed in to {host}", login)]
    scopes = set(re.findall(r"'([a-z:_]+)'", "".join(ln for ln in out.splitlines() if "scopes" in ln.lower())))
    if scopes and "repo" not in scopes:
        return [Check("gh", FIX, f"gh is signed in to {host} without repo scope ({', '.join(sorted(scopes))})",
                      f"gh auth refresh --hostname {host} --scopes repo")]
    note = "with repo scope" if scopes else "(a fine-grained or app token: scopes not listed)"
    return [Check("gh", OK, f"gh is signed in to {host} {note}")]


def check_org(c: Ctx) -> list[Check]:
    if not c.manifest:
        return [_not_installed(c, "org")]
    files = c.manifest.get("files") or {}
    org_skills = [r for r in files if r.startswith(("skills/release-approvals/", "skills/org-process/"))]
    if not org_skills:
        return [Check("org", SKIP, f"{c.name} takes no org overlay")]
    found: dict[str, set[str]] = {}
    for rel in org_skills:
        f = c.base / rel
        try:
            text = f.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for p in ORG_PLACEHOLDERS:
            if p in text:
                found.setdefault(p, set()).add(rel.split("/")[1])
    if found:
        what = ", ".join(sorted(p for p in found if p.isupper() or "-" in p)) or "the placeholder org"
        return [Check("org", FIX, f"the company's org overlay is not applied: the installed skills still hold {what}",
                      "add your company's org on the work laptop (orgs/README.md, 'Add your company's org'), point "
                      f"{c.name} at it in shared/work-system/targets.yaml, build, then {c.install_cmd()} "
                      "--channel checkout")]
    return [Check("org", OK, "the company's org overlay is applied (no placeholder left in the installed skills)")]


def _commands_from_toml(project: Path) -> tuple[list[str], str | None]:
    f = project / "ai-dlc.toml"
    if not f.is_file():
        return [], None
    try:
        import tomllib
    except ImportError:  # Python 3.10
        return [], f"{f.name} not read: Python 3.11+ reads TOML"
    try:
        cmds = (tomllib.loads(f.read_text(encoding="utf-8")).get("checks") or {}).get("commands") or {}
    except (OSError, ValueError) as e:
        return [], f"{f.name}: {e}"
    return [str(v) for v in cmds.values() if isinstance(v, str)], None


def _rules(c: Ctx) -> tuple[list[str], list[str], bool]:
    allow, deny, bypass = [], [], False
    dirs = [c.home / ".claude", c.target / ".claude"]
    for d in dict.fromkeys(dirs):
        for name in (il.SETTINGS, il.SETTINGS_LOCAL):
            try:
                s = il._read_settings(d, name) or {}
            except il.Refused:
                continue
            p = s.get("permissions") or {}
            allow += [r for r in p.get("allow") or [] if isinstance(r, str)]
            deny += [r for r in p.get("deny") or [] if isinstance(r, str)]
            bypass |= p.get("defaultMode") == "bypassPermissions"
    return allow, deny, bypass


def rule_matches(rule: str, command: str) -> bool:
    """Whether a Bash (or, on Windows, PowerShell) permission rule covers one simple command, as Claude Code reads
    it: `Bash` or `Bash(*)` is every command, `Bash(npm test:*)` a prefix on a word boundary, `*` a wildcard."""
    m = re.fullmatch(r"(Bash|PowerShell)(?:\((.*)\))?", rule.strip(), re.S)
    if not m or (m[1] == "PowerShell" and not WINDOWS):
        return False
    pat = (m[2] or "*").strip()
    if pat in ("*", ""):
        return True
    if pat.endswith(":*"):
        pre = pat[:-2].strip()
        return command == pre or command.startswith(pre + " ")
    if "*" in pat:
        return fnmatch.fnmatchcase(command, pat)
    return command == pat


def check_allowlist(c: Ctx) -> list[Check]:
    from_toml, note = _commands_from_toml(c.target)
    cmds = list(dict.fromkeys([*c.test_cmds, *from_toml]))
    if not cmds:
        why = note or f"no --test-cmd and no ai-dlc.toml [checks.commands] in {c.target}"
        return [Check("allowlist", SKIP, f"no test or check commands to look for ({why})",
                      "rerun with --test-cmd '<your test command>'")]
    allow, deny, bypass = _rules(c)
    missing, denied = [], []
    for cmd in cmds:
        for part in (p.strip() for p in SPLIT.split(cmd) if p.strip()):
            if any(rule_matches(r, part) for r in deny):
                denied.append(part)
            elif not bypass and not any(rule_matches(r, part) for r in allow):
                missing.append(part)
    missing, denied = list(dict.fromkeys(missing)), list(dict.fromkeys(denied))
    settings = c.target / ".claude" / il.SETTINGS
    if denied:
        return [Check("allowlist", FIX, f"a deny rule blocks {', '.join(denied[:3])}",
                      f"look at permissions.deny in {settings} and {c.home / '.claude' / il.SETTINGS}")]
    if missing:
        rules = ", ".join(json.dumps(f"Bash({p}:*)") for p in missing)
        return [Check("allowlist", FIX, f"{len(missing)} test or check command(s) would stop for permission: "
                                        f"{', '.join(missing[:3])}" + (" ..." if len(missing) > 3 else ""),
                      f"add to permissions.allow in {settings}: {rules}")]
    return [Check("allowlist", OK, f"the repository's {len(cmds)} test and check command(s) are allowed")]


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
        except (il.Refused, OSError, ValueError, yaml.YAMLError) as e:
            out.append(Check(cid, FIX, f"the check failed: {e}", "fix what it names, then run the doctor again"))
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
    a = ap.parse_args(argv)
    env = dict(os.environ if env is None else env)
    try:
        lock = il._lock_at(a.harness)
        home, target = a.home.expanduser(), a.target.expanduser()
        scope, base, manifest = find_install(a.scope, home, target)
    except il.Refused as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    c = Ctx(harness=a.harness.resolve(), lock=lock, scope=scope, base=base, home=home, target=target,
            manifest=manifest, run=run, env=env, live=a.live, exact_runtime=a.exact_runtime,
            github_host=a.github_host or env.get("GH_HOST") or "github.com", test_cmds=tuple(a.test_cmd))
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
