#!/usr/bin/env python3
"""Copy the shared work-system layer into every harness that carries it, or check that it is in sync.

`shared/work-system/` is the one place the work-system skills and hook are edited. `targets.yaml` names the
harnesses and pieces. For each target harness this:

- copies `shared/work-system/skills/<name>/` to `harnesses/<h>/skills/<name>/` (the whole directory);
- copies the hook to `harnesses/<h>/native/claude-code/hooks/`;
- checks that the harness's `native/claude-code/settings.json` registers the hook on PreToolUse for Bash and MCP
  tools (it never edits settings.json: that file is the harness's own).

    python scripts/sync_shared.py            # write the copies
    python scripts/sync_shared.py --check    # CI: exit 1 when a copy differs or the hook is not registered

After a write, re-pin each changed harness (`python scripts/relock.py harnesses/<h> --write`) and re-render its
environments (`python scripts/render_envs.py harnesses/<h>`).
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SHARED = ROOT / "shared" / "work-system"


def _files(d: Path) -> dict[str, bytes]:
    return {str(p.relative_to(d)): p.read_bytes() for p in sorted(d.rglob("*")) if p.is_file()}


def plan(root: Path = ROOT) -> tuple[list[tuple[Path, Path]], list[str]]:
    """(source, destination) pairs that are out of sync, and settings.json problems."""
    shared = root / "shared" / "work-system"
    t = yaml.safe_load((shared / "targets.yaml").read_text())
    stale: list[tuple[Path, Path]] = []
    problems: list[str] = []
    hook_src = shared / t["hook"]
    for h in t["harnesses"]:
        hd = root / "harnesses" / h
        if not hd.is_dir():
            problems.append(f"{h}: harnesses/{h} does not exist")
            continue
        for s in t["skills"]:
            src, dst = shared / "skills" / s, hd / "skills" / s
            if not dst.is_dir() or _files(src) != _files(dst):
                stale.append((src, dst))
        dst = hd / "native" / "claude-code" / "hooks" / hook_src.name
        if not dst.is_file() or dst.read_bytes() != hook_src.read_bytes():
            stale.append((hook_src, dst))
        settings = hd / "native" / "claude-code" / "settings.json"
        try:
            pre = json.loads(settings.read_text()).get("hooks", {}).get("PreToolUse", [])
        except (OSError, ValueError) as e:
            problems.append(f"{h}: cannot read {settings.relative_to(root)}: {e}")
            continue
        entries = [e for e in pre if any(x.get("command") == t["hook_command"] for x in e.get("hooks", []))]
        matchers = " ".join(e.get("matcher", "") for e in entries)
        if not entries:
            problems.append(f"{h}: settings.json does not register {t['hook_command']!r} on PreToolUse")
        elif "Bash" not in matchers or "mcp__" not in matchers:
            problems.append(f"{h}: the work-system hook must match Bash and mcp__ tools (matcher: {matchers!r})")
    return stale, problems


def write(stale: list[tuple[Path, Path]]) -> None:
    for src, dst in stale:
        if src.is_dir():
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(src, dst)
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
        print(f"synced {dst.relative_to(ROOT)}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--check", action="store_true", help="exit 1 when a copy differs; write nothing")
    args = ap.parse_args(argv)
    stale, problems = plan()
    if args.check:
        for src, dst in stale:
            print(f"error: {dst.relative_to(ROOT)} differs from {src.relative_to(ROOT)} "
                  "(edit shared/work-system/, then python scripts/sync_shared.py)", file=sys.stderr)
    else:
        write(stale)
    for p in problems:
        print(f"error: {p}", file=sys.stderr)
    if (args.check and stale) or problems:
        return 1
    print("shared work-system layer in sync")
    return 0


if __name__ == "__main__":
    sys.exit(main())
