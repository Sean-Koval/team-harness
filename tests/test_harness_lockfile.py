"""KAN-600: a company builds its overlay revision without hangar, and the lock is the one hangar would write.

`scripts/harness_lockfile.py` replaces hangar's `harness_lock` in the build. The build test runs with `import hangar`
blocked; the parity tests hold every function to hangar's own where hangar is installed (CI pins it, `HANGAR_REF`)."""

import copy
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import harness_lockfile as lf  # noqa: E402
import promote  # noqa: E402

GIT = ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false"]
LOCK_DIRS = sorted(p.parent for p in (ROOT / "harnesses").glob("**/harness.lock"))
ORG = "orgs/acme-test"
LINE = "Acme's own step: KAN-600 test line."


def _no_hangar_env(tmp: Path) -> dict[str, str]:
    """The environment with a `hangar` package ahead of the real one that fails to import, as if not installed."""
    shim = tmp / "no-hangar" / "hangar"
    shim.mkdir(parents=True, exist_ok=True)
    (shim / "__init__.py").write_text('raise ModuleNotFoundError("hangar is blocked (KAN-600)", name="hangar")\n')
    return {**os.environ, "PYTHONPATH": str(shim.parent)}


@pytest.fixture(scope="module")
def built(tmp_path_factory) -> Path:
    """A clone that points work-default at its own company org, built with hangar blocked."""
    tmp = tmp_path_factory.mktemp("overlay")
    repo = tmp / "repo"
    subprocess.run(["git", "clone", "-q", "--no-local", str(ROOT), str(repo)], check=True, capture_output=True)
    shutil.copytree(repo / "orgs/example-co", repo / ORG)
    org_yaml = repo / ORG / "org.yaml"
    org_yaml.write_text(org_yaml.read_text().replace("name: example-co", "name: acme-test", 1))
    skill = repo / ORG / "skills/org-process/SKILL.md"
    skill.write_text(skill.read_text() + f"\n{LINE}\n")
    targets = repo / "shared/work-system/targets.yaml"
    text = targets.read_text()
    assert "org: orgs/example-co" in text
    targets.write_text(text.replace("org: orgs/example-co", f"org: {ORG}"))
    for f in (ROOT / "scripts").glob("*.py"):  # the scripts as this checkout has them, committed or not
        shutil.copyfile(f, repo / "scripts" / f.name)
    subprocess.run([*GIT, "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run([*GIT, "commit", "-qm", "acme org", "--allow-empty"], cwd=repo, check=True, capture_output=True)
    env = _no_hangar_env(tmp)
    blocked = subprocess.run([sys.executable, "-c", "import hangar"], env=env, capture_output=True, text=True)
    assert blocked.returncode != 0 and "blocked" in blocked.stderr
    r = subprocess.run([sys.executable, "scripts/build_generated.py", "--note", "KAN-600: acme"], cwd=repo, env=env,
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert "candidate -> work-default" in r.stderr
    return repo


def test_overlay_builds_without_hangar(built):
    wd = built / "harnesses/work-default"
    assert LINE in (wd / "skills/org-process/SKILL.md").read_text()
    lock = lf.load(wd)
    comp = next(c for c in lock["components"] if c["id"] == "skill:org-process")
    assert comp["digest"] == lf.files_digest(lf.read_dir(wd / "skills/org-process"))
    chans = yaml.safe_load((built / "channels.yaml").read_text())
    assert chans["work-default"]["candidate"] == lf.harness_digest(lock)


def test_overlay_lock_is_hangars(built):
    """hangar's own check passes on every built lock, and it would write the same bytes."""
    hl = pytest.importorskip("hangar.harness_lock")
    for d in sorted(p.parent for p in (built / "harnesses").glob("*/harness.lock")):
        res = hl.check(d)
        assert res["ok"], (d.name, res["problems"])
        assert (d / "harness.lock").read_text(encoding="utf-8") == hl.dump(hl.load(d))
        assert lf.harness_digest(lf.load(d)) == hl.harness_digest(hl.load(d))


def test_promote_without_hangar_says_how_to_get_it(tmp_path):
    """Promoting still checks the lock with hangar: without it, one line saying so, not a traceback."""
    r = subprocess.run([sys.executable, "scripts/promote.py", "harnesses/work-default", "--release-only"], cwd=ROOT,
                       env=_no_hangar_env(tmp_path), capture_output=True, text=True)
    assert r.returncode == 1 and "Traceback" not in r.stderr, r.stderr
    assert r.stderr.strip().splitlines() == [f"promoting needs hangar for `hangar harness check`: "
                                              f"{promote.INSTALL_HANGAR}"]


# --- parity with hangar's harness_lock --------------------------------------------------------------------------

@pytest.mark.parametrize("d", LOCK_DIRS, ids=lambda d: d.relative_to(ROOT).as_posix())
def test_lock_matches_hangar(d):
    hl = pytest.importorskip("hangar.harness_lock")
    lock = lf.load(d)
    assert lock == hl.load(d)
    assert lf.identity(lock) == hl.identity(lock)
    assert lf.harness_digest(lock) == hl.harness_digest(lock)
    assert lf.dump(lock) == hl.dump(lock)
    bumped = copy.deepcopy(lock) | {"revision": lock["revision"] + 5}
    changed = copy.deepcopy(lock) | {"model": {"id": "another-model", "policy": None}}
    for new in (lock, bumped, changed):
        assert lf.next_revision(lock, new) == hl.next_revision(lock, new)
    assert lf.next_revision(None, lock) == hl.next_revision(None, lock)
    for c in lock["components"]:
        p = d / (c.get("path") or "")
        if c.get("path") and p.is_dir():
            files = hl.read_dir(p)
            assert lf.read_dir(p) == files
            assert lf.files_digest(files) == hl.files_digest(files)
            assert lf.tree_digest(files) == hl.tree_digest(files)


BROKEN = [
    lambda lk: lk.pop("schema"),
    lambda lk: lk.update(name="Not A Name"),
    lambda lk: lk.update(revision=0),
    lambda lk: lk.update(runtime={}),
    lambda lk: lk.update(model="x"),
    lambda lk: lk["components"].append(copy.deepcopy(lk["components"][0])),
    lambda lk: lk["components"].append({"id": "guide:AGENTS.md", "digest": "sha256:0", "path": "../x"}),
    lambda lk: lk["components"].append({"id": "plugin:p@m", "digest": "sha256:" + "0" * 64, "path": "plugins/o/p",
                                        "enabled": "yes", "tree": "bad"}),
    lambda lk: lk["components"].append({"id": "skill:ref"}),
    lambda lk: lk.update(binding={"mcp": [{"name": "s", "transport": "http", "url": "u"}, {"name": 1}],
                                  "hooks": [{"event": "x"}], "permissions": []}),
    lambda lk: lk.update(plugins={"autoUpdate": True}, remote=[{}]),
    lambda lk: lk.clear(),
]


@pytest.mark.parametrize("i", range(len(BROKEN)))
def test_problems_match_hangar(i):
    hl = pytest.importorskip("hangar.harness_lock")
    lock = yaml.safe_load((ROOT / "harnesses/work-default/harness.lock").read_text(encoding="utf-8"))
    BROKEN[i](lock)
    assert lf.problems(lock) == hl.problems(lock)
    assert lf.problems(lock)
    assert lf.problems("not a lock") == hl.problems("not a lock")


def test_plugin_digests_match_hangar(tmp_path):
    hl = pytest.importorskip("hangar.harness_lock")
    mkt = tmp_path / "plugins/team/.claude-plugin"
    mkt.mkdir(parents=True)
    entry = {"name": "p", "source": "./p", "version": "1.0.0", "description": "é"}
    (mkt / "marketplace.json").write_text(json.dumps({"name": "team", "plugins": [entry, {"no": "name"}]}),
                                          encoding="utf-8")
    assert lf.marketplace_entries(tmp_path, "team") == hl.marketplace_entries(tmp_path, "team") == {"p": entry}
    assert lf.marketplace_entries(tmp_path, "other") is hl.marketplace_entries(tmp_path, "other") is None
    files = {"a/b.md": b"x", "a\\odd\nname": b"y", "c.txt": b""}
    assert lf.plugin_digest(entry, files) == hl.plugin_digest(entry, files)
    assert lf.tree_digest(files) == hl.tree_digest(files)
    assert lf.plugin_ref("plugin:p@team") == hl.plugin_ref("plugin:p@team")
