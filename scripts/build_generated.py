#!/usr/bin/env python3
"""Build every generated file from its sources: the shared layer's copies, each harness's lock and env files, and
`candidate` on each new lock (KAN-481).

PRs change sources only (`shared/`, `orgs/`, a harness's own files); the generated files are built here, after each
merge, by `.github/workflows/generated.yml` on main, and in the working tree of each PR's CI run before the checks. So
two PRs never both edit a lock, a rendered copy or `channels.yaml`, and one's merge can't conflict with the other.

In order: `sync_shared.py` writes the layer's copies; for every harness with a `harness.lock`, `relock.py` re-pins its
files (a new revision only when something changed) and `render_envs.py` writes its `env.*.yaml`; when a harness's
digest changed, its `candidate` line in `channels.yaml` moves to the new digest, the note prepended to the old
comment, and `environments/agent.yaml`'s `AGENT_ENV_HARNESS_DIGEST` follows when it names that harness. `stable` and the `releases/` copies are left alone: only `promote.py` changes them. Nor does stable's environment
change without a promotion: the build refuses to rewrite an `env.stable.yaml` whose `stable` is the one it was last
written with (`stable_frozen`).

    python scripts/build_generated.py                       # build in place, to test a change locally
    python scripts/build_generated.py --restore             # then put the generated files back as committed
    python scripts/build_generated.py --note "KAN-123: ..."  # the channels.yaml note for a moved candidate
    python scripts/build_generated.py --guard origin/main   # CI: fail when the PR commits generated files
    python scripts/build_generated.py --drift origin/main   # CI, after the build: fail when a generated file the
                                                            # PR commits differs from the built one

`--restore` touches only generated files and lines (a harness's own files and other edits to channels.yaml or
agent.yaml stay). `--guard` is skipped in CI for a PR labelled `generated-files` (a lock frozen from a run).

Needs hangar importable (see relock.py).
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import promote  # noqa: E402
import relock  # noqa: E402
import render_envs  # noqa: E402
import sync_shared  # noqa: E402
import yaml  # noqa: E402
from hangar import harness_lock as hl  # noqa: E402

NOTE_LIMIT = 1200  # characters of a channels.yaml comment; older history is in git
ENV_FILES = ("env.stable.yaml", "env.candidate.yaml")
CHANNEL_LINE = re.compile(r"^\s+candidate:")
AGENT_LINE = re.compile(r"^\s*AGENT_ENV_HARNESS_DIGEST:")
LINE_FILES = {"channels.yaml": CHANNEL_LINE, "environments/agent.yaml": AGENT_LINE}  # generated lines only
LINE_NAMES = {"channels.yaml": "candidate", "environments/agent.yaml": "AGENT_ENV_HARNESS_DIGEST"}


def generated_prefixes(root: Path) -> list[str]:
    """Paths (a trailing / is a directory) that the build writes: the shared layer's and the org's copies in each
    target harness, and every harness's lock and env files. Release copies are promote.py's, never these."""
    t = yaml.safe_load((root / "shared" / "work-system" / "targets.yaml").read_text(encoding="utf-8"))
    out = []
    for h, entry in (t["harnesses"] or {}).items():
        entry = entry or {}
        skills = list(t["skills"]) + list(entry.get("skills") or [])
        org = root / entry["org"] / "skills" if entry.get("org") else None
        if org is not None and org.is_dir():
            skills += [d.name for d in org.iterdir() if d.is_dir()]
        out += [f"harnesses/{h}/skills/{s}/" for s in skills]
        hooks = [t["hook"], *[x["file"] for x in t.get("session_hooks") or []]]
        out += [f"harnesses/{h}/native/claude-code/hooks/{Path(x).name}" for x in hooks]
        out.append(f"harnesses/{h}/.env.example")
    for d in sorted((root / "harnesses").iterdir()):
        if (d / hl.LOCK_FILE).is_file():
            out += [f"harnesses/{d.name}/{f}" for f in (hl.LOCK_FILE, *ENV_FILES)]
    return out


def is_generated(prefixes: list[str], rel: str) -> bool:
    return any(rel == p or (p.endswith("/") and rel.startswith(p)) for p in prefixes)


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True).stdout


def guard(root: Path, base: str) -> list[str]:
    """What a PR commits that the build writes, relative to `base`."""
    prefixes = generated_prefixes(root)
    out = [f"{p}: generated" for p in _git(root, "diff", "--name-only", base, "HEAD").splitlines()
           if is_generated(prefixes, p)]
    for rel, pat in LINE_FILES.items():
        diff = _git(root, "diff", "-U0", base, "HEAD", "--", rel).splitlines()
        if any(x[:1] in "+-" and not x.startswith(("+++", "---")) and pat.match(x[1:]) for x in diff):
            out.append(f"{rel}: its {LINE_NAMES[rel]} line is generated")
    names = _git(root, "diff", "--name-status", base, "HEAD").splitlines()
    if any(x.startswith("M") and x.split("\t")[-1] == "CHANGELOG.md" for x in names) and not any(
            x.startswith("D") and x.split("\t")[-1].startswith("changes/") for x in names):
        out.append("CHANGELOG.md: add changes/<KEY>.md instead; only the release fold edits it")
    return out


def drift(root: Path, base: str) -> list[str]:
    """Generated files the PR changed since `base` that the build (already run in the work tree) wrote differently:
    a hand-edited copy, even in a PR labelled generated-files."""
    prefixes = generated_prefixes(root)
    touched = {p for p in _git(root, "diff", "--name-only", base, "HEAD").splitlines() if is_generated(prefixes, p)}
    rebuilt = set(_git(root, "diff", "--name-only", "HEAD").splitlines())
    return [f"{p}: differs from what the build writes" for p in sorted(touched & rebuilt)]


def restore(root: Path) -> list[str]:
    """Put every generated file and line back as HEAD has it; return what changed."""
    prefixes = generated_prefixes(root)
    done = []
    for line in _git(root, "status", "--porcelain", "--untracked-files=all").splitlines():
        rel = line[3:].split(" -> ")[-1]
        if not is_generated(prefixes, rel):
            continue
        if line.startswith("??"):
            (root / rel).unlink()
        else:
            _git(root, "restore", "--source=HEAD", "--staged", "--worktree", "--", rel)
        done.append(rel)
    for rel, pat in LINE_FILES.items():
        f = root / rel
        if not f.is_file():
            continue
        head = {i: x for i, x in enumerate(_git(root, "show", f"HEAD:{rel}").splitlines(keepends=True))
                if pat.match(x)}
        now = f.read_text(encoding="utf-8").splitlines(keepends=True)
        idx = [i for i, x in enumerate(now) if pat.match(x)]
        if len(idx) != len(head):
            raise SystemExit(f"{rel}: can't match its generated lines to HEAD's; restore it by hand")
        new = list(now)
        for i, x in zip(idx, head.values()):
            new[i] = x
        if new != now:
            f.write_text("".join(new), encoding="utf-8", newline="\n")
            done.append(rel)
    return done


def old_comment(channels_file: Path, name: str, channel: str) -> str:
    """The comment on `name.channel`'s line in channels.yaml, or ""."""
    inside = False
    for line in channels_file.read_text(encoding="utf-8").splitlines():
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
    text = f.read_text(encoding="utf-8")
    m = re.search(r"^\s*AGENT_ENV_HARNESS:\s*\"?([\w.-]+)\"?\s*$", text, re.MULTILINE)
    if not m or m.group(1) != name:
        return
    new, n = re.subn(r'^(\s*AGENT_ENV_HARNESS_DIGEST:\s*)"[^"]*"(.*)$',
                     lambda g: f'{g.group(1)}"{digest}"  # r{revision}', text, count=1, flags=re.MULTILINE)
    if n != 1:
        raise SystemExit(f"{f}: no AGENT_ENV_HARNESS_DIGEST line to move")
    f.write_text(new, encoding="utf-8", newline="\n")


