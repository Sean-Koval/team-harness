#!/usr/bin/env python3
"""Install a harness into Claude Code on a laptop, pinned to its `harness.lock`, and keep it that way.

hangar renders a harness into a sandbox's `~/.claude`; this does the same for a person's own machine, so a teammate
running Claude Code locally gets the same skills, hooks, guide and deny rules as an agent in hangar.

    python scripts/install_local.py harnesses/work-default --scope user                # print the plan (dry run)
    python scripts/install_local.py harnesses/work-default --scope user --apply        # install or upgrade
    python scripts/install_local.py harnesses/work-default --scope user --check        # exit 1 on drift
    python scripts/install_local.py harnesses/work-default --scope user --uninstall
    python scripts/install_local.py harnesses/work-default --scope project --target ~/src/svc --apply

Scopes. `user` writes under `<home>/.claude/` (`--home`, default your home): skills to `skills/<name>/`, hooks to
`hooks/`, the guide to `CLAUDE.md`. `project` writes the same under `<target>/.claude/` (`--target`, default the
current directory) and rewrites hook commands from `$HOME/.claude/hooks/...` to
`"$CLAUDE_PROJECT_DIR"/.claude/hooks/...`.

What it never does:

- Overwrite a file it didn't install, unless that file already holds the new bytes (it is then adopted). Any other
  clash refuses the whole install before anything is written.
- Replace your own `CLAUDE.md`. The guide then goes to `team-harness/<harness>.md` beside it, and the plan prints the
  one `@team-harness/<harness>.md` line to add to your `CLAUDE.md`.
- Drop your settings. `settings.json` is merged: the harness's hook groups and permission rules are added, your own
  entries are kept, and only entries this script added are ever removed.
- Install from a checkout that doesn't match its lock: every pinned digest is checked first.
- Touch MCP servers or credentials. It prints the `claude mcp add` commands for the lock's servers, with each
  credential as a `$VARIABLE` placeholder for you to fill from your secret manager. Plugins are printed the same way.
- Install two harnesses into one scope: `--uninstall` the first (work and personal harnesses stay apart).

The manifest `.claude/team-harness.json` records the harness, its revision and `harness_digest`, the source commit,
the settings entries added and the SHA-256 of every file written. `--check` reports an edited or missing file, a
removed settings entry, or a newer harness revision in the checkout. `--uninstall` removes only files whose digest
still matches, leaving an edited file in place with a warning.

Exit codes: 0 done or clean, 1 refused or drift, 2 bad input. Needs Python 3.10+ and PyYAML.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

SCHEMA = "team-harness.install/v1"
MANIFEST = "team-harness.json"
RUNTIME = "claude-code"
NATIVE = f"native:{RUNTIME}/"
SETTINGS = "settings.json"
_MCP_FIELDS = (("endpoint", "url"), ("header_names", "headers"), ("env_names", "env"), ("command", "command"),
               ("args", "args"))
_HOME_HOOK = re.compile(r'"?(?:\$HOME|\$\{HOME\}|~)/\.claude/hooks/([^"\s]+)"?')


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
    channels: list[str] = field(default_factory=list)
    source: dict[str, Any] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)  # where the checkout differs from the lock


def _git(root: Path, *args: str) -> str | None:
    try:
        r = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, timeout=10,
                           check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def _rel_ok(rel: str) -> bool:
    p = Path(rel)
    return bool(rel) and not p.is_absolute() and ".." not in p.parts


def load_harness(root: Path, scope: str) -> Harness:
    lock_file = root / "harness.lock"
    try:
        lock = yaml.safe_load(lock_file.read_text())
    except (OSError, yaml.YAMLError) as e:
        raise Refused(f"{lock_file}: {e}") from None
    if not isinstance(lock, dict) or lock.get("schema") != "hangar.harness-lock/v1":
        raise Refused(f"{lock_file}: not a hangar.harness-lock/v1 lock")
    if (lock.get("runtime") or {}).get("harness") != RUNTIME:
        raise Refused(f"{lock_file}: runtime is {lock.get('runtime', {}).get('harness')!r}; only {RUNTIME} "
                      "harnesses install locally")
    h = Harness(root=root, lock=lock, name=lock["name"], revision=int(lock["revision"]), digest=harness_digest(lock))

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
    h.settings = _scoped_settings(h.settings, scope, src=root / "native" / RUNTIME / SETTINGS)

    channels_file = root.parent.parent / "channels.yaml"
    if channels_file.is_file():
        chans = (yaml.safe_load(channels_file.read_text()) or {}).get(h.name) or {}
        h.channels = sorted(k for k, v in chans.items() if v == h.digest)
    commit = _git(root, "rev-parse", "HEAD")
    dirty = _git(root, "status", "--porcelain", "--", ".")
    h.source = {"path": str(root.resolve()), "commit": commit, "dirty": bool(dirty) if dirty is not None else None}
    return h


def _scoped_settings(s: dict[str, Any], scope: str, src: Path) -> dict[str, Any]:
    """The harness's settings with only what this script merges, hook commands rewritten for the scope."""
    s = {k: v for k, v in s.items() if k != "$schema"}
    extra = set(s) - {"hooks", "permissions"}
    if extra:
        raise Refused(f"{src}: install_local.py merges only hooks and permissions, not {sorted(extra)}")
    for k, v in (s.get("permissions") or {}).items():
        if not isinstance(v, list):
            raise Refused(f"{src}: permissions.{k} is not a list of rules; install_local.py can't merge it")
    if scope == "project":
        s = copy.deepcopy(s)
        for groups in (s.get("hooks") or {}).values():
            for g in groups:
                for hk in g.get("hooks") or []:
                    if isinstance(hk.get("command"), str):
                        hk["command"] = _HOME_HOOK.sub(r'"$CLAUDE_PROJECT_DIR"/.claude/hooks/\1', hk["command"])
    return s


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
class Plan:
    base: Path
    files: list[tuple[str, str]] = field(default_factory=list)  # (action, path) write|update|adopt|keep|remove
    left: list[str] = field(default_factory=list)  # managed files edited since: left alone
    conflicts: list[str] = field(default_factory=list)
    settings_lines: list[str] = field(default_factory=list)
    settings: dict[str, Any] | None = None  # the merged settings, None when unchanged
    records: list[dict[str, Any]] = field(default_factory=list)
    settings_created: bool = False
    guide_rel: str | None = None
    notes: list[str] = field(default_factory=list)


