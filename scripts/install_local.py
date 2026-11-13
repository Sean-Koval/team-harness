#!/usr/bin/env python3
"""Install a harness into Claude Code on a laptop, pinned to its `harness.lock`, and keep it that way.

hangar renders a harness into a sandbox's `~/.claude`; this does the same for a person's own machine, so a teammate
running Claude Code locally gets the same skills, hooks, guide and deny rules as an agent in hangar.

    python scripts/install_local.py harnesses/work-default --scope project --target ~/src/svc            # the plan
    python scripts/install_local.py harnesses/work-default --scope project --target ~/src/svc --apply    # install
    python scripts/install_local.py harnesses/work-default --scope project --target ~/src/svc --check    # drift?
    python scripts/install_local.py harnesses/work-default --scope project --target ~/src/svc --uninstall
    python scripts/install_local.py harnesses/suite-default --scope user --apply                         # ~/.claude

Channels. It installs a channel from `channels.yaml` (`--channel`, default `stable`), never just whatever the checkout
holds. When the checkout's lock is that channel's digest it installs from the checkout, which must be clean
(`--allow-dirty` to override). Otherwise it finds the lock in the git history of `harness.lock` and installs that
commit's harness directory. `--channel checkout` installs the checkout as it is (for trying a change).

Scopes. `user` writes under `<home>/.claude/` (`--home`, default your home): skills to `skills/<name>/`, hooks to
`hooks/`. Its hooks and deny rules then apply to every Claude Code session on the machine; nothing is committed, so
it is the team default. `project` writes the same under `<target>/.claude/` (`--target`, default the current
directory) and rewrites hook commands from `$HOME/.claude/hooks/...` to `"$CLAUDE_PROJECT_DIR"/.claude/hooks/...`.
Its skills, guide and deny rules (`settings.json`) can be committed. Its hooks go to `settings.local.json`, and their
manifest entries to `team-harness.local.json`, as a hook command differs by OS: a team of Macs and Windows machines
then commits the same bytes. It adds `.claude/*.local.json` to the project's `.gitignore` unless git already ignores
both files, and takes the line out again on `--uninstall`. The guide always goes to
`team-harness/<harness>.md`, and one `@team-harness/<harness>.md` line is added to `CLAUDE.md` beside it (and removed on
`--uninstall`), so edits to your `CLAUDE.md` never block an upgrade.

What it never does:

- Overwrite a file it didn't install, unless that file already holds the new bytes (it is then adopted). Any other
  clash refuses the whole install before anything is written.
- Replace your own `CLAUDE.md`: it only adds (and on uninstall removes) the one `@import` line.
- Drop your settings. `settings.json` is merged: the harness's hook groups and permission rules are added, your own
  entries are kept, and only entries this script added are ever removed. The manifest names every entry it is about
  to add before settings.json is written, so a failure part way stays reversible. A symlinked settings.json (your
  dotfiles) is written through to its target.
- Install from a checkout that doesn't match its lock: every pinned digest is checked first.
- Touch MCP servers or credentials. It prints the `claude mcp add` commands for the lock's servers, with each
  credential as a `$VARIABLE` placeholder for you to fill from your secret manager. Plugins are printed the same way.
- Install two harnesses into one scope: `--uninstall` the first (work and personal harnesses stay apart).

The manifest `.claude/team-harness.json` records the harness, its channel, revision and `harness_digest`, the source
commit, the settings entries added and the SHA-256 of every file written. `--check` reports an edited or missing file,
a removed settings entry or `@import` line, or that the channel has moved to another revision. `--uninstall` removes only files whose digest
still matches, leaving an edited file in place with a warning.

Windows (KAN-460). It runs natively, without WSL2, under PowerShell or cmd: `py -3 scripts\\install_local.py ...`.
Hook commands are written for Windows: `py -3` instead of `python3`; in user scope the hook's absolute path, in double
quotes with forward slashes, built from the profile directory (`--home`) instead of `$HOME`; in project scope a
`py -3 -c` line that finds the hook through `CLAUDE_PROJECT_DIR`, so no machine path lands in a committed file.

Hooks that don't start. Claude Code carries on when a hook command can't start (no `py` or `python3`, a wrong path),
so the guard is off with no warning. `--apply` and `--check` run every installed hook script once, through the shell
Claude Code uses (`sh -c`; on Windows Git Bash, or PowerShell where Git Bash isn't installed), with a harmless
`git status` call on stdin; any exit but 0 fails loudly (exit 1).

Uninstall puts back `settings.json`, `settings.local.json`, `.gitignore` and `CLAUDE.md` byte for byte. For a settings file, as the manifest keeps the original bytes, unless you
changed the file meanwhile in some other way: then your settings are kept and only the formatting may differ.

Exit codes: 0 done or clean, 1 refused or drift, 2 bad input. Needs Python 3.10+ and PyYAML.
"""

from __future__ import annotations

import argparse
import base64
import copy
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

SCHEMA = "team-harness.install/v1"
MANIFEST = "team-harness.json"
MANIFEST_LOCAL = "team-harness.local.json"  # this machine's settings.local.json entries: never committed
RUNTIME = "claude-code"
NATIVE = f"native:{RUNTIME}/"
SETTINGS = "settings.json"
SETTINGS_LOCAL = "settings.local.json"  # per machine and gitignored: project-scope hooks, whose command is per OS
SECTION = {SETTINGS: "settings", SETTINGS_LOCAL: "settings_local"}  # each file's block in the manifest
LOCAL_IGNORE = ".claude/*.local.json"  # settings.local.json and team-harness.local.json
_MCP_FIELDS = (("endpoint", "url"), ("header_names", "headers"), ("env_names", "env"), ("command", "command"),
               ("args", "args"))
_HOME_HOOK = re.compile(r'"?(?:\$HOME|\$\{HOME\}|~)/\.claude/hooks/([^"\s]+)"?')
# the one hook shape the harnesses use: python3 "$HOME/.claude/hooks/<file>.py", rewritten for Windows
_PY_HOOK = re.compile(r'\s*python3?\s+"?(?:\$HOME|\$\{HOME\}|~)/\.claude/hooks/([A-Za-z0-9_.-]+\.py)"?\s*')
WINDOWS = os.name == "nt"  # tests set it to check the Windows commands on any OS


class Refused(Exception):
    """The harness or the target is not in a state this script will act on (exit 2)."""


# --- digests: the same values as hangar's harness_lock (tests compare them with hangar's own) -------------------

