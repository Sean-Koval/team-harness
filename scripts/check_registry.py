#!/usr/bin/env python3
"""CI for a team harness repo, with hangar's own code: everything `hangar harness check` doesn't cover.

For each `harnesses/<name>/`:

1. the lock checks (`harness_lock.check`, what `hangar harness check` runs);
2. `AGENTS.md`, when present, is byte-identical to the `CLAUDE.md` guide, so the guide's digest covers both;
3. the rendered environments are up to date (`scripts/render_envs.py --check`);
4. `env.stable.yaml`, loaded by hangar's environment catalog, yields the lock's `harness_digest` without plugins, and
   `env.candidate.yaml` (when the lock has plugins) yields the full `harness_digest`, when projected the way a turn's
   manifest is: an experiment arm on either environment runs exactly that lock.

And for `channels.yaml`: every channel names a digest that resolves to a lock, in the checkout or its git history,
the way `hangar harness thaw name@<channel>` resolves it (hangar's resolver itself when this directory is the
repository root, followed by its claim checks against the rendered environments: CLI version, model, approvals,
MCP servers). Thaw mounts a lock's plugins itself (hangar#221), so every channel claims on `<name>`.

And for the work conventions: every environment under `environments/` (the role environments and `work-multirepo`)
loads in hangar's catalog next to the harness environments it extends, `work-multirepo` installs everything the
infra, code and database roles do, and every change-set profile under `changesets/` is well formed against them.
The agent environment's pins agree with what they name (`agent_pin_problems`; `--agent-pins` checks only these, which
`make agent-env` does before it starts one). hangar runs the environment locally (`hangar env local`, KAN-472).

    python scripts/check_registry.py [REPO_ROOT] [--agent-pins]
"""

from __future__ import annotations

import re
import subprocess
import sys
import tempfile
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


def claim_channel(root: Path, name: str, channel: str) -> str:
    """hangar's claim checks (`harness_thaw.pin`) for `name@channel` on the rendered environment that provides it."""
    env = name
    with tempfile.TemporaryDirectory() as data:  # pin copies the lock's files out (hangar#221 mounts them)
        fleet = SimpleNamespace(settings=SimpleNamespace(harness_repo=str(root), data_dir=data),
                                catalog=EnvCatalog([root / "harnesses" / name]))
        p = harness_thaw.pin(fleet, f"{name}@{channel}", env)
    return f"claim on {env}: ok ({p['harness']} {p['version']}, {p['model']}, {p['approvals']})"


def _catalog(root: Path) -> EnvCatalog:
    """Harness environments first (role environments extend them), then environments/roles/, then environments/."""
    harness_dirs = sorted(d for d in (root / "harnesses").iterdir() if (d / hl.LOCK_FILE).is_file())
    return EnvCatalog([*harness_dirs, root / "environments" / "roles", root / "environments"])


MULTI = "work-multirepo"
COVERED_ROLES = ("role-infra", "role-code", "role-database")  # role-deploy runs the deploy step, not the agent


def check_environments(root: Path) -> list[str]:
    errors: list[str] = []
    cat = _catalog(root)
    own = sorted({f.stem for f in (root / "environments").rglob("*.y*ml")})
    names: dict[str, Any] = {}
    for f in sorted((root / "environments").rglob("*.y*ml")):
        name = (yaml.safe_load(f.read_text()) or {}).get("name") or f.stem
        try:
            names[name] = cat.get(name)
            print(f"environment {name}: ok ({f.relative_to(root)})")
        except (KeyError, ValueError) as e:
            errors.append(f"{f.relative_to(root)}: {e}")
    if not own or errors or MULTI not in names:
        return errors
    multi = names[MULTI]
    for role in COVERED_ROLES:
        r = names.get(role)
        if r is None:
            errors.append(f"environments/roles: {role} is missing")
            continue
        missing = [*(f"apt {p}" for p in r.tools.apt if p not in multi.tools.apt),
                   *(f"mise {t}={v}" for t, v in r.tools.mise.items() if multi.tools.mise.get(t) != v),
                   *(f"pip {p}" for p in r.dependencies.pip if p not in multi.dependencies.pip),
                   *(f"service {k}" for k, v in r.services.items() if multi.services.get(k) != v),
                   *(f"env {k}" for k, v in r.env.items() if multi.env.get(k) != v)]
        if missing:
            errors.append(f"{MULTI} lacks what {role} installs: {', '.join(missing)}")
    if not errors:
        print(f"environment {MULTI}: carries {', '.join(COVERED_ROLES)}")
    if AGENT_ENV in names:
        pins = agent_pin_problems(root)
        errors += pins
        if not pins:
            print(f"environment {AGENT_ENV}: pins agree (harness, ai-dlc, knowledge format, model, names)")
    errors += claim_role_environments(root, cat, names)
    return errors