def base_dir(scope: str, home: Path, target: Path) -> Path:
    return (home if scope == "user" else target).expanduser() / ".claude"


def read_manifest(base: Path) -> dict[str, Any] | None:
    f = base / MANIFEST
    if not f.is_file():
        return None
    try:
        m = json.loads(f.read_text())
    except ValueError as e:
        raise Refused(f"{f}: {e}") from None
    if m.get("schema") != SCHEMA:
        raise Refused(f"{f}: not a {SCHEMA} manifest")
    return m


def _read_settings(base: Path) -> dict[str, Any] | None:
    f = base / SETTINGS
    if not f.exists():
        return None
    try:
        s = json.loads(f.read_text() or "{}")
    except ValueError as e:
        raise Refused(f"{f}: not valid JSON ({e}); fix it first, nothing is merged into a file that can't be read")
    if not isinstance(s, dict):
        raise Refused(f"{f}: not a JSON object")
    return s


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
    want = dict(h.files)

    # the guide: CLAUDE.md unless that is someone else's file, then beside it
    if h.guide is not None:
        cur = base / "CLAUDE.md"
        mine = "CLAUDE.md" in managed
        if not cur.exists() or cur.read_bytes() == h.guide or (mine and sha(cur.read_bytes()) == managed["CLAUDE.md"]):
            p.guide_rel = "CLAUDE.md"
        elif mine:
            p.conflicts.append("CLAUDE.md: edited since this script installed it; restore it, or move your edits "
                               "to another file and delete it, then run again")
            p.guide_rel = "CLAUDE.md"
        else:
            p.guide_rel = f"team-harness/{h.name}.md"
            line = f"@team-harness/{h.name}.md"
            if line not in cur.read_text(errors="replace").splitlines():
                p.notes.append(f"{cur} is your own, so the guide goes to {base / p.guide_rel}. Add this line to "
                               f"{cur} to load it:\n      {line}")
        if p.guide_rel and not any(c.startswith("CLAUDE.md:") for c in p.conflicts):
            want[p.guide_rel] = (h.guide, 0o644)

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
    cur_s = _read_settings(base)
    p.settings_created = cur_s is None if old is None else bool((old.get("settings") or {}).get("created"))
    s = copy.deepcopy(cur_s or {})
    ours = [_unrecord(r) for r in ((old or {}).get("settings") or {}).get("entries") or []]
    new = _entries(h.settings)
    for e in ours:
        if e not in new and _remove(s, e):
            p.settings_lines.append(f"- {_describe(e)}")
    for e in new:
        if e in ours and _has(s, e):
            p.records.append(_record(e))
        elif e not in ours and _has(s, e):
            p.notes.append(f"settings.json already has {_describe(e)}; it stays yours")
        else:
            _add(s, e)
            p.records.append(_record(e))
            p.settings_lines.append(f"+ {_describe(e)}")
    if s != (cur_s or {}) or (cur_s is None and s):
        p.settings = s
    return p


