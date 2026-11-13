#!/usr/bin/env python3
"""Re-pin a harness directory's files in its `harness.lock`, with hangar's own digest code.

The normal way to get a lock is `hangar harness freeze` from a turn that went well. Use this when you change the
harness's files by hand (a new skill, an edited guide, your own MCP endpoints) and want the lock to pin them before a
run exists to freeze from: it keeps the lock's runtime, model and binding layer (but MCP servers come from
`bindings/<name>.yaml` when its servers declare a `transport`), recomputes every component's digest
(and each skill's `tree`), adds components for unpinned skills, plugins (each `plugins/<marketplace>/` directory marketplace) and native files, and bumps the revision when
anything changed. `hangar harness check` then passes, and a turn run from the result reports the same
`harness_digest` once the environment provides the same files.

The digest covers every file the harness runs (KAN-473). hangar's identity takes a native `settings.json` only through
its hook entries' digest, so the settings file is pinned as `render_envs.py` provides it, with
`env.HARNESS_NATIVE_DIGEST` over the other native files (the hook scripts and what they call). Relock refuses a
result whose pinned files changed while `harness_digest` did not, and a harness whose native files no hook entry
covers. `--rekey` recomputes the digest of unchanged files and keeps the revision: use it when only the digest's form
changed, so a channel can name the same content at its new digest.

    python scripts/relock.py harnesses/team-default            # print what would change
    python scripts/relock.py harnesses/team-default --write    # write harness.lock
    python scripts/relock.py harnesses/team-default --without-plugins --print-digest
    python scripts/relock.py harnesses/work-default --rekey --write   # same files, new digest form, same revision

Needs hangar importable (`pip install "hangar @ git+https://github.com/Sean-Koval/hangar@<ref>"`).
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any

import yaml

from hangar import harness_lock as hl

sys.path.insert(0, str(Path(__file__).resolve().parent))
from render_envs import SETTINGS, native_files  # noqa: E402

GUIDES = ("CLAUDE.md", "AGENTS.md")  # the first one present is the guide component
CONFIG_ROOTS = {"claude-code": ".claude", "codex": ".codex"}  # native/<runtime>/ maps onto $HOME/<this>/



def _hooks(root: Path, lock: dict[str, Any]) -> list[dict[str, Any]]:
    """binding.hooks as hangar's manifest records them: hangar's own hooks (kept from the lock), then each event
    of every native `settings.json` in path order, sourced `environment:<path under $HOME>` with the digest of the
    file as the environment provides it (`render_envs.native_files`: it names the other native files' digest)."""
    runtime = lock["runtime"]["harness"]
    home_dir = CONFIG_ROOTS.get(runtime)
    out = [h for h in lock["binding"].get("hooks") or [] if not str(h.get("source", "")).startswith("environment:")]
    base = root / "native" / runtime
    if home_dir is None or not base.is_dir():
        return out
    provided = native_files(root, runtime)
    for rel in sorted(k for k in provided if k.rsplit("/", 1)[-1] == SETTINGS):
        text = provided[rel]
        for event in (json.loads(text).get("hooks") or {}):
            out.append({"event": event, "source": f"environment:{home_dir}/{rel}", "digest": hl._sha(text.encode())})
    return out


MCP_SHAPE = {"http": ("endpoint",), "stdio": ("command", "args")}  # what the lock pins of each transport


def bindings_file(root: Path, name: str) -> Path | None:
    """The repository's `bindings/<name>.yaml` above the harness directory `root`, as render_envs.py finds it."""
    repo = next((p for p in root.resolve().parents if (p / "bindings").is_dir()), None)
    f = repo / "bindings" / f"{name}.yaml" if repo else None
    return f if f and f.is_file() else None


def _mcp(root: Path, lock: dict[str, Any]) -> list[dict[str, Any]]:
    """binding.mcp built from `bindings/<name>.yaml` when its servers declare a `transport` (KAN-459), so a server
    added, renamed or moved is a source change and the build writes the lock; otherwise the lock's, as before.
    One entry per server in name order: name, transport, then `endpoint` (http) or `command` and `args` (stdio), and
    the names of its headers or env, never their values."""
    f = bindings_file(root, lock["name"])
    servers = ((yaml.safe_load(f.read_text()) or {}).get("mcp") or {}) if f else {}
    declared = {n for n, s in servers.items() if isinstance(s, dict) and "transport" in s}
    if not declared:
        return lock["binding"].get("mcp") or []
    if declared != set(servers):
        raise SystemExit(f"{f}: give every mcp server a transport, or none (missing: "
                         f"{', '.join(sorted(set(servers) - declared))})")
    out = []
    for name in sorted(servers):
        s = servers[name]
        shape = MCP_SHAPE.get(s["transport"])
        if shape is None or any(k not in s for k in shape):
            raise SystemExit(f"{f}: mcp.{name}: transport http needs endpoint; stdio needs command and args")
        m: dict[str, Any] = {"name": name, "transport": s["transport"]}
        m.update({k: (list(s[k]) if k == "args" else s[k]) for k in shape})
        names = sorted(s.get("headers" if s["transport"] == "http" else "env") or {})
        if names:
            m["header_names" if s["transport"] == "http" else "env_names"] = names
        out.append(m)
    return out


def pinned(lock: dict[str, Any]) -> dict[str, str]:
    """{component id: digest} of what a lock pins by content."""
    return {c["id"]: c["digest"] for c in lock.get("components") or [] if c.get("digest")}


def coverage_problems(root: Path, lock: dict[str, Any]) -> list[str]:
    """Native files no hook entry's digest covers: hangar's identity would not change when they do."""
    runtime = lock["runtime"]["harness"]
    provided = native_files(root, runtime)
    if not any(k.rsplit("/", 1)[-1] != SETTINGS for k in provided):
        return []
    if any(str(h.get("source", "")).startswith("environment:") for h in lock["binding"].get("hooks") or []):
        return []
    return [(f"{root}: native/{runtime}/ has files but no settings.json with hooks, so harness_digest would not "
             "cover them")]


def relock(root: Path, *, without_plugins: bool = False, rekey: bool = False
           ) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """(new lock, previous lock) for the harness directory `root`. `rekey`: the files must be the previous lock's;
    only the digest is recomputed and the revision stays."""
    lock_file = root / hl.LOCK_FILE
    prev = yaml.safe_load(lock_file.read_text()) if lock_file.is_file() else None
    if prev is None:
        raise SystemExit(f"{lock_file}: start from a lock (hangar harness freeze, or a skeleton with runtime, model "
                         "and binding and `components: []`)")
    hl.validate(prev)
    lock = copy.deepcopy(prev)
    old = {c["id"]: c for c in prev["components"]}
    comps: list[dict[str, Any]] = []

    guide = next((g for g in GUIDES if (root / g).is_file()), None)
    if guide:
        comps.append({"id": f"guide:{guide}", "digest": hl._sha((root / guide).read_bytes()), "path": guide})

    # skills: the lock's order first (it is identity), then new ones by name
    have = sorted(d.name for d in (root / "skills").iterdir() if d.is_dir()) if (root / "skills").is_dir() else []
    order = [c["id"][6:] for c in prev["components"] if c["id"].startswith("skill:")]
    for name in [n for n in order if n in have] + [n for n in have if n not in order]:
        files = hl.read_dir(root / "skills" / name)
        c = {"id": f"skill:{name}", "digest": hl.files_digest(files), "tree": hl.tree_digest(files),
             "path": f"skills/{name}"}
        c["source"] = (old.get(c["id"]) or {}).get("source") or f"path:skills/{name}"
        comps.append(c)
    for c in prev["components"]:  # references (pinned git skills, hangar's own) carry over as they are
        if c.get("digest") is None and c["id"].startswith("skill:"):
            comps.append(c)

    if not without_plugins and (root / "plugins").is_dir():
        # each directory under plugins/ is a Claude Code directory marketplace (hangar#221): its
        # .claude-plugin/marketplace.json lists the plugins, each at plugins/<marketplace>/<its ./ source>
        for mdir in sorted(p for p in (root / "plugins").iterdir() if p.is_dir()):
            entries = hl.marketplace_entries(root, mdir.name)
            if entries is None:
                raise SystemExit(f"{mdir}/.claude-plugin/marketplace.json: missing, or not marketplace {mdir.name}")
            for name, entry in sorted(entries.items()):
                src = entry.get("source")
                if not isinstance(src, str) or not src.startswith("./"):
                    raise SystemExit(f"{mdir}: plugin {name} needs a relative ./ source to be pinned")
                d = (mdir / src).resolve()
                files = hl.read_dir(d)
                cid = f"plugin:{name}@{mdir.name}"
                c = {"id": cid, "digest": hl.plugin_digest(entry, files), "tree": hl.tree_digest(files),
                     "path": d.relative_to(root.resolve()).as_posix()}
                c["enabled"] = (old.get(cid) or {}).get("enabled", True)
                if prov := (old.get(cid) or {}).get("source"):
                    c["source"] = prov
                comps.append(c)

    if (root / "native").is_dir():
        for f in sorted(p for p in (root / "native").rglob("*") if p.is_file() and not p.is_symlink()):
            rel = f.relative_to(root).as_posix()
            runtime_path = rel.removeprefix("native/")
            comps.append({"id": f"native:{runtime_path}", "digest": hl._sha(f.read_bytes()), "path": rel})

    lock["components"] = comps
    lock["binding"]["mcp"] = _mcp(root, lock)
    lock["binding"]["hooks"] = _hooks(root, lock)
    if problems := coverage_problems(root, lock):
        raise SystemExit("; ".join(problems))
    if rekey:
        if pinned(lock) != pinned(prev):
            changed = sorted(set(pinned(lock).items()) ^ set(pinned(prev).items()))
            raise SystemExit(f"{root}: --rekey keeps the files, but these differ from the lock: "
                             f"{', '.join(sorted({k for k, _ in changed}))}")
        lock["revision"] = prev["revision"]
    else:
        # a skeleton (no components yet) is a new harness: revision 1
        lock["revision"] = 1 if not prev["components"] else hl.next_revision(prev, lock)
    if rekey and lock["binding"]["mcp"] != prev["binding"].get("mcp"):
        raise SystemExit(f"{root}: --rekey keeps the binding, but bindings/ declares other MCP servers than the lock")
    if prev["components"] and pinned(lock) != pinned(prev) and hl.harness_digest(lock) == hl.harness_digest(prev):
        raise SystemExit(f"{root}: the pinned files changed but harness_digest did not; a channel naming it would "
                         "change without a promotion")
    hl.validate(lock)
    return lock, prev


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("harness", type=Path, help="the harness directory (holds harness.lock)")
    ap.add_argument("--write", action="store_true", help="write harness.lock (default: print it)")
    ap.add_argument("--without-plugins", action="store_true",
                    help="leave plugin components out (a harness without its plugins, e.g. a stable channel that "
                         "can't load them yet)")
    ap.add_argument("--print-digest", action="store_true", help="print only the harness_digest")
    ap.add_argument("--rekey", action="store_true",
                    help="the files are the lock's: recompute the digest in its current form and keep the revision")
    a = ap.parse_args()
    lock, prev = relock(a.harness, without_plugins=a.without_plugins, rekey=a.rekey)
    digest = hl.harness_digest(lock)
    if a.print_digest:
        print(digest)
        return 0
    if a.write:
        (a.harness / hl.LOCK_FILE).write_text(hl.dump(lock))
        print(f"{lock['name']} r{lock['revision']} {digest}", file=sys.stderr)
    else:
        sys.stdout.write(hl.dump(lock))
        same = prev is not None and hl.harness_digest(prev) == digest
        print(f"# {lock['name']} r{lock['revision']} {digest}" + (" (unchanged)" if same else ""), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
