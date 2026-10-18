#!/usr/bin/env python3
"""Re-pin a harness directory's files in its `harness.lock`, with hangar's own digest code.

The normal way to get a lock is `hangar harness freeze` from a turn that went well. Use this when you change the
harness's files by hand (a new skill, an edited guide, your own MCP endpoints) and want the lock to pin them before a
run exists to freeze from: it keeps the lock's runtime, model and binding layer, recomputes every component's digest
(and each skill's `tree`), adds components for unpinned skills, plugins and native files, and bumps the revision when
anything changed. `hangar harness check` then passes, and a turn run from the result reports the same
`harness_digest` once the environment provides the same files.

    python scripts/relock.py harnesses/team-default            # print what would change
    python scripts/relock.py harnesses/team-default --write    # write harness.lock
    python scripts/relock.py harnesses/team-default --without-plugins --print-digest

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

GUIDES = ("CLAUDE.md", "AGENTS.md")  # the first one present is the guide component
CONFIG_ROOTS = {"claude-code": ".claude", "codex": ".codex"}  # native/<runtime>/ maps onto $HOME/<this>/


def _marketplace(root: Path) -> str | None:
    f = root / ".claude-plugin" / "marketplace.json"
    try:
        return json.loads(f.read_text())["name"]
    except (OSError, ValueError, KeyError):
        return None


def _hooks(root: Path, lock: dict[str, Any]) -> list[dict[str, Any]]:
    """binding.hooks as hangar's manifest records them: hangar's own hooks (kept from the lock), then each event
    of every native `settings.json` in path order, sourced `environment:<path under $HOME>` with the file's digest."""
    runtime = lock["runtime"]["harness"]
    home_dir = CONFIG_ROOTS.get(runtime)
    out = [h for h in lock["binding"].get("hooks") or [] if not str(h.get("source", "")).startswith("environment:")]
    base = root / "native" / runtime
    if home_dir is None or not base.is_dir():
        return out
    for f in sorted(p for p in base.rglob("settings.json") if p.is_file()):
        data = f.read_bytes()
        for event in (json.loads(data).get("hooks") or {}):
            out.append({"event": event, "source": f"environment:{home_dir}/{f.relative_to(base).as_posix()}",
                        "digest": hl._sha(data)})
    return out


def relock(root: Path, *, without_plugins: bool = False) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """(new lock, previous lock) for the harness directory `root`."""
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
        market = _marketplace(root)
        if market is None:
            raise SystemExit(f"{root}/.claude-plugin/marketplace.json: a plugin needs the marketplace that lists it")
        for d in sorted(p for p in (root / "plugins").iterdir() if p.is_dir()):
            cid = f"plugin:{d.name}@{market}"
            c = {"id": cid, "digest": hl.files_digest(hl.read_dir(d)), "path": f"plugins/{d.name}"}
            c["enabled"] = (old.get(cid) or {}).get("enabled", True)
            if src := (old.get(cid) or {}).get("source"):
                c["source"] = src
            comps.append(c)

    if (root / "native").is_dir():
        for f in sorted(p for p in (root / "native").rglob("*") if p.is_file() and not p.is_symlink()):
            rel = f.relative_to(root).as_posix()
            runtime_path = rel.removeprefix("native/")
            comps.append({"id": f"native:{runtime_path}", "digest": hl._sha(f.read_bytes()), "path": rel})

    lock["components"] = comps
    lock["binding"]["hooks"] = _hooks(root, lock)
    # a skeleton (no components yet) is a new harness: revision 1
    lock["revision"] = 1 if not prev["components"] else hl.next_revision(prev, lock)
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
    a = ap.parse_args()
    lock, prev = relock(a.harness, without_plugins=a.without_plugins)
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