def claim_role_environments(root: Path, cat: EnvCatalog, names: dict[str, Any]) -> list[str]:
    """hangar's claim checks for `<harness>@stable` on each environment that extends that harness's environment:
    a job on a role's repo (or a change set) runs the stable harness there with its CLI, model and MCP servers."""
    top = (_git(root, "rev-parse", "--show-toplevel") or "").strip()
    if not (top and Path(top).resolve() == root):
        return []  # hangar's resolver wants the repository root
    channels = yaml.safe_load((root / "channels.yaml").read_text()) or {}
    errors: list[str] = []
    for env in names:
        base = env
        while (parent := cat.raw(base).get("extends")) is not None:
            base = parent
        if "stable" not in (channels.get(base) or {}):
            continue
        with tempfile.TemporaryDirectory() as data:
            fleet = SimpleNamespace(settings=SimpleNamespace(harness_repo=str(root), data_dir=data), catalog=cat)
            try:
                p = harness_thaw.pin(fleet, f"{base}@stable", env)
                print(f"{base}@stable: claim on {env}: ok ({p['harness']} {p['version']}, {p['model']})")
            except harness_thaw.ThawError as e:
                errors.append(f"{base}@stable on {env}: {e}")
    return errors


PROFILE_SCHEMA = "hangar.changeset-profile/v1"
_REPO = re.compile(r"^[\w.-]+/[\w.-]+$")
_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
_REF = re.compile(r"{([a-z][a-z0-9_-]*)\.merge_sha}")


def profile_problems(p: Any, envs: set[str]) -> list[str]:
    """The shape of hangar.changeset-profile/v1 (hangar's change-set design, section 5), checked without hangar."""
    if not isinstance(p, dict):
        return ["not a mapping"]
    out: list[str] = []
    if p.get("schema") != PROFILE_SCHEMA:
        out.append(f"schema must be {PROFILE_SCHEMA}")
    if not _NAME.match(str(p.get("name") or "")):
        out.append("name: lowercase letters, digits and '-'")
    if p.get("environment") not in envs:
        out.append(f"environment {p.get('environment')!r} is not in environments/ or a harness")
    repos = p.get("repos") or {}
    if not isinstance(repos, dict) or len(repos) < 2:
        return [*out, "repos: at least two roles, {role: {repo: owner/name}}"]
    read_only = set()
    for role, r in repos.items():
        if not isinstance(r, dict) or not _REPO.match(str(r.get("repo") or "")):
            out.append(f"repos.{role}: repo must be owner/name")
            continue
        if r.get("agent", "write") not in ("read", "write"):
            out.append(f"repos.{role}: agent is read or write")
        if r.get("agent") == "read":
            read_only.add(role)
    if len({r.get("repo") for r in repos.values() if isinstance(r, dict)}) != len(repos):
        out.append("repos: each role is a different repo")
    order = p.get("land_order") or []
    if len(set(order)) != len(order) or not set(order) <= set(repos) - read_only or not order:
        out.append("land_order: each writable role once, and only those")
    d = p.get("deploy")
    if d is not None:
        role = d.get("role")
        if role not in read_only:
            out.append("deploy.role: a role the agent may only read (agent: read)")
        if not set(d.get("after") or []) <= set(order) or not d.get("after"):
            out.append("deploy.after: roles from land_order")
        for step in ("ready", "apply"):
            if not isinstance(d.get(step), dict) or not d[step].get("kind"):
                out.append(f"deploy.{step}: needs a kind")
        refs = set(_REF.findall(yaml.safe_dump(d)))
        if unknown := sorted(refs - set(d.get("after") or [])):
            out.append(f"deploy: {{<role>.merge_sha}} names roles that aren't in deploy.after: {', '.join(unknown)}")
        if not d.get("environments"):
            out.append("deploy.environments: at least one")
    return out


def check_changesets(root: Path) -> list[str]:
    errors: list[str] = []
    envs = set(_catalog(root).names())
    for f in sorted((root / "changesets").glob("*.y*ml")):
        p = yaml.safe_load(f.read_text())
        problems = profile_problems(p, envs)
        if isinstance(p, dict) and p.get("name") != f.stem:
            problems.append(f"name {p.get('name')!r} differs from the file name")
        errors += [f"{f.relative_to(root)}: {x}" for x in problems]
        if not problems:
            print(f"changeset {f.stem}: ok ({', '.join(p['land_order'])}, then {p['deploy']['role']})"
                  if p.get("deploy") else f"changeset {f.stem}: ok")
    return errors



# ------------------------------------------------------------------------------------------------ the agent environment
AGENT_ENV = "agent"  # environments/agent.yaml (KAN-447)
AGENT_INPUTS = ("TICKET_KEY", "CODE_REPO", "KNOWLEDGE_REPO")
AGENT_PINS = ("AGENT_ENV_HARNESS", "AGENT_ENV_HARNESS_DIGEST", "AI_DLC_REF", "KNOWLEDGE_FORMAT_VERSION")


def agent_catalog(root: Path) -> EnvCatalog:
    """The catalog `hangar env local` loads: the harness directories, then the role environments and environments/."""
    harness_dirs = sorted(d for d in (root / "harnesses").iterdir() if (d / hl.LOCK_FILE).is_file())
    return EnvCatalog([*harness_dirs, root / "environments" / "roles", root / "environments"])


