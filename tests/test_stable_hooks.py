"""KAN-477: a session on `stable` runs the hooks of stable's release copy, not the ones current on main.

`env.stable.yaml` (environment `<name>`) is rendered from the lock `stable` names, read from its release copy
(`harnesses/<name>/releases/rN/`); `env.candidate.yaml` (environment `<name>-candidate`) from the current lock. A
turn on `<name>` then reports stable's `harness_digest`, so turn 1 of a stable session has no drift.
"""

import shutil
import sys
from pathlib import Path

import pytest
import yaml

pytest.importorskip("hangar")
from hangar import harness_lock as hl  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import check_registry  # noqa: E402
import promote  # noqa: E402
import relock  # noqa: E402
import render_envs  # noqa: E402

NAME = "work-default"
HOOK = "native/claude-code/hooks/guard_work.py"
HOME_HOOK = ".claude/hooks/guard_work.py"


def _hook(env_text: str) -> str:
    return yaml.safe_load(env_text)["agent_config"]["files"][HOME_HOOK]


def _write(h: Path) -> dict[str, str]:
    out = render_envs.render(h)
    for f in ("env.stable.yaml", "env.candidate.yaml"):
        if f in out:
            (h / f).write_text(out[f])
        elif (h / f).exists():
            (h / f).unlink()
    return out


def _identity(h: Path, env: str) -> str:
    approvals = (hl.load(h)["binding"].get("permissions") or {}).get("approvals")
    return check_registry.env_identity(h, env, approvals)


@pytest.fixture
def repo(tmp_path):
    """A registry whose stable and candidate are the same lock, with its release copy written."""
    h = tmp_path / "harnesses" / NAME
    shutil.copytree(ROOT / "harnesses" / NAME, h, ignore=shutil.ignore_patterns("releases", "env.*.yaml"))
    shutil.copytree(ROOT / "bindings", tmp_path / "bindings")
    digest = hl.harness_digest(hl.load(h))
    (tmp_path / "channels.yaml").write_text(
        f'{NAME}:\n  stable: "{digest}"  # r\n  candidate: "{digest}"  # r\n')
    rel = promote.write_release(h)
    _write(h)
    return tmp_path, h, digest, rel


def test_the_committed_stable_environments_serve_the_release_copies():
    chans = yaml.safe_load((ROOT / "channels.yaml").read_text())
    for name, ch in chans.items():
        h = ROOT / "harnesses" / name
        src = render_envs.stable_dir(h)
        assert hl.harness_digest(hl.load(src)) == ch["stable"]
        text = (h / "env.stable.yaml").read_text()
        provided = render_envs._as_locked(src, hl.load(src), "claude-code", render_envs.native_files(src, "claude-code"))
        files = yaml.safe_load(text)["agent_config"]["files"]
        for rel, content in provided.items():
            assert files[f".claude/{rel}"] == content, f"{name}: {rel} is not stable's"
        st = hl.load(src)
        without = {**st, "components": [c for c in st["components"] if not c["id"].startswith("plugin:")]}
        assert _identity(h, name) == hl.harness_digest(without), f"{name}: a stable session would drift on turn 1"


def test_one_lock_needs_no_candidate_environment(repo):
    _, h, digest, _ = repo
    assert not (h / "env.candidate.yaml").exists()
    assert _identity(h, NAME) == digest