def sha(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def files_digest(files: dict[str, bytes]) -> str:
    """hangar `harness_lock.files_digest`: per file in path-component order, the path, NUL, raw SHA-256."""
    h = hashlib.sha256()
    for rel in sorted(files, key=lambda r: tuple(r.split("/"))):
        h.update(rel.encode() + b"\0")
        h.update(hashlib.sha256(files[rel]).digest())
    return "sha256:" + h.hexdigest()


def harness_digest(lock: dict[str, Any]) -> str:
    """hangar `harness_lock.harness_digest`: SHA-256 of the canonical JSON of the lock's identity sections."""
    runtime, model, binding = lock.get("runtime") or {}, lock.get("model") or {}, lock.get("binding") or {}
    comps = lock.get("components") or []

    def kind(c: dict[str, Any]) -> str:
        return c.get("id", "").partition(":")[0]

    def cname(c: dict[str, Any]) -> str:
        return c["id"].partition(":")[2]

    guide = next((c for c in comps if kind(c) == "guide"), None)
    plugins = []
    for c in comps:
        if kind(c) == "plugin":
            name, _, mkt = cname(c).rpartition("@")
            plugins.append({"name": name, "marketplace": mkt, "digest": c.get("digest"),
                            "enabled": c.get("enabled", True)})
    mcp = []
    for x in binding.get("mcp") or []:
        d = {"name": x.get("name"), "transport": x.get("transport")}
        for ours, theirs in _MCP_FIELDS:
            d[theirs] = x.get(ours)
        mcp.append(d)
    ident = {
        "harness.name": runtime.get("harness"),
        "harness.locked": runtime.get("version"),
        "model.id": model.get("id"),
        "instructions.global.declared.digest": guide.get("digest") if guide else None,
        "skills.declared[*].{name,digest}": [{"name": cname(c), "digest": c.get("digest")}
                                             for c in comps if kind(c) == "skill"],
        "plugins[*].{name,marketplace,digest,enabled}": plugins or None,
        "mcp_servers[*].{name,transport,url,headers,env,command,args}": mcp,
        "hooks[*].{event,source,digest}": [{"event": x.get("event"), "source": x.get("source"),
                                           "digest": x.get("digest")} for x in binding.get("hooks") or []],
        "permissions.approvals": (binding.get("permissions") or {}).get("approvals"),
    }
    return sha(json.dumps(ident, sort_keys=True, separators=(",", ":"), default=str).encode())


def _read_dir(d: Path) -> dict[str, bytes]:
    return {f.relative_to(d).as_posix(): f.read_bytes()
            for f in sorted(d.rglob("*")) if f.is_file() and not f.is_symlink()}


# --- the harness, as the lock pins it ---------------------------------------------------------------------------

@dataclass
class Harness:
    root: Path
    lock: dict[str, Any]
    name: str
    revision: int
    digest: str
    files: dict[str, tuple[bytes, int]] = field(default_factory=dict)  # path under .claude -> (bytes, mode)
    guide: bytes | None = None
    settings: dict[str, Any] = field(default_factory=dict)
    source: dict[str, Any] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)  # where the checkout differs from the lock
    scope: str = "user"


def _git(root: Path, *args: str) -> str | None:
    try:
        r = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=10, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def _rel_ok(rel: str) -> bool:
    p = Path(rel)
    return bool(rel) and not p.is_absolute() and ".." not in p.parts


