#!/usr/bin/env python3
"""Render the shared work-system layer into every harness that carries it, or check that it is in sync.

`shared/work-system/` is the one place the work-system skills and hook are edited. `targets.yaml` names the
harnesses, the pieces each one carries, and each harness's profile (`profiles/<harness>.yaml`). A shared file may hold
`{{name}}` placeholders; the profile's `params` fill them, so nothing person- or company-specific lives in a shared
file and each harness gets concrete text. For each target harness this:

- renders `shared/work-system/skills/<name>/` into `harnesses/<h>/skills/<name>/` (the whole directory), for the
  shared skill list plus the harness's own `skills:` from targets.yaml;
- renders the hook into `harnesses/<h>/native/claude-code/hooks/`;
- checks that the harness's `native/claude-code/settings.json` registers the hook on PreToolUse for Bash and MCP
  tools (it never edits settings.json: that file is the harness's own).

A placeholder the profile does not fill is an error, never an empty string.

    python scripts/sync_shared.py            # write the copies
    python scripts/sync_shared.py --check    # CI: exit 1 when a copy differs, a placeholder is unfilled, or the hook
                                             # is not registered

After a write, re-pin each changed harness (`python scripts/relock.py harnesses/<h> --write`) and re-render its
environments (`python scripts/render_envs.py harnesses/<h>`).
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SHARED = ROOT / "shared" / "work-system"
PLACEHOLDER = re.compile(r"\{\{\s*([a-z_][a-z0-9_]*)\s*\}\}")


def _files(d: Path) -> dict[str, bytes]:
    return {str(p.relative_to(d)): p.read_bytes() for p in sorted(d.rglob("*")) if p.is_file()}


def render(data: bytes, params: dict[str, str], where: str, problems: list[str]) -> bytes:
    """`data` with every {{name}} replaced by params[name]; an unfilled name is recorded in `problems`."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return data

    def sub(m: re.Match) -> str:
        name = m.group(1)
        if name not in params:
            problems.append(f"{where}: placeholder {{{{{name}}}}} is not in the profile")
            return m.group(0)
        return str(params[name]).strip()

    return PLACEHOLDER.sub(sub, text).encode("utf-8")


def _profile(shared: Path, h: str, entry: dict, problems: list[str]) -> dict[str, str]:
    path = entry.get("profile")
    if not path:
        problems.append(f"{h}: targets.yaml names no profile")
        return {}
    try:
        return (yaml.safe_load((shared / path).read_text()) or {}).get("params") or {}
    except (OSError, yaml.YAMLError) as e:
        problems.append(f"{h}: cannot read {path}: {e}")
        return {}


def plan(root: Path = ROOT) -> tuple[list[tuple[Path, Path, dict[str, bytes]]], list[str]]:
    """(source, destination, rendered files) for every copy that is out of sync, and problems."""
    shared = root / "shared" / "work-system"
    t = yaml.safe_load((shared / "targets.yaml").read_text())
    stale: list[tuple[Path, Path, dict[str, bytes]]] = []
    problems: list[str] = []
    hook_src = shared / t["hook"]
    harnesses = t["harnesses"]
    if isinstance(harnesses, list):  # the older form: a plain list, no profiles
        harnesses = {h: {} for h in harnesses}
    for h, entry in harnesses.items():
        entry = entry or {}
        hd = root / "harnesses" / h
        if not hd.is_dir():
            problems.append(f"{h}: harnesses/{h} does not exist")
            continue
        params = _profile(shared, h, entry, problems)
        for s in list(t["skills"]) + list(entry.get("skills") or []):
            src, dst = shared / "skills" / s, hd / "skills" / s
            if not src.is_dir():
                problems.append(f"{h}: shared skill {s} does not exist")
                continue
            want = {rel: render(b, params, f"{h}: skills/{s}/{rel}", problems) for rel, b in _files(src).items()}
            if not dst.is_dir() or want != _files(dst):
                stale.append((src, dst, want))
        dst = hd / "native" / "claude-code" / "hooks" / hook_src.name
        want_hook = render(hook_src.read_bytes(), params, f"{h}: {t['hook']}", problems)
        if not dst.is_file() or dst.read_bytes() != want_hook:
            stale.append((hook_src, dst, {"": want_hook}))
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


def write(stale: list[tuple[Path, Path, dict[str, bytes]]], root: Path = ROOT) -> None:
    for src, dst, files in stale:
        if src.is_dir():
            if dst.exists():
                shutil.rmtree(dst)
            for rel, data in files.items():
                (dst / rel).parent.mkdir(parents=True, exist_ok=True)
                (dst / rel).write_bytes(data)
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(files[""])
            shutil.copymode(src, dst)
        print(f"synced {dst.relative_to(root)}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--check", action="store_true", help="exit 1 when a copy differs; write nothing")
    args = ap.parse_args(argv)
    stale, problems = plan()
    if args.check:
        for src, dst, _ in stale:
            print(f"error: {dst.relative_to(ROOT)} differs from the rendering of {src.relative_to(ROOT)} "
                  "(edit shared/work-system/, then python scripts/sync_shared.py)", file=sys.stderr)
    elif not problems:
        write(stale)
    for p in problems:
        print(f"error: {p}", file=sys.stderr)
    if (args.check and stale) or problems:
        return 1
    print("shared work-system layer in sync")
    return 0


if __name__ == "__main__":
    sys.exit(main())