def test_a_hook_edit_on_main_waits_for_a_promotion(repo):
    root, h, stable, rel = repo
    old = (h / HOOK).read_text()
    with (h / HOOK).open("a") as f:
        f.write("# edited on main\n")
    lock, _ = relock.relock(h)
    (h / hl.LOCK_FILE).write_text(hl.dump(lock))
    candidate = hl.harness_digest(lock)
    promote.set_channel(root / "channels.yaml", NAME, "candidate", candidate, "next")
    out = _write(h)

    # stable: exactly the release copy's hook bytes, and the stable digest on turn 1
    assert _hook(out["env.stable.yaml"]) == old
    assert _hook(out["env.stable.yaml"]) == (rel / HOOK).read_text()
    assert _identity(h, NAME) == stable
    # candidate: the edit, on its own environment
    assert _hook(out["env.candidate.yaml"]).endswith("# edited on main\n")
    assert _identity(h, f"{NAME}-candidate") == candidate
    assert check_registry.channel_env(root, NAME, "stable") == NAME
    assert check_registry.channel_env(root, NAME, "candidate") == f"{NAME}-candidate"

    # the promotion moves stable, and the environment with it
    promote.write_release(h)
    promote.set_channel(root / "channels.yaml", NAME, "stable", candidate, "promoted")
    out = _write(h)
    assert _hook(out["env.stable.yaml"]).endswith("# edited on main\n")
    assert _identity(h, NAME) == candidate
    assert "env.candidate.yaml" not in out


def test_stable_without_a_release_copy_is_refused(repo):
    root, h, _, _ = repo
    with (h / HOOK).open("a") as f:
        f.write("# edited on main\n")
    lock, _ = relock.relock(h)
    (h / hl.LOCK_FILE).write_text(hl.dump(lock))
    shutil.rmtree(h / "releases")
    with pytest.raises(SystemExit, match="neither the current lock nor a release copy"):
        render_envs.render(h)


def _git(repo: Path, *args: str) -> None:
    import subprocess
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.invalid",
                    "-c", "commit.gpgsign=false", *args], capture_output=True, text=True, check=True)


def test_a_binding_change_reaches_stable_only_by_promotion(repo):
    """A dependency added to bindings/ after stable's release copy was committed goes to the candidate environment
    only; env.stable.yaml keeps the bindings of the commit that added the copy, and check_registry's render check
    fails on a stable environment that took the new one."""
    root, h, _, rel = repo
    _git(root, "init", "-q")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "release")
    stable_before = (h / "env.stable.yaml").read_text()
    # a new lock on main, so stable is the release copy and candidate the current lock
    guide = h / "CLAUDE.md"
    guide.write_text(guide.read_text() + "\nA line after the release.\n")
    shutil.copy(guide, h / "AGENTS.md")
    import subprocess
    subprocess.run([sys.executable, str(ROOT / "scripts/relock.py"), str(h), "--write"], check=True,
                   capture_output=True)
    lock = hl.load(h)
    chans = yaml.safe_load((root / "channels.yaml").read_text())
    chans[NAME]["candidate"] = hl.harness_digest(lock)
    (root / "channels.yaml").write_text(yaml.safe_dump(chans))
    b = root / "bindings" / f"{NAME}.yaml"
    data = yaml.safe_load(b.read_text())
    data["dependencies"] = {"pip": ["example-tool==1.0"]}
    b.write_text(yaml.safe_dump(data, sort_keys=False))
    out = render_envs.render(h)
    assert render_envs.stable_dir(h) == rel
    # the same release, now read from releases/rN/: what the bindings give is what the release had
    bound = lambda text: {k: yaml.safe_load(text).get(k) for k in ("mcp", "secrets", "dependencies")}  # noqa: E731
    assert bound(out["env.stable.yaml"]) == bound(stable_before)
    assert "dependencies" not in yaml.safe_load(out["env.stable.yaml"])
    assert "example-tool==1.0" in out["env.candidate.yaml"]
    # a stable environment rendered from the current bindings is drift: the render check reports it
    leaked = yaml.safe_load(out["env.stable.yaml"])
    leaked["dependencies"] = data["dependencies"]
    (h / "env.stable.yaml").write_text(render_envs.HEADER.format(name=NAME) + yaml.safe_dump(leaked, sort_keys=False))
    r = subprocess.run([sys.executable, str(ROOT / "scripts/render_envs.py"), str(h), "--check"],
                       capture_output=True, text=True)
    assert r.returncode == 1 and "env.stable.yaml is out of date" in r.stderr
