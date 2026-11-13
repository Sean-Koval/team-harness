#!/usr/bin/env python3
"""Build every generated file from its sources: the shared layer's copies, each harness's lock and env files, and
`candidate` on each new lock (KAN-481).

PRs change sources only (`shared/`, `orgs/`, a harness's own files); the generated files are built here, after each
merge, by `.github/workflows/generated.yml` on main, and in the working tree of each PR's CI run before the checks. So
two PRs never both edit a lock, a rendered copy or `channels.yaml`, and one's merge can't conflict with the other.

In order: `sync_shared.py` writes the layer's copies; for every harness with a `harness.lock`, `relock.py` re-pins its
files (a new revision only when something changed) and `render_envs.py` writes its `env.*.yaml`; when a harness's
digest changed, its `candidate` line in `channels.yaml` moves to the new digest, the note prepended to the old
comment, and `environments/agent.yaml`'s `AGENT_ENV_HARNESS_DIGEST` follows when it names that harness. `stable` and the `releases/` copies are left alone: only `promote.py` changes them.

    python scripts/build_generated.py                       # build in place (then `git restore harnesses channels.yaml`
                                                            # before committing a PR)
    python scripts/build_generated.py --note "KAN-123: ..."  # the channels.yaml note for a moved candidate

Needs hangar importable (see relock.py).
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import promote  # noqa: E402
import relock  # noqa: E402
import render_envs  # noqa: E402
import sync_shared  # noqa: E402
from hangar import harness_lock as hl  # noqa: E402

NOTE_LIMIT = 600  # characters of a channels.yaml comment; older history is in git


def old_comment(channels_file: Path, name: str, channel: str) -> str:
    """The comment on `name.channel`'s line in channels.yaml, or ""."""
    inside = False
    for line in channels_file.read_text().splitlines():
        if re.match(r"^\S", line):
            inside = line.split(":", 1)[0].strip() == name
        elif inside and re.match(rf"^\s+{re.escape(channel)}:", line):
            return line.split("#", 1)[1].strip() if "#" in line else ""
    return ""


def repin_agent_env(root: Path, name: str, digest: str, revision: int) -> None:
    """Point environments/agent.yaml's AGENT_ENV_HARNESS_DIGEST at `digest` when its AGENT_ENV_HARNESS is `name`
    (the agent environment runs the current lock: check_registry.py's agent_pin_problems)."""
    f = root / "environments" / "agent.yaml"
    if not f.is_file():
        return
    text = f.read_text()
    m = re.search(r"^\s*AGENT_ENV_HARNESS:\s*\"?([\w.-]+)\"?\s*$", text, re.MULTILINE)
    if not m or m.group(1) != name:
        return
    new, n = re.subn(r'^(\s*AGENT_ENV_HARNESS_DIGEST:\s*)"[^"]*"(.*)$',
                     lambda g: f'{g.group(1)}"{digest}"  # r{revision}', text, count=1, flags=re.MULTILINE)
    if n != 1:
        raise SystemExit(f"{f}: no AGENT_ENV_HARNESS_DIGEST line to move")
    f.write_text(new)


def build(root: Path, note: str) -> list[str]:
    """Build in place; return one line per harness whose lock moved."""
    if sync_shared.main([]) != 0:
        raise SystemExit("sync_shared.py failed: fix the shared layer first")
    channels_file = root / "channels.yaml"
    moved = []
    for d in sorted((root / "harnesses").iterdir()):
        if not (d / hl.LOCK_FILE).is_file():
            continue
        before = hl.harness_digest(hl.load(d))
        lock, _ = relock.relock(d)
        digest = hl.harness_digest(lock)
        if digest != before:
            (d / hl.LOCK_FILE).write_text(hl.dump(lock))
        want = render_envs.render(d)
        for f in ("env.stable.yaml", "env.candidate.yaml"):
            if f in want and (not (d / f).is_file() or (d / f).read_text() != want[f]):
                (d / f).write_text(want[f])
            elif f not in want and (d / f).is_file():
                (d / f).unlink()
        if digest != before:
            text = f"r{lock['revision']}: {note}"
            prev = old_comment(channels_file, lock["name"], "candidate")
            full = f"{text}. {prev}" if prev else text
            promote.set_channel(channels_file, lock["name"], "candidate", digest, full[:NOTE_LIMIT].rstrip())
            repin_agent_env(root, lock["name"], digest, lock["revision"])
            moved.append(f"{lock['name']} r{lock['revision']} {digest}")
    return moved


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--note", default="built from sources by scripts/build_generated.py",
                    help="what changed, for the channels.yaml line of each moved candidate")
    a = ap.parse_args(argv)
    note = " ".join(a.note.replace("#", "").split())  # one line, and no second comment marker
    for line in build(ROOT, note):
        print(f"candidate -> {line}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