def contract_names(path: Path) -> list[str]:
    """The variable names agent.env.example declares, in order."""
    return [m.group(1) for line in path.read_text().splitlines() if (m := re.match(r"^([A-Z][A-Z0-9_]*)=", line))]


def agent_pin_problems(root: Path) -> list[str]:
    """Where the agent environment's pins disagree with what they name. Empty when the definition is consistent."""
    cat = agent_catalog(root)
    spec = cat.get(AGENT_ENV)
    raw = cat.raw(AGENT_ENV)
    out: list[str] = []
    env = spec.env
    missing = [p for p in AGENT_PINS if not env.get(p)]
    if missing:
        return [f"env {AGENT_ENV}: pin(s) missing: {', '.join(missing)}"]
    harness = env["AGENT_ENV_HARNESS"]
    if raw.get("extends") != harness:
        out.append(f"env {AGENT_ENV}: extends {raw.get('extends')!r}, but AGENT_ENV_HARNESS is {harness!r}")
    lock_dir = root / "harnesses" / harness
    if not (lock_dir / hl.LOCK_FILE).is_file():
        return [*out, f"env {AGENT_ENV}: AGENT_ENV_HARNESS {harness!r} has no harnesses/{harness}/{hl.LOCK_FILE}"]
    lock = hl.load(lock_dir)
    digest = hl.harness_digest(lock)
    if env["AGENT_ENV_HARNESS_DIGEST"] != digest:
        out.append(f"env {AGENT_ENV}: AGENT_ENV_HARNESS_DIGEST is {env['AGENT_ENV_HARNESS_DIGEST']}, but "
                   f"{harness} provides r{lock.get('revision')} {digest}")
    channels = yaml.safe_load((root / "channels.yaml").read_text()) or {}
    if not [ch for ch, d in (channels.get(harness) or {}).items() if d == env["AGENT_ENV_HARNESS_DIGEST"]]:
        out.append(f"env {AGENT_ENV}: AGENT_ENV_HARNESS_DIGEST is no channel of {harness} in channels.yaml")
    if spec.model != (lock.get("model") or {}).get("id"):
        out.append(f"env {AGENT_ENV}: model {spec.model!r} is not the harness lock's {lock.get('model')}")
    ref = env["AI_DLC_REF"]
    if not re.fullmatch(r"[0-9a-f]{40}", ref):
        out.append(f"env {AGENT_ENV}: AI_DLC_REF must be a full commit SHA, not {ref!r}")
    elif ref not in (spec.dependencies.script or ""):
        out.append(f"env {AGENT_ENV}: dependencies.script does not install ai-dlc at AI_DLC_REF {ref}")
    if not str(env["KNOWLEDGE_FORMAT_VERSION"]).isdigit():
        out.append(f"env {AGENT_ENV}: KNOWLEDGE_FORMAT_VERSION must be an integer")
    names = contract_names(root / "environments" / "agent.env.example")
    if set(spec.secrets) - set(names):
        out.append(f"agent.env.example lacks the spec's secrets: {', '.join(sorted(set(spec.secrets) - set(names)))}")
    if set(AGENT_INPUTS) - set(names):
        out.append(f"agent.env.example lacks the inputs: {', '.join(sorted(set(AGENT_INPUTS) - set(names)))}")
    if clash := sorted(set(names) & set(spec.env)):
        out.append(f"agent.env.example names values the spec fixes: {', '.join(clash)}")
    if spec.egress is None or spec.egress.mode != "allowlist":
        out.append(f"env {AGENT_ENV}: egress.mode must be allowlist")
    return out


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    root = Path(args[0] if args else ".").resolve()
    if "--agent-pins" in sys.argv[1:]:
        pins = agent_pin_problems(root)
        for p in pins:
            print(f"error: {p}", file=sys.stderr)
        return 1 if pins else 0
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
        if any(c["id"].startswith("plugin:") for c in lock["components"]):
            got = env_identity(d, f"{lock['name']}-candidate", approvals)
            if got != hl.harness_digest(lock):
                errors.append(f"{d.name}: env.candidate.yaml yields {got}, the lock is {hl.harness_digest(lock)}")
            else:
                print(f"{d.name}: env.candidate.yaml reproduces {got}")
    channels = yaml.safe_load((root / "channels.yaml").read_text()) or {}
    for name, chans in channels.items():
        for ch, digest in (chans or {}).items():
            try:
                where = resolve_channel(root, name, ch, digest)
                print(f"{name}@{ch}: {digest} -> {where}")
                top = (_git(root, "rev-parse", "--show-toplevel") or "").strip()
                if top and Path(top).resolve() == root:
                    print(f"{name}@{ch}: {claim_channel(root, name, ch)}")
            except (ValueError, harness_thaw.ThawError) as e:
                errors.append(str(e))
    if (root / "environments").is_dir():
        errors += check_environments(root)
    if (root / "changesets").is_dir():
        errors += check_changesets(root)
    for e in errors:
        print(f"error: {e}", file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
