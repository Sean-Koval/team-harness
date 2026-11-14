"""KAN-473: harness_digest covers hook scripts, and CI fails when a harness's files change under a digest."""

import shutil
import subprocess
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

HOOK = "native/claude-code/hooks/guard_work_system.py"


def _copy(tmp_path: Path) -> Path:
    h = tmp_path / "harnesses" / "suite-default"
    shutil.copytree(ROOT / "harnesses" / "suite-default", h)
    return h


def _relock(h: Path) -> dict:
    lock, _ = relock.relock(h)
    (h / hl.LOCK_FILE).write_text(hl.dump(lock))
    return lock


def test_settings_name_the_other_native_files(tmp_path):
    h = _copy(tmp_path)
    before = render_envs.native_files(h, "claude-code")["settings.json"]
    assert render_envs.PIN_VAR in before
    with (h / HOOK).open("a") as f:
        f.write("# edited\n")
    assert render_envs.native_files(h, "claude-code")["settings.json"] != before


def test_editing_a_hook_script_changes_the_digest_and_revision(tmp_path):
    h = _copy(tmp_path)
    before = hl.load(h)
    with (h / HOOK).open("a") as f:
        f.write("# edited\n")
    after = _relock(h)
    assert hl.harness_digest(after) != hl.harness_digest(before)
    assert after["revision"] == before["revision"] + 1
    assert hl.check(h)["ok"]


def test_the_committed_locks_are_current():
    for h in sorted((ROOT / "harnesses").iterdir()):
        lock, _ = relock.relock(h)
        assert hl.harness_digest(lock) == hl.harness_digest(hl.load(h)), f"{h.name}: run scripts/relock.py"


def test_rekey_refuses_changed_files(tmp_path):
    h = _copy(tmp_path)
    with (h / HOOK).open("a") as f:
        f.write("# edited\n")
    with pytest.raises(SystemExit, match="--rekey keeps the files"):
        relock.relock(h, rekey=True)


def test_native_files_without_a_hook_entry_are_refused(tmp_path):
    h = _copy(tmp_path)
    settings = h / "native/claude-code/settings.json"
    settings.write_text('{"permissions": {}}\n')
    with pytest.raises(SystemExit, match="would not cover them"):
        relock.relock(h)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    h = _copy(tmp_path)
    digest = hl.harness_digest(hl.load(h))
    (tmp_path / "channels.yaml").write_text(yaml.safe_dump({"suite-default": {"stable": digest, "candidate": digest}}))
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "-c", "user.name=t", "-c", "user.email=t@example.invalid", "add", "-A")
    _git(tmp_path, "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-qm", "base")
    return tmp_path, h, _git(tmp_path, "rev-parse", "HEAD")


def test_changed_files_need_candidate_moved(repo):
    root, h, base = repo
    chans = yaml.safe_load((root / "channels.yaml").read_text())["suite-default"]
    with (h / HOOK).open("a") as f:
        f.write("# edited\n")
    lock = _relock(h)
    problems = check_registry.base_problems(root, base, h, lock, chans)
    assert any("point candidate at" in p for p in problems)
    chans["candidate"] = hl.harness_digest(lock)
    assert check_registry.base_problems(root, base, h, lock, chans) == []


def test_changed_files_under_the_same_digest_fail(repo):
    root, h, base = repo
    chans = yaml.safe_load((root / "channels.yaml").read_text())["suite-default"]
    with (h / HOOK).open("a") as f:
        f.write("# edited\n")
    # what a lock looked like before KAN-473: the hook's component re-pinned, the digest left as it was
    lock = yaml.safe_load((h / hl.LOCK_FILE).read_text())
    for c in lock["components"]:
        if c["id"] == f"native:{HOOK.removeprefix('native/')}":
            c["digest"] = hl._sha((h / HOOK).read_bytes())
    (h / hl.LOCK_FILE).write_text(hl.dump(lock))
    problems = check_registry.base_problems(root, base, h, lock, chans)
    assert any("harness_digest did not" in p for p in problems)
    assert any("revision is still" in p for p in problems)


def test_stable_resolves_from_its_release_copy_not_history(repo):
    root, h, _ = repo
    chans = yaml.safe_load((root / "channels.yaml").read_text())["suite-default"]
    promote.write_release(h)
    rev = hl.load(h)["revision"]
    with (h / HOOK).open("a") as f:
        f.write("# edited\n")
    lock = _relock(h)
    assert check_registry.resolve_channel(root, "suite-default", "stable", chans["stable"]) == f"releases/r{rev}"
    assert check_registry.resolve_channel(root, "suite-default", "candidate", hl.harness_digest(lock)) == "current"
    shutil.rmtree(h / "releases")
    with pytest.raises(ValueError, match="release copy"):
        check_registry.resolve_channel(root, "suite-default", "stable", chans["stable"])


def test_release_copies_never_change(repo):
    root, h, _ = repo
    rel = promote.write_release(h)
    assert promote.release_problems(h) == []
    _git(root, "-c", "user.name=t", "-c", "user.email=t@example.invalid", "add", "-A")
    # --allow-empty: the copy is already committed when the current lock is a promoted one
    _git(root, "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-qm", "release", "--allow-empty")
    base = _git(root, "rev-parse", "HEAD")
    with (rel / HOOK).open("a") as f:
        f.write("# edited\n")
    assert any("the lock says" in p for p in promote.release_problems(h))
    with (h / HOOK).open("a") as f:
        f.write("# edited\n")
    _relock(h)
    with pytest.raises(SystemExit, match="never change"):
        promote.write_release(h, rel / hl.LOCK_FILE)
    relock_rel, _ = relock.relock(rel)
    (rel / hl.LOCK_FILE).write_text(hl.dump(relock_rel))
    assert any("never change" in p for p in check_registry.release_base_problems(root, base, h))


def test_promote_moves_stable_to_a_release_copy(repo):
    root, h, _ = repo
    with (h / HOOK).open("a") as f:
        f.write("# edited\n")
    lock = _relock(h)
    digest = hl.harness_digest(lock)
    promote.set_channel(root / "channels.yaml", "suite-default", "candidate", digest, "next")
    promote.write_release(h)
    promote.set_channel(root / "channels.yaml", "suite-default", "stable", digest, "promoted")
    chans = yaml.safe_load((root / "channels.yaml").read_text())["suite-default"]
    assert chans == {"stable": digest, "candidate": digest}
    assert (h / "releases" / f"r{lock['revision']}" / HOOK).read_bytes() == (h / HOOK).read_bytes()
