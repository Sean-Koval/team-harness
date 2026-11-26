"""A harness lock's digests, file form and schema check, without hangar (KAN-600).

The same values and bytes as hangar's `harness_lock` at the ref CI pins (`HANGAR_REF` in the Makefile), so a company
can build its overlay's revision (`build_generated.py`, `relock.py`) with only Python and PyYAML.
`tests/test_harness_lockfile.py` holds every function here to hangar's own wherever hangar is installed, as it is in
CI; bump `HANGAR_REF` and that test says what moved. Checking a lock against its files (`hangar harness check`),
freezing and promoting still use hangar.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

import yaml

SCHEMA = "hangar.harness-lock/v1"
LOCK_FILE = "harness.lock"
KINDS = ("guide", "skill", "plugin", "native")
_MCP_FIELDS = (("endpoint", "url"), ("header_names", "headers"), ("env_names", "env"), ("command", "command"),
               ("args", "args"))


# --- digests ----------------------------------------------------------------------------------------------------

def sha(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


_sha = sha  # hangar's name, kept so callers read the same either way


def _canon(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def files_digest(files: dict[str, bytes]) -> str:
    """Per file in path-component order: the path, a NUL, and the raw SHA-256 of its content."""
    h = hashlib.sha256()
    for rel in sorted(files, key=lambda r: tuple(r.split("/"))):
        h.update(rel.encode() + b"\0")
        h.update(hashlib.sha256(files[rel]).digest())
    return "sha256:" + h.hexdigest()


def tree_digest(files: dict[str, bytes]) -> str:
    """`sha256sum` over each file as `./path`, in byte order (`sort -z` under LC_ALL=C), then the listing's SHA-256."""
    lines = []
    for rel in sorted(files, key=lambda r: ("./" + r).encode()):
        hexd, name = hashlib.sha256(files[rel]).hexdigest(), "./" + rel
        if "\\" in name or "\n" in name:  # GNU sha256sum escapes such names and marks the line
            lines.append("\\" + hexd + "  " + name.replace("\\", "\\\\").replace("\n", "\\n") + "\n")
        else:
            lines.append(hexd + "  " + name + "\n")
    return sha("".join(lines).encode())


def read_dir(root: Path) -> dict[str, bytes]:
    """{relative posix path: content} of the regular files under `root` (symlinks skipped, as the digests do)."""
    return {f.relative_to(root).as_posix(): f.read_bytes()
            for f in sorted(root.rglob("*")) if f.is_file() and not f.is_symlink()}


def _kind(cid: str) -> str:
    return cid.partition(":")[0]


def _cname(cid: str) -> str:
    return cid.partition(":")[2]


def plugin_ref(cid: str) -> dict[str, str]:
    """`plugin:<name>@<marketplace>` -> {name, marketplace}."""
    name, _, mkt = _cname(cid).rpartition("@")
    return {"name": name, "marketplace": mkt}


