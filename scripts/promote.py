#!/usr/bin/env python3
"""Promote a harness: keep a release copy of its current revision and point `stable` (or another channel) at it.

A channel names a `harness_digest`. The files behind every promoted digest stay in the tree, at
`harnesses/<name>/releases/r<N>/`: the lock and every file it pins, exactly as `hangar harness thaw` would mount them.
`check_registry.py` resolves channels from the current lock or these copies, never from git history, so a squash merge
or a rewritten history can't lose or change what `stable` runs (KAN-473). Release copies are append-only.

    python scripts/promote.py harnesses/work-default                 # stable = the current lock (candidate's)
    python scripts/promote.py harnesses/work-default --channel beta
    python scripts/promote.py harnesses/team-default --release-only  # write the copy, leave channels.yaml alone

Needs hangar importable (see relock.py).
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

import yaml

from hangar import harness_lock as hl

RELEASES = "releases"


def needed(lock: dict[str, Any]) -> list[str]:
    """The paths a lock's directory must hold for a claim (hangar's harness_thaw._needed)."""
    out = [c["path"] for c in lock["components"] if c.get("path")]
    for c in lock["components"]:
        if c["id"].startswith("plugin:"):
            out.append(f"plugins/{hl.plugin_ref(c['id'])['marketplace']}/.claude-plugin/marketplace.json")
    return out


def release_dir(harness: Path, revision: int) -> Path:
    return harness / RELEASES / f"r{revision}"


def releases(harness: Path) -> list[Path]:
    d = harness / RELEASES
    return sorted(p for p in d.iterdir() if p.is_dir()) if d.is_dir() else []


def find_release(harness: Path, digest: str) -> Path | None:
    """The release copy whose lock has `digest`, if any."""
    for d in releases(harness):
        try:
            if hl.harness_digest(hl.load(d)) == digest:
                return d
        except ValueError:
            continue
    return None


def release_problems(harness: Path) -> list[str]:
    """Each release copy is a whole harness: its lock checks against its files, and it sits at r<its revision>."""
    out = []
    for d in releases(harness):
        res = hl.check(d)
        out += [f"{d.relative_to(harness.parent.parent)}: {p}" for p in res["problems"]]
        if res["ok"] and d.name != f"r{res['revision']}":
            out.append(f"{d.relative_to(harness.parent.parent)}: holds r{res['revision']}")
    return out


def write_release(harness: Path, lock_file: Path | None = None) -> Path:
    """Copy the harness's current lock (or `lock_file`, whose files are in `harness`) and its files into
    releases/r<N>/. Refuses to change an existing copy."""
    lock = hl.load(lock_file or harness)
    dest = release_dir(harness, lock["revision"])
    if dest.exists():
        if hl.harness_digest(hl.load(dest)) == hl.harness_digest(lock) and hl.check(dest)["ok"]:
            return dest
        raise SystemExit(f"{dest} already holds another r{lock['revision']}: release copies never change")
    with tempfile.TemporaryDirectory(dir=harness) as tmp:
        t = Path(tmp) / "r"
        for rel in needed(lock):
            src = harness / rel
            if src.is_dir():
                shutil.copytree(src, t / rel)
            else:
                (t / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(src, t / rel)
        (t / hl.LOCK_FILE).write_text(hl.dump(lock))
        res = hl.check(t)
        if not res["ok"]:
            raise SystemExit(f"{harness}: the files don't match the lock: {'; '.join(res['problems'])}")
        dest.parent.mkdir(exist_ok=True)
        t.rename(dest)
    return dest


def set_channel(channels_file: Path, name: str, channel: str, digest: str, note: str) -> None:
    """Rewrite one `channel: "digest"  # note` line under `name:` in channels.yaml, keeping the rest as written."""
    lines = channels_file.read_text().splitlines(keepends=True)
    inside, done = False, False
    for i, line in enumerate(lines):
        if re.match(r"^\S", line):
            inside = line.split(":", 1)[0].strip() == name
        elif inside and re.match(rf"^\s+{re.escape(channel)}:", line):
            indent = line[: len(line) - len(line.lstrip())]
            lines[i] = f'{indent}{channel}: "{digest}"  # {note}\n'
            done = True
    if not done:
        raise SystemExit(f"{channels_file}: no {name}.{channel} line to move")
    channels_file.write_text("".join(lines))
    assert (yaml.safe_load(channels_file.read_text()) or {})[name][channel] == digest


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("harness", type=Path)
    ap.add_argument("--channel", default="stable")
    ap.add_argument("--release-only", action="store_true", help="write the release copy; leave channels.yaml alone")
    ap.add_argument("--note", default=None, help="the comment for the channels.yaml line")
    a = ap.parse_args()
    lock = hl.load(a.harness)
    res = hl.check(a.harness)
    if not res["ok"]:
        raise SystemExit(f"{a.harness}: {'; '.join(res['problems'])} (run scripts/relock.py first)")
    digest = hl.harness_digest(lock)
    channels_file = a.harness.resolve().parent.parent / "channels.yaml"
    chans = (yaml.safe_load(channels_file.read_text()) or {}).get(lock["name"]) or {}
    if not a.release_only and a.channel == "stable" and chans.get("candidate") != digest:
        raise SystemExit(f"{lock['name']}: candidate is not the current lock ({digest}); promote what was evaluated")
    dest = write_release(a.harness)
    print(f"{lock['name']} r{lock['revision']} {digest} -> {dest}", file=sys.stderr)
    if not a.release_only:
        set_channel(channels_file, lock["name"], a.channel, digest,
                    a.note or f"r{lock['revision']}, promoted from candidate ({RELEASES}/r{lock['revision']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