def stable_frozen(root: Path, harness: Path, name: str) -> bool:
    """Whether `harness`'s env.stable.yaml must stay as committed: it is committed, and channels.yaml names the same
    `stable` now as in the commit that last changed it. Stable's lock, its release copy and the bindings it renders
    with all move only by a promotion, so a rendering that differs without one is a build fault (ac72dd6: a shallow
    clone rendered stable with main's bindings). A renderer change that should reach stable goes in a PR labelled
    generated-files, which commits the new env.stable.yaml for review (KAN-481)."""
    rel = (harness / "env.stable.yaml").relative_to(root).as_posix()
    last = _git(root, "log", "-1", "--format=%H", "--", rel).strip()
    if not last:
        return False
    try:
        then = yaml.safe_load(_git(root, "show", f"{last}:channels.yaml")) or {}
    except subprocess.CalledProcessError:
        return False
    now = yaml.safe_load((root / "channels.yaml").read_text(encoding="utf-8")) or {}
    stable = (now.get(name) or {}).get("stable")
    return stable is not None and stable == (then.get(name) or {}).get("stable")


def build(root: Path, note: str) -> list[str]:
    """Build in place; return one line per harness whose lock moved. Refuses, after building the rest, to change a
    stable environment with no promotion since it was last written (stable_frozen)."""
    if sync_shared.main([]) != 0:
        raise SystemExit("sync_shared.py failed: fix the shared layer first")
    channels_file = root / "channels.yaml"
    moved, refused = [], []
    for d in sorted((root / "harnesses").iterdir()):
        if not (d / hl.LOCK_FILE).is_file():
            continue
        before = hl.harness_digest(hl.load(d))
        lock, _ = relock.relock(d)
        digest = hl.harness_digest(lock)
        if digest != before:
            (d / hl.LOCK_FILE).write_text(hl.dump(lock), encoding="utf-8", newline="\n")
        want = render_envs.render(d)
        for f in ENV_FILES:
            if f in want and (not (d / f).is_file() or (d / f).read_text(encoding="utf-8") != want[f]):
                if f == "env.stable.yaml" and stable_frozen(root, d, lock["name"]):
                    refused.append(f"{d.relative_to(root).as_posix()}/{f}")
                    continue
                (d / f).write_text(want[f], encoding="utf-8", newline="\n")
            elif f not in want and (d / f).is_file():
                (d / f).unlink()
        if digest != before:
            text = f"r{lock['revision']}: {note}"
            prev = old_comment(channels_file, lock["name"], "candidate")
            full = f"{text}. {prev}" if prev else text
            if len(full) > NOTE_LIMIT:  # drop the oldest revisions whole
                cut = full.rfind(". r", 0, NOTE_LIMIT)
                full = full[:cut + 1] if cut > 0 else full[:NOTE_LIMIT].rstrip()
            promote.set_channel(channels_file, lock["name"], "candidate", digest, full)
            repin_agent_env(root, lock["name"], digest, lock["revision"])
            moved.append(f"{lock['name']} r{lock['revision']} {digest}")
    if refused:
        raise SystemExit("\n".join(
            f"error: {f}: the build would change stable's environment with no promotion (its stable digest in "
            "channels.yaml is the one it was last written with). Build from a full clone (fetch-depth: 0); a "
            "renderer change for stable goes in a PR labelled generated-files (KAN-481)" for f in refused))
    return moved


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--note", default="built from sources by scripts/build_generated.py",
                    help="what changed, for the channels.yaml line of each moved candidate")
    ap.add_argument("--restore", action="store_true", help="put the generated files back as HEAD has them")
    ap.add_argument("--guard", metavar="BASE", help="fail when HEAD changes generated files or lines since BASE")
    ap.add_argument("--drift", metavar="BASE", help="after a build: fail when a generated file HEAD changed since "
                    "BASE differs from the built one")
    a = ap.parse_args(argv)
    if a.drift:
        bad = drift(ROOT, a.drift)
        for b in bad:
            print(f"error: {b}; edit the source in shared/ or orgs/, not the copy (KAN-481)", file=sys.stderr)
        return 1 if bad else 0
    if a.restore:
        for rel in restore(ROOT):
            print(f"restored {rel}", file=sys.stderr)
        return 0
    if a.guard:
        bad = guard(ROOT, a.guard)
        for b in bad:
            print(f"error: {b}; PRs commit sources only, the build writes this after merge (KAN-481; "
                  "python scripts/build_generated.py --restore). A lock frozen from a run: label the PR "
                  "generated-files", file=sys.stderr)
        return 1 if bad else 0
    note = " ".join(a.note.replace("#", "").split())  # one line, and no second comment marker
    for line in build(ROOT, note):
        print(f"candidate -> {line}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