def _write(f: Path, data: bytes, mode: int | None = None) -> None:
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


def apply_install(h: Harness, p: Plan, scope: str) -> None:
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
    if p.settings is not None:
        _write(p.base / SETTINGS, _settings_bytes(p.settings))
    manifest = {
        "schema": SCHEMA, "harness": h.name, "revision": h.revision, "harness_digest": h.digest,
        "channels": h.channels, "scope": scope, "source": h.source, "guide": p.guide_rel,
        "settings": {"created": p.settings_created, "entries": p.records},
        "files": dict(sorted(digests.items())),
    }
    data = (json.dumps(manifest, indent=2) + "\n").encode()
    if not (p.base / MANIFEST).is_file() or _strip_source(p.base / MANIFEST) != _strip_source(data):
        _write(p.base / MANIFEST, data, 0o644)


def _strip_source(x: Path | bytes) -> Any:
    """A manifest without its source block, so a re-run from another commit of the same lock writes nothing."""
    m = json.loads(x.read_bytes() if isinstance(x, Path) else x)
    m.pop("source", None)
    return m


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
    def quoted(text: str, var: str) -> str:
        return f'"{text}${var}"' if scope == "user" else f"'{text}${{{var}}}'"

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
                out.append(f"claude plugin marketplace add {h.root.resolve() / 'plugins' / mkt}")
            out.append(f"claude plugin install {name}@{mkt} --scope {scope}")
    return out


# --- check, uninstall -------------------------------------------------------------------------------------------

def check(h: Harness | None, lock_digest: str | None, lock_rev: int | None, base: Path) -> list[str]:
    m = read_manifest(base)
    if m is None:
        return [f"not installed: {base / MANIFEST} is missing"]
    drift = []
    if h is not None and m["harness"] != h.name:
        drift.append(f"{base} has {m['harness']} installed, not {h.name}")
    for rel, dg in sorted((m.get("files") or {}).items()):
        f = base / rel
        if not f.is_file():
            drift.append(f"missing: {rel}")
        elif sha(f.read_bytes()) != dg:
            drift.append(f"edited: {rel}")
    s = _read_settings(base) or {}
    for r in (m.get("settings") or {}).get("entries") or []:
        if not _has(s, _unrecord(r)):
            drift.append(f"settings.json no longer has {_describe(_unrecord(r))}")
    if lock_digest and lock_digest != m["harness_digest"]:
        newer = lock_rev is not None and lock_rev > int(m["revision"])
        drift.append(f"{'newer harness revision' if newer else 'the harness changed'}: r{lock_rev} {lock_digest} "
                     f"in the checkout, r{m['revision']} {m['harness_digest']} installed; run --apply to upgrade")
    return drift


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
    cur = _read_settings(base)
    if cur is not None:
        s = copy.deepcopy(cur)
        for r in (m.get("settings") or {}).get("entries") or []:
            if _remove(s, _unrecord(r)):
                removed.append(f"settings.json: {_describe(_unrecord(r))}")
            else:
                left.append(f"settings.json: {_describe(_unrecord(r))}: changed or already gone")
        if not s and (m.get("settings") or {}).get("created"):
            (base / SETTINGS).unlink()
        elif s != cur:
            _write(base / SETTINGS, _settings_bytes(s))
    (base / MANIFEST).unlink()
    return removed, left