def plugin_digest(entry: dict[str, Any], files: dict[str, bytes]) -> str:
    """A plugin's digest from its marketplace entry and its files."""
    e = json.dumps(entry, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(f"{e}\n{files_digest(files)}".encode()).hexdigest()


def marketplace_entries(root: Path, mkt: str) -> dict[str, Any] | None:
    """{plugin name: entry} of `plugins/<mkt>/.claude-plugin/marketplace.json` under a harness directory; None when
    it can't be read or names another marketplace."""
    try:
        data = json.loads((root / "plugins" / mkt / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("name") != mkt or not isinstance(data.get("plugins"), list):
        return None
    return {e["name"]: e for e in data["plugins"] if isinstance(e, dict) and isinstance(e.get("name"), str)}


def identity(lock: dict[str, Any]) -> dict[str, Any]:
    """The lock's identity sections (hangar's `manifest.HARNESS_SECTIONS`, in order): what `harness_digest` covers."""
    runtime, model, binding = lock.get("runtime") or {}, lock.get("model") or {}, lock.get("binding") or {}
    comps = lock.get("components") or []
    guide = next((c for c in comps if _kind(c.get("id", "")) == "guide"), None)
    plugins = [plugin_ref(c["id"]) | {"digest": c.get("digest"), "enabled": c.get("enabled", True)}
               for c in comps if _kind(c.get("id", "")) == "plugin"]
    mcp = []
    for x in binding.get("mcp") or []:
        d = {"name": x.get("name"), "transport": x.get("transport")}
        for ours, theirs in _MCP_FIELDS:
            d[theirs] = x.get(ours)
        mcp.append(d)
    return {
        "harness.name": runtime.get("harness"),
        "harness.locked": runtime.get("version"),
        "model.id": model.get("id"),
        "instructions.global.declared.digest": guide.get("digest") if guide else None,
        "skills.declared[*].{name,digest}": [{"name": _cname(c["id"]), "digest": c.get("digest")}
                                             for c in comps if _kind(c.get("id", "")) == "skill"],
        "plugins[*].{name,marketplace,digest,enabled}": plugins or None,  # null without any, as the manifest's
        "mcp_servers[*].{name,transport,url,headers,env,command,args}": mcp,
        "hooks[*].{event,source,digest}": [{"event": x.get("event"), "source": x.get("source"),
                                           "digest": x.get("digest")} for x in binding.get("hooks") or []],
        "permissions.approvals": (binding.get("permissions") or {}).get("approvals"),
    }


def harness_digest(lock: dict[str, Any]) -> str:
    """The lock's identity: SHA-256 of the canonical JSON of `identity(lock)`."""
    return sha(_canon(identity(lock)).encode())


def next_revision(prev: dict[str, Any] | None, new: dict[str, Any]) -> int:
    """1 for a new harness; the previous revision when nothing but name and revision differ, else one more."""
    if prev is None:
        return 1

    def material(lock: dict[str, Any]) -> str:
        return _canon({k: v for k, v in lock.items() if k not in ("name", "revision")})

    return int(prev.get("revision") or 0) + (0 if material(prev) == material(new) else 1)


# --- the file ---------------------------------------------------------------------------------------------------

def dump(lock: dict[str, Any]) -> str:
    """The lock as YAML, keys in the schema's order (so diffs stay small)."""
    order = ("schema", "name", "revision", "runtime", "model", "components", "binding", "plugins", "remote")
    body = {k: lock[k] for k in order if k in lock} | {k: v for k, v in lock.items() if k not in order}
    return "# hangar harness lock (docs/harness-lock.md). Written by `hangar harness freeze`; identity is\n" \
           "# harness_digest, printed by `hangar harness check`.\n" + yaml.safe_dump(body, sort_keys=False,
                                                                                    allow_unicode=True, width=120)


def load(path: Path) -> dict[str, Any]:
    """A lock file (or a directory holding `harness.lock`), parsed and checked against the schema."""
    if path.is_dir():
        path = path / LOCK_FILE
    try:
        lock = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as e:
        raise ValueError(f"cannot read {path}: {e.strerror}") from None
    except yaml.YAMLError as e:
        raise ValueError(f"{path} is not YAML: {e}") from None
    validate(lock)
    return lock


_NAME = re.compile(r"^[a-z0-9][a-z0-9._-]{0,62}$")
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_ID = re.compile(r"^(guide|skill|plugin|native):\S{1,200}$")
_PLUGIN_ID = re.compile(r"^plugin:[A-Za-z0-9][A-Za-z0-9._-]{0,99}@[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")


def safe_path(p: Any) -> bool:
    """A relative path inside the harness directory: no absolute paths, `..`, backslashes or empty parts."""
    return isinstance(p, str) and bool(p) and not p.startswith("/") and "\\" not in p and "\0" not in p \
        and all(part not in ("", ".", "..") for part in p.split("/"))


def _component_problems(comps: list[Any]) -> list[str]:
    out: list[str] = []
    seen_ids: set[str] = set()
    seen_paths: list[str] = []
    for i, c in enumerate(comps):
        if not isinstance(c, dict) or not isinstance(c.get("id"), str) or not _ID.match(c["id"]):
            out.append(f"components[{i}].id: kind:name, kind one of {', '.join(KINDS)}")
            continue
        where = f"component {c['id']}"
        if c["id"] in seen_ids:
            out.append(f"{where}: listed twice")
        seen_ids.add(c["id"])
        d = c.get("digest")
        if d is None:
            if not c.get("source") or c.get("path") is not None:
                out.append(f"{where}: a component without a digest is a reference: give its source, no path")
        elif not isinstance(d, str) or not _DIGEST.match(d):
            out.append(f"{where}.digest: sha256:<64 hex>")
        if c.get("path") is not None:
            if not safe_path(c["path"]):
                out.append(f"{where}.path: a relative path inside the harness directory")
            elif any(c["path"] == p or c["path"].startswith(p + "/") or p.startswith(c["path"] + "/")
                     for p in seen_paths):
                out.append(f"{where}.path overlaps another component's")
            else:
                seen_paths.append(c["path"])
        elif d is not None:
            out.append(f"{where}: a component with a digest needs its path")
        if c.get("tree") is not None and (_kind(c["id"]) not in ("skill", "plugin")
                                          or not _DIGEST.match(str(c["tree"]))):
            out.append(f"{where}.tree: sha256:<64 hex>, skills and plugins only")
        if _kind(c["id"]) == "plugin":
            if not _PLUGIN_ID.match(c["id"]):
                out.append(f"{where}: plugin:<name>@<marketplace>")
            elif c.get("path") is not None and safe_path(c["path"]):
                mkt = f"plugins/{plugin_ref(c['id'])['marketplace']}"
                if c["path"] != mkt and not c["path"].startswith(mkt + "/"):
                    out.append(f"{where}.path: under {mkt}/ (its marketplace's directory)")
        if "enabled" in c and not isinstance(c["enabled"], bool):
            out.append(f"{where}.enabled: true or false")
    if sum(1 for x in seen_ids if _kind(x) == "guide") > 1:
        out.append("components: at most one guide (the harness's global instructions file)")
    return out


def problems(lock: Any) -> list[str]:
    """What's wrong with a lock document (empty: it is a valid `hangar.harness-lock/v1`)."""
    if not isinstance(lock, dict):
        return ["a harness lock is a mapping"]
    out: list[str] = []
    if lock.get("schema") != SCHEMA:
        out.append(f"schema must be {SCHEMA} (got {lock.get('schema')!r})")
    if not isinstance(lock.get("name"), str) or not _NAME.match(lock["name"]):
        out.append("name: lowercase letters, digits, '.', '_' or '-', at most 63")
    rev = lock.get("revision")
    if not isinstance(rev, int) or isinstance(rev, bool) or rev < 1:
        out.append("revision: an integer >= 1")
    rt = lock.get("runtime")
    if not isinstance(rt, dict) or not isinstance(rt.get("harness"), str) or not rt["harness"]:
        out.append("runtime.harness: the harness name (claude-code, codex, ...)")
    elif not all(isinstance(rt.get(k), (str, type(None))) for k in ("version", "pack")):
        out.append("runtime.version and runtime.pack: strings or null")
    md = lock.get("model")
    if not isinstance(md, dict) or not all(isinstance(md.get(k), (str, type(None))) for k in ("id", "policy")):
        out.append("model: {id, policy}, strings or null")
    comps = lock.get("components")
    if not isinstance(comps, list):
        out.append("components: a list")
        comps = []
    out += _component_problems(comps)
    b = lock.get("binding")
    if not isinstance(b, dict):
        out.append("binding: {mcp, hooks, permissions}")
    else:
        for i, x in enumerate(b.get("mcp") or []):
            if not isinstance(x, dict) or not isinstance(x.get("name"), str) or x.get("transport") not in (
                    "http", "stdio"):
                out.append(f"binding.mcp[{i}]: {{name, transport: http|stdio, ...}}")
            elif any(k in x for k in ("headers", "env", "url", "token")):
                out.append(f"binding.mcp[{i}]: names only (endpoint, header_names, env_names), never values")
        for i, x in enumerate(b.get("hooks") or []):
            if not isinstance(x, dict) or not x.get("event") or not x.get("source"):
                out.append(f"binding.hooks[{i}]: {{event, source, digest?}}")
        if not isinstance(b.get("permissions") or {}, dict):
            out.append("binding.permissions: {approvals}")
    pl = lock.get("plugins")
    if not isinstance(pl, dict) or pl.get("autoUpdate") is not False:
        out.append("plugins.autoUpdate must be false: a marketplace update would change the harness under its lock")
    rm = lock.get("remote")
    if not isinstance(rm, list) or not all(isinstance(x, dict) and x.get("id") for x in rm):
        out.append("remote: a list of {id, version}")
    return out


def validate(lock: Any) -> None:
    if errs := problems(lock):
        raise ValueError("invalid harness lock: " + "; ".join(errs))
