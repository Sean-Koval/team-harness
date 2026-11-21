"""KAN-512: the scaffold-artifact skill's MCP server template renders into a repository that passes its own verify
command (ruff, pyright, pytest) before any feature line is written.

The verify run installs the rendered project with its `[dev]` extra into a venv of its own, named by SCAFFOLD_PYTHON.
check.yml's Linux job sets it and SCAFFOLD_REQUIRED=1, so there a missing venv fails instead of skipping; anywhere
else (locally, generated.yml) the run is skipped without it.
"""

import importlib.util
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "shared/work-system/skills/scaffold-artifact"
HARNESSES = ("suite-default", "work-default")


def load(skill_dir: Path):
    spec = importlib.util.spec_from_file_location(f"scaffold_{skill_dir.parent.parent.name}", skill_dir / "scaffold.py")
    mod = importlib.util.module_from_spec(spec)
    dont, sys.dont_write_bytecode = sys.dont_write_bytecode, True  # a __pycache__ in the skill would be a stray file
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.dont_write_bytecode = dont
    return mod


def rendered(h: str) -> Path:
    return ROOT / "harnesses" / h / "skills" / "scaffold-artifact"


def render(tmp_path: Path, h: str = "suite-default") -> Path:
    dest = tmp_path / "weather-tools"
    r = subprocess.run([sys.executable, str(rendered(h) / "scaffold.py"), "mcp-server", str(dest), "--name",
                        "weather-tools", "--ticket", "PROJ-12", "--description", "Weather lookups for the team"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return dest


def files(d: Path) -> list[Path]:
    return sorted(p for p in d.rglob("*") if p.is_file())


@pytest.mark.parametrize("h", HARNESSES)
def test_the_rendered_repo_has_fragments_windows_ci_and_no_unfilled_placeholder(h, tmp_path):
    dest = render(tmp_path, h)
    rel = {p.relative_to(dest).as_posix() for p in files(dest)}
    assert {"changes/README.md", "changes/PROJ-12.added.md", "tests/test_contract.py", "evals/README.md",
            "evals/golden/search.json", "src/weather_tools/server.py", "AGENTS.md", "pyproject.toml"} <= rel
    ci = (dest / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert re.search(r"(?m)^\s+runs-on: windows-latest$", ci) and re.search(r"(?m)^\s+runs-on: ubuntu-latest$", ci)
    for p in files(dest):
        text = p.read_text(encoding="utf-8")
        assert "{{" not in text and "@@" not in text, p.relative_to(dest)
    agents = (dest / "AGENTS.md").read_text(encoding="utf-8")
    assert "Owner: " in agents and "PROJ-12" in agents and "Approvals: " in agents


@pytest.mark.parametrize("h", HARNESSES)
def test_the_harness_copy_fills_owner_and_approvals_from_its_profile(h):
    agents = (rendered(h) / "templates/mcp-server/AGENTS.md").read_text(encoding="utf-8")
    shared = (SKILL / "templates/mcp-server/AGENTS.md").read_text(encoding="utf-8")
    assert "{{owner}}" in shared and "{{approvals}}" in shared
    assert "{{" not in agents


def test_the_template_runs_its_own_verify_command(tmp_path):
    py = os.environ.get("SCAFFOLD_PYTHON")
    if not py:
        if os.environ.get("SCAFFOLD_REQUIRED") == "1":
            pytest.fail("SCAFFOLD_PYTHON is not set: this job must run the template's verify command")
        pytest.skip("set SCAFFOLD_PYTHON to a venv's python to run the template's verify command")
    dest = render(tmp_path)
    # the venv first on PATH, as when it is activated: pyright reads site-packages from the python it finds there
    venv_bin = str(Path(py).parent)
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTEST_")}
    env.update(PATH=venv_bin + os.pathsep + env.get("PATH", ""), VIRTUAL_ENV=str(Path(py).parent.parent))
    # with its dependencies, from the template's own pins: the declaration is part of what is checked
    install = subprocess.run([py, "-m", "pip", "install", "--quiet", "-e", ".[dev]"], cwd=dest, env=env,
                             capture_output=True, text=True, timeout=900)
    assert install.returncode == 0, install.stdout + install.stderr
    for cmd in (["ruff", "check", "."], ["ruff", "format", "--check", "."], ["pyright"], ["pytest", "-q"]):
        r = subprocess.run([py, "-m", *cmd], cwd=dest, env=env, capture_output=True, text=True, timeout=600)
        assert r.returncode == 0, f"{' '.join(cmd)}:\n{r.stdout}\n{r.stderr}"


def test_it_refuses_a_directory_that_is_not_empty_and_leaves_nothing_on_failure(tmp_path):
    scaffold = load(SKILL)
    vals = scaffold.values("weather-tools", "PROJ-12", "Weather")
    busy = tmp_path / "busy"
    busy.mkdir()
    (busy / "keep.txt").write_text("x")
    with pytest.raises(ValueError, match="not an empty directory"):
        scaffold.render("mcp-server", busy, vals)
    assert [p.name for p in busy.iterdir()] == ["keep.txt"]
    # a token the values don't fill: the run fails and removes what it wrote
    with pytest.raises(ValueError, match="tokens left unfilled"):
        scaffold.render("mcp-server", tmp_path / "new", {k: v for k, v in vals.items() if k != "@@ticket@@"})
    assert not (tmp_path / "new").exists()
    # parents it had to create go too, and an empty directory it was given is left empty
    with pytest.raises(ValueError, match="tokens left unfilled"):
        scaffold.render("mcp-server", tmp_path / "a" / "b" / "new", {k: v for k, v in vals.items() if k != "@@ticket@@"})
    assert not (tmp_path / "a").exists()
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(ValueError, match="tokens left unfilled"):
        scaffold.render("mcp-server", empty, {k: v for k, v in vals.items() if k != "@@ticket@@"})
    assert empty.is_dir() and not any(empty.iterdir())


@pytest.mark.parametrize("name, ticket, description", [
    ("Weather Tools", "PROJ-12", "x"), ("weather_tools", "PROJ-12", "x"), ("-x", "PROJ-12", "x"),
    ("weather", "proj-12", "x"), ("weather", "PROJ", "x"), ("weather", "PROJ-12", ""),
    ("weather", "PROJ-12", 'say "hi"'), ("weather", "PROJ-12", "a @@b@@"),
    ("class", "PROJ-12", "x"), ("typing", "PROJ-12", "x"), ("mcp", "PROJ-12", "x"), ("pytest", "PROJ-12", "x"),
    ("weather", "PROJ-12", "x" * 71), ("weather", "PROJ-12", "bell\x07")])
def test_it_refuses_malformed_names(name, ticket, description):
    with pytest.raises(ValueError):
        load(SKILL).values(name, ticket, description)


def test_the_skill_stays_short():
    assert len((SKILL / "SKILL.md").read_text(encoding="utf-8").splitlines()) <= 150


def test_every_verify_command_has_a_powershell_form():
    # coworkers on Windows run it in PowerShell without Git Bash; Windows PowerShell 5.1 rejects &&
    for rel in ("SKILL.md", "templates/mcp-server/AGENTS.md", "templates/mcp-server/README.md"):
        text = (SKILL / rel).read_text(encoding="utf-8")
        assert text.count("python -m pytest -q") == text.count("if ($?) { python -m pytest -q }") * 2, rel
    assert ".venv\\Scripts\\Activate.ps1" in (SKILL / "SKILL.md").read_text(encoding="utf-8")
