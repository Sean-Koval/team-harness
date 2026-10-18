#!/usr/bin/env python3
"""CI for a team harness repo, with hangar's own code: everything `hangar harness check` doesn't cover.

For each `harnesses/<name>/`:

1. the lock checks (`harness_lock.check`, what `hangar harness check` runs);
2. `AGENTS.md`, when present, is byte-identical to the `CLAUDE.md` guide, so the guide's digest covers both;
3. the rendered environments are up to date (`scripts/render_envs.py --check`);
4. `env.stable.yaml`, loaded by hangar's environment catalog, yields the lock's `harness_digest` (without plugins)
   when projected the way a turn's manifest is: a session thawed on it reports no drift.

And for `channels.yaml`: every channel names a digest that resolves to a lock, in the checkout or its git history,
the way `hangar harness thaw name@<channel>` resolves it (hangar's resolver itself when this directory is the
repository root).

    python scripts/check_registry.py [REPO_ROOT]
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import yaml

from hangar import harness_lock as hl
from hangar import harness_thaw, manifest, plugins
from hangar.envspec import EnvCatalog
from hangar.harnesses import HARNESSES

sys.path.insert(0, str(Path(__file__).resolve().parent))
import render_envs  # noqa: E402


def env_identity(env_dir: Path, env: str, approvals: str | None) -> str:
    """harness_digest of a turn on environment `env`, as hangar's manifest computes it (the sections a lock pins)."""
    spec = EnvCatalog([env_dir]).get(env)
    h = spec.harnesses[0]
    hd = HARNESSES[h]
    text = spec.agent_config.instructions
    m: dict[str, Any] = {
        "harness": {"name": h, "locked": hd.version if hd.install else None},
        "model": {"id": spec.model},
        "instructions": {"global": {"declared": {"digest": manifest._sha(text)} if text else None}},
        "skills": {"declared": manifest.declared_skills(spec, h)},
        "plugins": plugins.manifest(spec, h),
        "mcp_servers": manifest.mcp_servers(spec, h),
        "hooks": manifest._hooks(spec, h, {}),
        "permissions": {"approvals": approvals},
    }
    return manifest.section_digest(m, manifest.HARNESS_SECTIONS)


def _git(root: Path, *args: str) -> str | None:
    r = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else None


def resolve_channel(root: Path, name: str, channel: str, digest: str) -> str:
    """Where `name@channel` resolves: 'current' or a commit. Raises ValueError when it doesn't."""
    top = (_git(root, "rev-parse", "--show-toplevel") or "").strip()
    if top and Path(top).resolve() == root.resolve():
        r = harness_thaw.resolve(SimpleNamespace(harness_repo=str(root)), f"{name}@{channel}")
        return r.commit or "current"
    # a harness repo kept in a subdirectory (this example inside agent-factory): the same walk, with paths relative
    # to it (hangar's resolver expects the repository root)
    rel = f"harnesses/{name}/{hl.LOCK_FILE}"
    current = hl.load(root / rel)
    if hl.harness_digest(current) == digest:
        return "current"
    for commit in (_git(root, "log", "--format=%H", "--", rel) or "").split():
        text = _git(root, "show", f"{commit}:./{rel}")
        old = yaml.safe_load(text or "")
        if not hl.problems(old) and hl.harness_digest(old) == digest:
            return commit
    raise ValueError(f"{name}@{channel} ({digest}) is neither the current lock nor in the git history of {rel}")


def main() -> int:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    errors: list[str] = []
    for d in sorted((root / "harnesses").iterdir()):
        if not (d / hl.LOCK_FILE).is_file():
            continue
        res = hl.check(d)
        print(f"{d.name}: lock {'ok' if res['ok'] else 'FAILS'} r{res.get('revision')} {res['digest']}")
        errors += [f"{d.name}: {p}" for p in res["problems"]]
        if not res["ok"]:
            continue
        lock = hl.load(d)
        if (d / "AGENTS.md").exists() and (d / "AGENTS.md").read_bytes() != (d / "CLAUDE.md").read_bytes():
            errors.append(f"{d.name}: AGENTS.md differs from CLAUDE.md (copy it: the lock pins CLAUDE.md)")
        want = render_envs.render(d)
        for f, text in want.items():
            if not (d / f).is_file() or (d / f).read_text() != text:
                errors.append(f"{d.name}: {f} is out of date (python scripts/render_envs.py harnesses/{d.name})")
        if errors:
            continue
        approvals = (lock["binding"].get("permissions") or {}).get("approvals")
        without = {**lock, "components": [c for c in lock["components"] if not c["id"].startswith("plugin:")]}
        got = env_identity(d, lock["name"], approvals)  # the catalog reads env.*.yaml next to the lock
        if got != hl.harness_digest(without):
            errors.append(f"{d.name}: env.stable.yaml yields {got}, the lock without plugins is "
                          f"{hl.harness_digest(without)}")
        else:
            print(f"{d.name}: env.stable.yaml reproduces {got}")
    channels = yaml.safe_load((root / "channels.yaml").read_text()) or {}
    for name, chans in channels.items():
        for ch, digest in (chans or {}).items():
            try:
                where = resolve_channel(root, name, ch, digest)
                print(f"{name}@{ch}: {digest} -> {where}")
            except (ValueError, harness_thaw.ThawError) as e:
                errors.append(str(e))
    for e in errors:
        print(f"error: {e}", file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