# --- CLI --------------------------------------------------------------------------------------------------------

def _lock_or_none(root: Path) -> dict[str, Any] | None:
    try:
        lock = yaml.safe_load((root / "harness.lock").read_text())
    except (OSError, yaml.YAMLError):
        return None
    return lock if isinstance(lock, dict) else None


def _header(h: Harness, scope: str, base: Path) -> str:
    chan = f" ({', '.join(h.channels)})" if h.channels else ""
    src = h.source.get("commit") or "no git commit"
    if h.source.get("dirty"):
        src += ", uncommitted changes"
    return f"{h.name} r{h.revision} {h.digest}{chan} from {src} -> {scope} scope, {base}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("harness", type=Path, help="the harness directory (holds harness.lock)")
    ap.add_argument("--scope", choices=("user", "project"), required=True)
    ap.add_argument("--home", type=Path, default=Path.home(), help="user scope: the home whose .claude/ to write")
    ap.add_argument("--target", type=Path, default=Path.cwd(), help="project scope: the project directory")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="print the plan and write nothing (the default)")
    mode.add_argument("--apply", action="store_true", help="install or upgrade")
    mode.add_argument("--check", action="store_true", help="exit 1 when the install drifted or the harness is newer")
    mode.add_argument("--uninstall", action="store_true", help="remove what this script installed")
    a = ap.parse_args(argv)
    base = base_dir(a.scope, a.home, a.target)
    try:
        if a.uninstall:
            lock = _lock_or_none(a.harness)
            m = read_manifest(base)
            if lock and m and m["harness"] != lock.get("name"):
                raise Refused(f"{base} has {m['harness']} installed, not {lock.get('name')}; name that harness")
            removed, left = uninstall(base)
            for r in removed:
                print(f"  removed {r}")
            for r in left:
                print(f"  warning: left {r}", file=sys.stderr)
            print(f"uninstalled from {base}")
            return 0
        if a.check:
            lock = _lock_or_none(a.harness) or {}
            try:
                h: Harness | None = load_harness(a.harness, a.scope)
            except Refused:
                h = None
            rev = lock.get("revision")
            drift = check(h, harness_digest(lock) if lock else None, int(rev) if rev is not None else None, base)
            if h and h.problems:
                drift += [f"checkout: {x}" for x in h.problems]
            for d in drift:
                print(f"  {d}")
            print(f"{'drift' if drift else 'clean'}: {lock['name']} in {base}")
            return 1 if drift else 0

        h = load_harness(a.harness, a.scope)
        if h.problems:
            raise Refused("the checkout doesn't match its lock, so it isn't what the lock pins:\n  "
                          + "\n  ".join(h.problems) + "\nrun scripts/relock.py, or check out a committed revision")
        p = plan_install(h, base)
        print(_header(h, a.scope, base))
        for action, rel in p.files:
            if action != "keep":
                print(f"  {action:<7} {rel}" + ("  (already these bytes)" if action == "adopt" else ""))
        kept = sum(1 for x, _ in p.files if x == "keep")
        if kept:
            print(f"  keep    {kept} file(s) unchanged")
        for line in p.settings_lines:
            print(f"  settings.json {line}")
        for rel in p.left:
            print(f"  warning: {rel} is no longer in the harness but was edited; left in place", file=sys.stderr)
        for n in p.notes:
            print(f"  note: {n}")
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
        changes = any(x != "keep" for x, _ in p.files) or p.settings is not None or read_manifest(base) is None
        if not a.apply:
            print("dry run: nothing written; run again with --apply" if changes else "up to date")
            return 0
        apply_install(h, p, a.scope)
        print(f"installed {h.name} r{h.revision} into {base}" if changes else "up to date")
        return 0
    except Refused as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