def load_harness(root: Path, scope: str, base: Path | None = None) -> Harness:
    """The harness at `root`; `base` is the .claude directory it goes into (Windows hook paths are built from it)."""
    lock_file = root / "harness.lock"
    try:
        lock = yaml.safe_load(lock_file.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as e:
        raise Refused(f"{lock_file}: {e}") from None
    if not isinstance(lock, dict) or lock.get("schema") != "hangar.harness-lock/v1":
        raise Refused(f"{lock_file}: not a hangar.harness-lock/v1 lock")
    if (lock.get("runtime") or {}).get("harness") != RUNTIME:
        raise Refused(f"{lock_file}: runtime is {lock.get('runtime', {}).get('harness')!r}; only {RUNTIME} "
                      "harnesses install locally")
    h = Harness(root=root, lock=lock, name=lock["name"], revision=int(lock["revision"]), digest=harness_digest(lock),
                scope=scope)

    for c in lock.get("components") or []:
        cid, rel = c["id"], c.get("path")
        if rel is None or cid.startswith("plugin:"):
            continue  # a reference skill or a plugin: printed, not installed
        if not _rel_ok(rel):
            raise Refused(f"{lock_file}: {cid} has an unsafe path {rel!r}")
        src = root / rel
        if cid.startswith("skill:"):
            files = _read_dir(src) if src.is_dir() else {}
            if files_digest(files) != c["digest"]:
                h.problems.append(f"{rel}/ does not match {cid} in the lock")
            for f, data in files.items():
                h.files[f"skills/{cid[6:]}/{f}"] = (data, (src / f).stat().st_mode & 0o777)
        elif cid.startswith(("guide:", NATIVE)):
            data = src.read_bytes() if src.is_file() else b""
            if not src.is_file() or sha(data) != c["digest"]:
                h.problems.append(f"{rel} does not match {cid} in the lock")
            if cid.startswith("guide:"):
                h.guide = data
            elif cid == f"{NATIVE}{SETTINGS}":
                try:
                    h.settings = json.loads(data or b"{}")
                except ValueError as e:
                    raise Refused(f"{src}: {e}") from None
            else:
                h.files[cid[len(NATIVE):]] = (data, src.stat().st_mode & 0o777 if src.is_file() else 0o644)
    h.settings = _scoped_settings(h.settings, scope, src=root / "native" / RUNTIME / SETTINGS, base=base)

    commit = _git(root, "rev-parse", "HEAD")
    dirty = _git(root, "status", "--porcelain", "--", ".", f"../../bindings/{h.name}.yaml")
    h.source = {"commit": commit, "dirty": bool(dirty) if dirty is not None else None}
    if scope == "user":  # a project's manifest may be committed: no machine path in it
        h.source["path"] = str(root.resolve())
    return h


# --- channels: which lock to install -----------------------------------------------------------------------------

def _lock_at(root: Path) -> dict[str, Any]:
    f = root / "harness.lock"
    if not f.is_file():
        raise Refused(f"{root} is not a harness directory: {f} is missing")
    try:
        lock = yaml.safe_load(f.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as e:
        raise Refused(f"{f}: {e}") from None
    if not isinstance(lock, dict) or not lock.get("name"):
        raise Refused(f"{f}: not a harness lock")
    return lock


def channel_digest(root: Path, name: str, channel: str) -> str:
    f = root.parent.parent / "channels.yaml"
    try:
        chans = ((yaml.safe_load(f.read_text(encoding="utf-8")) or {}).get(name) or {}) if f.is_file() else {}
    except (OSError, yaml.YAMLError) as e:
        raise Refused(f"{f}: {e}") from None
    if channel not in chans:
        have = ", ".join(sorted(chans)) or "none"
        raise Refused(f"{f} has no {name}@{channel} (channels: {have}); --channel checkout installs the checkout as is")
    return str(chans[channel])


@dataclass
class Source:
    root: Path  # the harness directory to install from
    channel: str
    digest: str  # the channel's harness_digest
    revision: int | None
    commit: str | None = None  # set when it came from the git history, not the working tree


def resolve(root: Path, channel: str, scratch: Path) -> Source:
    """Where `<harness>@<channel>` is: the checkout when its lock is the channel's digest, else the commit in the
    git history of harness.lock whose lock is, extracted under `scratch`."""
    lock = _lock_at(root)
    if channel == "checkout":
        return Source(root, channel, harness_digest(lock), int(lock.get("revision") or 0))
    want = channel_digest(root, lock["name"], channel)
    if harness_digest(lock) == want:
        return Source(root, channel, want, int(lock.get("revision") or 0))
    top = _git(root, "rev-parse", "--show-toplevel")
    if top:
        rel = root.resolve().relative_to(Path(top).resolve()).as_posix()
        for commit in (_git(Path(top), "log", "--format=%H", "--", f"{rel}/harness.lock") or "").split():
            try:
                old = yaml.safe_load(_git(Path(top), "show", f"{commit}:{rel}/harness.lock") or "")
            except yaml.YAMLError:
                continue
            if isinstance(old, dict) and harness_digest(old) == want:
                return Source(_extract(Path(top), commit, rel, lock["name"], scratch), channel, want,
                              int(old.get("revision") or 0), commit)
    raise Refused(f"{lock['name']}@{channel} is {want}, which is neither this checkout's lock "
                  f"(r{lock.get('revision')}, {harness_digest(lock)}) nor in its git history; fetch the full history "
                  f"(git fetch --unshallow), or choose another --channel")


def _extract(top: Path, commit: str, rel: str, name: str, scratch: Path) -> Path:
    """`commit`'s harness directory (and its binding, when it had one) under scratch, laid out as in the repo."""
    paths = [rel]
    binding = f"bindings/{name}.yaml"
    if _git(top, "cat-file", "-e", f"{commit}:{binding}") is not None:
        paths.append(binding)
    tar = scratch / "harness.tar"
    with tar.open("wb") as fh:
        # the committed bytes the lock pins: no autocrlf conversion on the way out (Git for Windows turns it on)
        r = subprocess.run(["git", "-C", str(top), "-c", "core.autocrlf=false", "archive", "--format=tar", commit,
                            "--", *paths], stdout=fh, check=False)
    if r.returncode != 0:
        raise Refused(f"git archive {commit} {rel} failed")
    with tarfile.open(tar) as t:
        if hasattr(tarfile, "data_filter"):
            t.extractall(scratch / "repo", filter="data")
        else:  # Python before the extraction filters: git archive writes no links out of the tree
            t.extractall(scratch / "repo")  # noqa: S202
    return scratch / "repo" / rel


def _scoped_settings(s: dict[str, Any], scope: str, src: Path, base: Path | None = None) -> dict[str, Any]:
    """The harness's settings with only what this script merges, hook commands rewritten for the scope."""
    s = {k: v for k, v in s.items() if k != "$schema"}
    extra = set(s) - {"hooks", "permissions"}
    if extra:
        raise Refused(f"{src}: install_local.py merges only hooks and permissions, not {sorted(extra)}")
    for k, v in (s.get("permissions") or {}).items():
        if not isinstance(v, list):
            raise Refused(f"{src}: permissions.{k} is not a list of rules; install_local.py can't merge it")
    if scope == "project" or WINDOWS:
        s = copy.deepcopy(s)
        for groups in (s.get("hooks") or {}).values():
            for g in groups:
                for hk in g.get("hooks") or []:
                    if isinstance(hk.get("command"), str):
                        hk["command"] = _hook_command(hk["command"], scope, src, base)
    return s


def _hook_command(cmd: str, scope: str, src: Path, base: Path | None) -> str:
    """A harness hook command as this machine runs it: unchanged for user scope on macOS and Linux."""
    if not WINDOWS:
        return _HOME_HOOK.sub(r'"$CLAUDE_PROJECT_DIR"/.claude/hooks/\1', cmd) if scope == "project" else cmd
    m = _PY_HOOK.fullmatch(cmd)
    if m is None:
        if _HOME_HOOK.search(cmd):
            raise Refused(f"{src}: the hook command {cmd!r} has no native Windows form; install_local.py rewrites "
                          'only python3 "$HOME/.claude/hooks/<file>.py"')
        return cmd  # an echo and the like: no path, no interpreter
    name = m.group(1)
    if scope == "project":
        # CLAUDE_PROJECT_DIR read by Python, not the shell: one line for Git Bash and PowerShell alike
        return ('py -3 -c "import os,runpy;runpy.run_path(os.path.join(os.environ[\'CLAUDE_PROJECT_DIR\'],'
                f"'.claude','hooks','{name}'),run_name='__main__')\"")
    path = Path(os.path.abspath(base or Path.home() / ".claude")).joinpath("hooks", name).as_posix()
    if any(c in path for c in '"$%`'):
        raise Refused(f'{path}: a hook path with ", $, % or ` can\'t be quoted for both Git Bash and PowerShell; '
                      "install with --home pointing elsewhere, or use --scope project")
    return f'py -3 "{path}"'


# --- settings.json merge ----------------------------------------------------------------------------------------

def _entries(s: dict[str, Any]) -> list[tuple[str, str, Any]]:
    """Every mergeable entry: ("hooks", event, group) and ("permissions", key, rule)."""
    out = [("hooks", ev, g) for ev, groups in (s.get("hooks") or {}).items() for g in groups]
    out += [("permissions", k, r) for k, rules in (s.get("permissions") or {}).items() for r in rules]
    return out


def _has(s: dict[str, Any], e: tuple[str, str, Any]) -> bool:
    return e[2] in ((s.get(e[0]) or {}).get(e[1]) or [])


def _remove(s: dict[str, Any], e: tuple[str, str, Any]) -> bool:
    lst = (s.get(e[0]) or {}).get(e[1])
    if not isinstance(lst, list) or e[2] not in lst:
        return False
    lst.remove(e[2])
    if not lst:  # it held only ours: leave no empty container behind
        del s[e[0]][e[1]]
        if not s[e[0]]:
            del s[e[0]]
    return True


def _add(s: dict[str, Any], e: tuple[str, str, Any]) -> None:
    s.setdefault(e[0], {}).setdefault(e[1], []).append(copy.deepcopy(e[2]))


def _record(e: tuple[str, str, Any]) -> dict[str, Any]:
    return {"section": e[0], "key": e[1], "value": e[2]}


def _unrecord(r: dict[str, Any]) -> tuple[str, str, Any]:
    return (r["section"], r["key"], r["value"])


def _describe(e: tuple[str, str, Any]) -> str:
    if e[0] == "permissions":
        return f"permissions.{e[1]} {e[2]}"
    cmds = "; ".join(hk.get("command", "?") for hk in e[2].get("hooks") or [])
    m = f" [{e[2]['matcher']}]" if e[2].get("matcher") else ""
    return f"{e[1]} hook{m} {cmds[:90] + ('...' if len(cmds) > 90 else '')}"


# --- plan, apply ------------------------------------------------------------------------------------------------

@dataclass
class SettingsPlan:
    """One settings file: what this install adds to it and how to put it back."""
    name: str
    lines: list[str] = field(default_factory=list)
    settings: dict[str, Any] | None = None  # the merged settings, None when unchanged
    records: list[dict[str, Any]] = field(default_factory=list)
    created: bool = False
    old_records: list[dict[str, Any]] = field(default_factory=list)  # the previous install's entries in this file
    original: str | None = None  # base64 of the file before this script first changed it

    def block(self, entries: list[dict[str, Any]]) -> dict[str, Any]:
        return {"created": self.created, "entries": entries,
                **({"original": self.original} if self.original is not None else {})}


@dataclass
class Plan:
    base: Path
    files: list[tuple[str, str]] = field(default_factory=list)  # (action, path) write|update|adopt|keep|remove
    left: list[str] = field(default_factory=list)  # managed files edited since: left alone
    conflicts: list[str] = field(default_factory=list)
    sfiles: dict[str, SettingsPlan] = field(default_factory=dict)  # settings.json, and settings.local.json
    gitignore: dict[str, Any] | None = None  # the line this install keeps in the project's .gitignore
    gitignore_add: bool = False  # ... and it is not there yet
    old_files: dict[str, str] = field(default_factory=dict)
    guide_rel: str | None = None
    guide_import: str | None = None  # the line CLAUDE.md needs, when it doesn't have it yet
    notes: list[str] = field(default_factory=list)


def base_dir(scope: str, home: Path, target: Path) -> Path:
    return (home if scope == "user" else target).expanduser() / ".claude"


def read_manifest(base: Path) -> dict[str, Any] | None:
    """The manifest, with this machine's settings.local.json block from team-harness.local.json when there is one."""
    f = base / MANIFEST
    if not f.is_file():
        return None
    try:
        m = json.loads(f.read_text(encoding="utf-8"))
        loc = json.loads((base / MANIFEST_LOCAL).read_text(encoding="utf-8")) \
            if (base / MANIFEST_LOCAL).is_file() else {}
    except ValueError as e:
        raise Refused(f"{f}: {e}") from None
    if m.get("schema") != SCHEMA or (loc and loc.get("schema") != SCHEMA):
        raise Refused(f"{f}: not a {SCHEMA} manifest")
    if loc.get("settings_local"):
        m["settings_local"] = loc["settings_local"]
    return m


def _write_manifest(base: Path, m: dict[str, Any]) -> None:
    """The committed manifest holds what every machine shares; the per-OS hook entries go beside it, gitignored."""
    m = dict(m)
    local = m.pop("settings_local", None)
    if local:
        _write(base / MANIFEST_LOCAL, (json.dumps({"schema": SCHEMA, "settings_local": local}, indent=2) + "\n")
               .encode(), 0o644)
    elif (base / MANIFEST_LOCAL).is_file():
        (base / MANIFEST_LOCAL).unlink()
    _write(base / MANIFEST, (json.dumps(m, indent=2) + "\n").encode(), 0o644)


def _read_settings(base: Path, name: str = SETTINGS) -> dict[str, Any] | None:
    f = base / name
    if not f.exists():
        return None
    try:
        s = _parse_settings(f.read_bytes())
    except ValueError as e:
        raise Refused(f"{f}: not valid JSON ({e}); fix it first, nothing is merged into a file that can't be read")
    if not isinstance(s, dict):
        raise Refused(f"{f}: not a JSON object")
    return s


def split_settings(s: dict[str, Any], scope: str) -> dict[str, dict[str, Any]]:
    """Which file each part goes to. Project scope: hooks to settings.local.json (per machine, gitignored), as their
    command differs by OS; deny rules stay in the committed settings.json. User scope: all of it in settings.json."""
    if scope != "project":
        return {SETTINGS: s, SETTINGS_LOCAL: {}}
    return {SETTINGS: {k: v for k, v in s.items() if k != "hooks"},
            SETTINGS_LOCAL: {"hooks": s["hooks"]} if s.get("hooks") else {}}


def _parse_settings(data: bytes) -> Any:
    """settings.json as Claude Code reads it: UTF-8, a byte-order mark allowed (Windows editors write one)."""
    return json.loads(data.decode("utf-8-sig") or "{}")


def _inside(base: Path, rel: str) -> bool:
    try:
        (base / rel).resolve().relative_to(base.resolve())
        return True
    except ValueError:
        return False


def plan_install(h: Harness, base: Path) -> Plan:
    p = Plan(base=base)
    old = read_manifest(base)
    if old and old["harness"] != h.name:
        raise Refused(f"{base} has {old['harness']} installed; run --uninstall with that harness first "
                      "(one harness per scope)")
    managed: dict[str, str] = (old or {}).get("files") or {}
    p.old_files = dict(managed)
    want = dict(h.files)

    # the guide: always beside CLAUDE.md, loaded by one @import line, so CLAUDE.md stays the person's own file
    if h.guide is not None:
        p.guide_rel = f"team-harness/{h.name}.md"
        want[p.guide_rel] = (h.guide, 0o644)
        cur = base / "CLAUDE.md"
        if cur.is_dir():
            p.conflicts.append("CLAUDE.md: is a directory")
        elif not _imports(cur, _import_line(h.name)):
            p.guide_import = _import_line(h.name)

    for rel, (data, _) in sorted(want.items()):
        f = base / rel
        if not _inside(base, rel) or f.is_symlink():
            p.conflicts.append(f"{rel}: a symlink or outside {base}; not followed")
        elif f.is_dir():
            p.conflicts.append(f"{rel}: is a directory")
        elif not f.exists():
            p.files.append(("write", rel))
        elif (cur := f.read_bytes()) == data:
            p.files.append(("keep" if rel in managed else "adopt", rel))
        elif rel in managed and sha(cur) == managed[rel]:
            p.files.append(("update", rel))
        elif rel in managed:
            p.conflicts.append(f"{rel}: edited since this script installed it")
        else:
            p.conflicts.append(f"{rel}: exists and was not installed by this script")
    for rel in sorted(set(managed) - set(want)):
        f = base / rel
        if not f.is_file():
            continue
        if sha(f.read_bytes()) == managed[rel]:
            p.files.append(("remove", rel))
        else:
            p.left.append(rel)

    # settings: drop what we added that the harness no longer has, add what is new, keep the rest where it is
    for name, part in split_settings(h.settings, h.scope).items():
        p.sfiles[name] = _plan_settings(base, name, part, ((old or {}).get(SECTION[name]) or {}), p.notes)

    # project scope: settings.local.json must stay out of git, or one OS's hook commands get committed for all
    if h.scope == "project" and p.sfiles[SETTINGS_LOCAL].records:
        gi = (old or {}).get("gitignore") or {}
        ignore = base.parent / ".gitignore"
        if gi.get("line") and _imports(ignore, gi["line"]):
            p.gitignore = gi
        elif not all(_git_ignores(base.parent, f".claude/{n}") for n in (SETTINGS_LOCAL, MANIFEST_LOCAL)):
            p.gitignore = {"file": ".gitignore", "line": LOCAL_IGNORE,
                           "created": bool(gi.get("created")) or not ignore.exists()}
            p.gitignore_add = True
    return p


def _plan_settings(base: Path, name: str, part: dict[str, Any], old: dict[str, Any], notes: list[str]) -> SettingsPlan:
    sp = SettingsPlan(name=name)
    cur_s = _read_settings(base, name)
    sp.old_records = list(old.get("entries") or [])
    # created: as recorded while this script has entries in the file; else as the file stands now
    sp.created = bool(old.get("created")) if sp.old_records else cur_s is None
    # the bytes to put back on uninstall: kept from the install that first changed the file; taken now only while
    # the file holds nothing of ours (an install from before KAN-460 left no copy, and its file has our entries)
    sp.original = old.get("original")
    if sp.original is None and cur_s is not None and not sp.old_records:
        sp.original = base64.b64encode((base / name).read_bytes()).decode()
    s = copy.deepcopy(cur_s or {})
    ours = [_unrecord(r) for r in sp.old_records]
    new = _entries(part)
    for e in ours:
        if e not in new and _remove(s, e):
            sp.lines.append(f"- {_describe(e)}")
    for e in new:
        if e in ours and _has(s, e):
            sp.records.append(_record(e))
        elif e not in ours and _has(s, e):
            notes.append(f"{name} already has {_describe(e)}; it stays yours")
        elif e in ours and e[0] == "hooks" and _edited_group(s, e):
            notes.append(f"{name}: you edited {_describe(e)}; it is yours now and is not added again")
        else:
            _add(s, e)
            sp.records.append(_record(e))
            sp.lines.append(f"+ {_describe(e)}")
    if s != (cur_s or {}) or (cur_s is None and s):
        sp.settings = s
    return sp


def _git_ignores(project: Path, rel: str) -> bool:
    """Whether git already ignores `rel` in the project (a .gitignore pattern, info/exclude, a global excludes file)."""
    try:
        r = subprocess.run(["git", "-C", str(project), "check-ignore", "-q", "--no-index", rel], capture_output=True,
                           timeout=10, check=False)
    except (OSError, subprocess.SubprocessError):
        return False
    return r.returncode == 0


def _commands(group: Any) -> set[str]:
    return {hk.get("command") for hk in (group.get("hooks") or []) if isinstance(hk, dict)} \
        if isinstance(group, dict) else set()


def _edited_group(s: dict[str, Any], e: tuple[str, str, Any]) -> bool:
    """A hook group this script added that is still there with the same commands, but edited (a matcher, a timeout)."""
    cmds = _commands(e[2])
    return bool(cmds) and any(_commands(g) == cmds for g in (s.get("hooks") or {}).get(e[1]) or [])


def _import_line(name: str) -> str:
    return f"@team-harness/{name}.md"


def _imports(claude_md: Path, line: str) -> bool:
    return claude_md.is_file() and line.encode() in claude_md.read_bytes().splitlines()


def _add_import(claude_md: Path, line: str) -> bool:
    """Append the line in the file's own line ending (CRLF from a Windows editor stays CRLF), bytes otherwise kept.
    True when the file had no final newline, so one was added before the line (removal takes it away again)."""
    data = claude_md.read_bytes() if claude_md.is_file() else b""
    eol = b"\r\n" if b"\r\n" in data else b"\n"
    joined = bool(data) and not data.endswith(b"\n")
    if joined:
        data += eol
    _write(claude_md, data + line.encode() + eol)
    return joined


def _remove_import(claude_md: Path, line: str, created: bool, joined: bool = False) -> bool:
    if not claude_md.is_file():
        return False
    lines = claude_md.read_bytes().splitlines(keepends=True)
    keep = [x for x in lines if x.rstrip(b"\r\n") != line.encode()]
    if keep == lines:
        return False
    if joined and keep and lines[-1].rstrip(b"\r\n") == line.encode():
        keep[-1] = keep[-1].rstrip(b"\r\n")  # the newline added before the line, when it was last
    if created and not b"".join(keep).strip():
        claude_md.unlink()
    else:
        _write(claude_md, b"".join(keep))
    return True


def _write(f: Path, data: bytes, mode: int | None = None) -> None:
    if f.is_symlink():  # settings.json or CLAUDE.md kept in dotfiles: write the file the link points at
        f = f.resolve()
    f.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=f.parent, prefix=f".{f.name}.")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.chmod(tmp, mode if mode is not None else (f.stat().st_mode & 0o777 if f.exists() else 0o644))
        os.replace(tmp, f)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _prune(base: Path, rel: str) -> None:
    d = (base / rel).parent
    while d != base and base in d.parents:
        try:
            d.rmdir()
        except OSError:
            return
        d = d.parent


def _settings_bytes(s: dict[str, Any]) -> bytes:
    return (json.dumps(s, indent=2, ensure_ascii=False) + "\n").encode()


def apply_install(h: Harness, p: Plan, scope: str, channel: str = "checkout") -> None:
    want = dict(h.files)
    if p.guide_rel:
        want[p.guide_rel] = (h.guide or b"", 0o644)
    digests: dict[str, str] = {}
    for action, rel in p.files:
        f = p.base / rel
        if action in ("write", "update"):
            _write(f, want[rel][0], want[rel][1])
        if action == "remove":
            f.unlink()
            _prune(p.base, rel)
        else:
            digests[rel] = sha(want[rel][0])
    old = read_manifest(p.base) or {}
    guide_import = dict(old.get("guide_import") or {})
    if p.guide_import:
        claude_md = p.base / "CLAUDE.md"
        guide_import = {"file": "CLAUDE.md", "line": p.guide_import,
                        "created": bool(guide_import.get("created")) or not claude_md.exists()}
        if _add_import(claude_md, p.guide_import):
            guide_import["joined"] = True

    def manifest(entries: dict[str, list[dict[str, Any]]], files: dict[str, str]) -> dict[str, Any]:
        m = {
            "schema": SCHEMA, "harness": h.name, "channel": channel, "revision": h.revision,
            "harness_digest": h.digest, "scope": scope, "source": h.source, "guide": p.guide_rel,
            "guide_import": guide_import or None,
            **{SECTION[n]: sp.block(entries[n]) for n, sp in p.sfiles.items()
               if n == SETTINGS or sp.records or sp.old_records or sp.original is not None},
            **({"gitignore": p.gitignore} if p.gitignore else {}),
            "files": dict(sorted(files.items())),
        }
        return json.loads(json.dumps(m))  # as read back

    final = {n: sp.records for n, sp in p.sfiles.items()}
    if any(sp.settings is not None for sp in p.sfiles.values()) or p.gitignore_add:
        # name every entry, old and new, before a settings file changes: a failure between the writes then leaves
        # entries the manifest still claims, so a re-run or --uninstall removes them instead of taking them as yours
        pending = {n: sp.old_records + [r for r in sp.records if r not in sp.old_records] for n, sp in p.sfiles.items()}
        _write_manifest(p.base, manifest(pending, {**p.old_files, **digests}))
        if p.gitignore_add and p.gitignore:  # before the hooks land in settings.local.json
            if _add_import(p.base.parent / p.gitignore["file"], p.gitignore["line"]):
                p.gitignore["joined"] = True
            _write_manifest(p.base, manifest(pending, {**p.old_files, **digests}))
        for n, sp in p.sfiles.items():
            if sp.settings is not None:
                _write(p.base / n, _settings_bytes(sp.settings))
    data = manifest(final, digests)
    cur = read_manifest(p.base)
    if cur is None or _strip_source(cur) != _strip_source(data):
        _write_manifest(p.base, data)


def _strip_source(m: dict[str, Any]) -> dict[str, Any]:
    """A manifest without its source block, so a re-run from another commit of the same lock writes nothing."""
    return {k: v for k, v in m.items() if k != "source"}


# --- printed, never run: MCP servers and plugins ----------------------------------------------------------------

def _var(name: str, header: str, binding: dict[str, Any]) -> str:
    val = str((((binding.get("mcp") or {}).get(name) or {}).get("headers") or {}).get(header) or "")
    m = re.fullmatch(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", val)
    return m.group(1) if m else re.sub(r"[^A-Z0-9]+", "_", f"{name}_MCP_{header}".upper())


def mcp_commands(h: Harness, scope: str) -> list[str]:
    bfile = h.root.parent.parent / "bindings" / f"{h.name}.yaml"
    binding = (yaml.safe_load(bfile.read_text()) or {}) if bfile.is_file() else {}
    # user scope: your shell fills $VAR when you run the command, so the value lands only in your own ~/.claude.json;
    # project scope: the literal ${VAR} goes into .mcp.json, which Claude Code expands at start (never commit a token)
    # on Windows the user-scope line is for PowerShell, which reads an environment variable as $env:NAME
    def quoted(text: str, var: str) -> str:
        if scope == "user":
            return f'"{text}$env:{var}"' if WINDOWS else f'"{text}${var}"'
        return f"'{text}${{{var}}}'"

    out = []
    for m in (h.lock.get("binding") or {}).get("mcp") or []:
        words = ["claude", "mcp", "add", "--scope", scope, "--transport", m.get("transport") or "stdio"]
        if m.get("transport") == "http":
            words += [m["name"], m["endpoint"]]
            for k in m.get("header_names") or []:
                words += ["--header", quoted(f"{k}: ", _var(m["name"], k, binding))]
        else:
            for k in m.get("env_names") or []:
                words += ["--env", quoted(f"{k}=", k)]
            words += [m["name"], "--", m.get("command") or "", *map(str, m.get("args") or [])]
        out.append(" ".join(words))
    return out


def plugin_commands(h: Harness, scope: str) -> list[str]:
    out, seen = [], set()
    for c in h.lock.get("components") or []:
        if c["id"].startswith("plugin:") and c.get("enabled", True):
            name, _, mkt = c["id"][7:].rpartition("@")
            if mkt not in seen:
                seen.add(mkt)
                where = str(h.root.resolve() / "plugins" / mkt)
                quote = subprocess.list2cmdline([where]) if WINDOWS else shlex.quote(where)
                out.append(f"claude plugin marketplace add {quote}")
            out.append(f"claude plugin install {name}@{mkt} --scope {scope}")
    return out


# --- check, uninstall -------------------------------------------------------------------------------------------

def check(h: Harness | None, lock_digest: str | None, lock_rev: int | None, base: Path,
          channel: str | None = None) -> list[str]:
    m = read_manifest(base)
    if m is None:
        return [f"not installed: {base / MANIFEST} is missing"]
    drift = []
    if h is not None and m["harness"] != h.name:
        drift.append(f"{base} has {m['harness']} installed, not {h.name}")
    gi = m.get("guide_import") or {}
    if gi.get("line") and not _imports(base / gi.get("file", "CLAUDE.md"), gi["line"]):
        drift.append(f"{gi.get('file', 'CLAUDE.md')} no longer has the line {gi['line']}")
    for rel, dg in sorted((m.get("files") or {}).items()):
        f = base / rel
        if not f.is_file():
            drift.append(f"missing: {rel}")
        elif sha(f.read_bytes()) != dg:
            drift.append(f"edited: {rel}")
    present = []
    for name, sec in SECTION.items():
        s = _read_settings(base, name) or {}
        for r in (m.get(sec) or {}).get("entries") or []:
            if not _has(s, _unrecord(r)):
                drift.append(f"{name} no longer has {_describe(_unrecord(r))}")
            else:
                present.append(r)
    ig = m.get("gitignore") or {}
    if ig.get("line") and not _imports(base.parent / ig.get("file", ".gitignore"), ig["line"]):
        drift.append(f"{ig.get('file', '.gitignore')} no longer has the line {ig['line']}, so {SETTINGS_LOCAL} "
                     "(this machine's hook commands) may be committed")
    drift += probe_hooks(base, m.get("scope") or "user", present)
    if lock_digest and lock_digest != m["harness_digest"]:
        newer = lock_rev is not None and lock_rev > int(m["revision"])
        where = f"on the {channel} channel" if channel and channel != "checkout" else "in the checkout"
        drift.append(f"{'newer harness revision' if newer else 'the harness changed'}: r{lock_rev} {lock_digest} "
                     f"{where}, r{m['revision']} {m['harness_digest']} installed; run --apply to upgrade")
    return drift


# a call every guard lets through: a hook that doesn't exit 0 on it either didn't start or is broken
PROBE = {"session_id": "team-harness-probe", "tool_name": "Bash", "tool_input": {"command": "git status"}}


def _runs_hook_file(cmd: str) -> bool:
    """A guard: a command that runs a script from .claude/hooks (an echo reminder is not a guard)."""
    return ".claude/hooks/" in cmd or "'.claude','hooks'" in cmd


def _git_bash() -> str | None:
    """The bash.exe Claude Code runs hooks with on Windows: CLAUDE_CODE_GIT_BASH_PATH, else Git for Windows' own (found
    beside git.exe, then in Program Files). Never C:\\Windows\\System32\\bash.exe, which is WSL."""
    named = os.environ.get("CLAUDE_CODE_GIT_BASH_PATH")
    if named:
        if not Path(named).is_file():
            raise FileNotFoundError(f"CLAUDE_CODE_GIT_BASH_PATH names no file: {named}")
        return named
    candidates = []
    git = shutil.which("git")
    if git:
        g = Path(git).resolve()  # <Git>/cmd/git.exe, <Git>/bin/git.exe or <Git>/mingw64/bin/git.exe
        candidates += [g.parent.parent / "bin" / "bash.exe", g.parent.parent.parent / "bin" / "bash.exe"]
    for var in ("ProgramFiles", "ProgramW6432", "ProgramFiles(x86)", "LOCALAPPDATA"):
        root = os.environ.get(var)
        if root:
            candidates += [Path(root) / "Git" / "bin" / "bash.exe", Path(root) / "Programs" / "Git" / "bin" / "bash.exe"]
    return next((str(c) for c in candidates if c.is_file()), None)


def hook_shell(cmd: str) -> list[str]:
    """The argv Claude Code runs a shell-form hook command with: `sh -c` on macOS and Linux; on Windows Git Bash, or
    PowerShell where Git Bash isn't installed. cmd never runs a hook, so probing through it would test the wrong
    shell."""
    if os.name != "nt":
        return ["/bin/sh", "-c", cmd]
    bash = _git_bash()
    if bash:
        return [bash, "-c", cmd]
    ps = shutil.which("powershell") or shutil.which("pwsh") or "powershell"
    return [ps, "-NoProfile", "-NonInteractive", "-Command", cmd]


def probe_hooks(base: Path, scope: str, entries: list[dict[str, Any]]) -> list[str]:
    """Run each hook command these settings entries add once, as Claude Code would, and say which didn't run."""
    root = base.parent  # the project, or the home whose .claude this is
    env = dict(os.environ)
    if scope == "project":
        env["CLAUDE_PROJECT_DIR"] = str(root)
    elif not WINDOWS:
        env["HOME"] = str(root)  # the --home the commands were installed for
    out, seen = [], set()
    for r in entries:
        if r.get("section") != "hooks" or not isinstance(r.get("value"), dict):
            continue
        for hk in r["value"].get("hooks") or []:
            cmd = hk.get("command") if isinstance(hk, dict) and hk.get("type", "command") == "command" else None
            if not isinstance(cmd, str) or cmd in seen or not _runs_hook_file(cmd):
                continue
            seen.add(cmd)
            event = json.dumps({**PROBE, "hook_event_name": r["key"], "cwd": str(root)}).encode()
            try:
                res = subprocess.run(hook_shell(cmd), input=event, capture_output=True, env=env,  # noqa: S603
                                     cwd=root if root.is_dir() else None, timeout=30, check=False)
                rc, said = res.returncode, (res.stderr or res.stdout).decode("utf-8", "replace").strip()
            except subprocess.TimeoutExpired:
                rc, said = None, "timed out after 30s"
            except OSError as e:
                rc, said = None, str(e)
            if rc != 0:
                first = said.splitlines()[0] if said else "no output"
                out.append(f"hook did not run, so its guard is OFF: {r['key']} {cmd!r} "
                           f"({'exit ' + str(rc) if rc is not None else 'error'}: {first[:200]})")
    return out


def uninstall(base: Path) -> tuple[list[str], list[str]]:
    """(removed, left) after removing every file and settings entry this script installed."""
    m = read_manifest(base)
    if m is None:
        raise Refused(f"nothing to uninstall: {base / MANIFEST} is missing")
    removed, left = [], []
    for rel, dg in sorted((m.get("files") or {}).items()):
        f = base / rel
        if not f.is_file():
            continue
        if sha(f.read_bytes()) == dg:
            f.unlink()
            _prune(base, rel)
            removed.append(rel)
        else:
            left.append(f"{rel}: edited since it was installed, so it is yours now")
    for name, sec in SECTION.items():
        _uninstall_settings(base, name, m.get(sec) or {}, removed, left)
    ig = m.get("gitignore") or {}
    if ig.get("line") and _remove_import(base.parent / ig.get("file", ".gitignore"), ig["line"],
                                         bool(ig.get("created")), bool(ig.get("joined"))):
        removed.append(f"{ig.get('file', '.gitignore')}: the line {ig['line']}")
    gi = m.get("guide_import") or {}
    if gi.get("line") and _remove_import(base / gi.get("file", "CLAUDE.md"), gi["line"], bool(gi.get("created")),
                                         bool(gi.get("joined"))):
        removed.append(f"{gi.get('file', 'CLAUDE.md')}: the line {gi['line']}")
    (base / MANIFEST_LOCAL).unlink(missing_ok=True)
    (base / MANIFEST).unlink()
    return removed, left


def _uninstall_settings(base: Path, name: str, block: dict[str, Any], removed: list[str], left: list[str]) -> None:
    cur = _read_settings(base, name)
    if cur is None or not block:
        return
    s = copy.deepcopy(cur)
    for r in block.get("entries") or []:
        if _remove(s, _unrecord(r)):
            removed.append(f"{name}: {_describe(_unrecord(r))}")
        else:
            left.append(f"{name}: {_describe(_unrecord(r))}: changed or already gone")
    original = _original(block)
    if not s and block.get("created"):
        (base / name).unlink()
    elif original is not None and _same_settings(original, s):
        if (base / name).read_bytes() != original:
            _write(base / name, original)  # the person's own bytes: indentation, key order, BOM, CRLF
    elif s != cur:
        _write(base / name, _settings_bytes(s))


def _original(block: dict[str, Any]) -> bytes | None:
    b64 = block.get("original")
    try:
        return base64.b64decode(b64, validate=True) if isinstance(b64, str) else None
    except ValueError:
        return None


def _same_settings(original: bytes, s: dict[str, Any]) -> bool:
    try:
        return _parse_settings(original) == s
    except ValueError:
        return False


# --- CLI --------------------------------------------------------------------------------------------------------

def _header(h: Harness, src: Source, scope: str, base: Path) -> str:
    if src.commit:
        origin = f"commit {src.commit[:12]} (from git history)"
    else:
        origin = h.source.get("commit") or "no git commit"
        if h.source.get("dirty"):
            origin += ", uncommitted changes"
    chan = "the checkout as is" if src.channel == "checkout" else f"{h.name}@{src.channel}"
    return f"{chan}: {h.name} r{h.revision} {h.digest} from {origin} -> {scope} scope, {base}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("harness", type=Path, help="the harness directory (holds harness.lock)")
    ap.add_argument("--scope", choices=("user", "project"), required=True)
    ap.add_argument("--home", type=Path, default=Path.home(), help="user scope: the home whose .claude/ to write")
    ap.add_argument("--target", type=Path, default=Path.cwd(), help="project scope: the project directory")
    ap.add_argument("--channel", help="the channels.yaml channel to install (default stable; --check: the installed "
                                      "one); 'checkout' installs the checkout as it is")
    ap.add_argument("--allow-dirty", action="store_true",
                    help="install from a checkout with uncommitted changes in the harness (or not in git)")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="print the plan and write nothing (the default)")
    mode.add_argument("--apply", action="store_true", help="install or upgrade")
    mode.add_argument("--check", action="store_true", help="exit 1 when the install drifted or the channel moved")
    mode.add_argument("--uninstall", action="store_true", help="remove what this script installed")
    a = ap.parse_args(argv)
    base = base_dir(a.scope, a.home, a.target)
    try:
        with tempfile.TemporaryDirectory(prefix="team-harness-") as scratch:
            return _run(a, base, Path(scratch))
    except Refused as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    except OSError as e:
        print(f"error: {e.filename or ''}: {e.strerror or e}".replace("error: : ", "error: "), file=sys.stderr)
        return 2


def _run(a: argparse.Namespace, base: Path, scratch: Path) -> int:
    if a.uninstall:
        name = _lock_at(a.harness)["name"]
        m = read_manifest(base)
        if m and m["harness"] != name:
            raise Refused(f"{base} has {m['harness']} installed, not {name}; name that harness")
        removed, left = uninstall(base)
        for r in removed:
            print(f"  removed {r}")
        for r in left:
            print(f"  warning: left {r}", file=sys.stderr)
        print(f"uninstalled from {base}")
        return 0
    if a.check:
        name = _lock_at(a.harness)["name"]
        m = read_manifest(base)
        channel = a.channel or (m or {}).get("channel") or "stable"
        src = resolve(a.harness, channel, scratch)
        try:
            h: Harness | None = load_harness(src.root, a.scope, base)
        except Refused:
            h = None
        drift = check(h, src.digest, src.revision, base, channel)
        if h and h.problems:
            drift += [f"checkout: {x}" for x in h.problems]
        for d in drift:
            print(f"  {d}")
        print(f"{'drift' if drift else 'clean'}: {name}@{channel} in {base}")
        return 1 if drift else 0

    src = resolve(a.harness, a.channel or "stable", scratch)
    h = load_harness(src.root, a.scope, base)
    if src.commit:
        h.source = {"commit": src.commit, "dirty": False}
        if a.scope == "user":
            h.source["path"] = str(a.harness.resolve())
    elif h.source.get("dirty") is not False and not a.allow_dirty:
        why = "has uncommitted changes" if h.source.get("dirty") else "is not in a git checkout"
        raise Refused(f"{a.harness} {why}, so it may not be what {h.name}@{src.channel} pins; commit or stash them, "
                      "or pass --allow-dirty")
    if h.problems:
        raise Refused("the checkout doesn't match its lock, so it isn't what the lock pins:\n  "
                      + "\n  ".join(h.problems) + "\nrun scripts/relock.py, or check out a committed revision")
    p = plan_install(h, base)
    print(_header(h, src, a.scope, base))
    for action, rel in p.files:
        if action != "keep":
            print(f"  {action:<7} {rel}" + ("  (already these bytes)" if action == "adopt" else ""))
    kept = sum(1 for x, _ in p.files if x == "keep")
    if kept:
        print(f"  keep    {kept} file(s) unchanged")
    if p.guide_import:
        print(f"  CLAUDE.md + {p.guide_import}")
    for sp in p.sfiles.values():
        for line in sp.lines:
            print(f"  {sp.name} {line}")
    if p.gitignore_add and p.gitignore:
        print(f"  {p.gitignore['file']} + {p.gitignore['line']}")
    for rel in p.left:
        print(f"  warning: {rel} is no longer in the harness but was edited; left in place", file=sys.stderr)
    for n in p.notes:
        print(f"  note: {n}")
    if a.scope == "user" and (h.settings.get("hooks") or h.settings.get("permissions")):
        print("  note: user scope applies these hooks and deny rules to every Claude Code session on this machine; "
              "--scope project limits them to one repository")
    if p.conflicts:
        print("refused, nothing written:", file=sys.stderr)
        for c in p.conflicts:
            print(f"  conflict: {c}", file=sys.stderr)
        return 1
    runtime, model = h.lock["runtime"], h.lock["model"]
    print(f"  pinned: Claude Code {runtime.get('version')}, model {model.get('id')} (not installed by this script)")
    cmds = mcp_commands(h, a.scope)
    if cmds:
        where = "" if a.scope == "user" else f", from {a.target}"
        print(f"MCP servers: run these yourself{where}, after setting each $VARIABLE from your secret manager "
              "(its value is the whole header, such as `Bearer <token>`):")
        for c in cmds:
            print(f"  {c}")
    plugins = plugin_commands(h, a.scope)
    if plugins:
        print("Plugins: run these yourself:")
        for c in plugins:
            print(f"  {c}")
    m = read_manifest(base)
    changes = (any(x != "keep" for x, _ in p.files) or any(sp.settings is not None for sp in p.sfiles.values())
               or p.guide_import is not None or p.gitignore_add or m is None or m.get("channel") != src.channel)
    if not a.apply:
        print("dry run: nothing written; run again with --apply" if changes else "up to date")
        return 0
    apply_install(h, p, a.scope, src.channel)
    print(f"installed {h.name}@{src.channel} r{h.revision} into {base}" if changes else "up to date")
    dead = probe_hooks(base, a.scope, [r for sp in p.sfiles.values() for r in sp.records])
    for d in dead:
        print(f"error: {d}", file=sys.stderr)
    if dead:
        print("installed, but Claude Code skips a hook that can't start: fix the interpreter or path, then run "
              "--check", file=sys.stderr)
    return 1 if dead else 0


if __name__ == "__main__":
    sys.exit(main())
