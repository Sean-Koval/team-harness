"""KAN-547: the scaffold template's PowerShell verify line runs under Windows PowerShell 5.1, as a coworker without
Git Bash would run it.

The test renders the template, creates `.venv`, activates it as SKILL.md step 4 says and runs the README's
```powershell block with powershell.exe. The block must pass on a clean render. With a lint error it must stop at
ruff and exit non-zero, so pyright and pytest never run. That is what the `if ($?)` chain promises.

It runs only on Windows, where powershell.exe is 5.1. check.yml's windows job sets SCAFFOLD_POWERSHELL_REQUIRED=1, so
there a missing powershell.exe fails instead of skipping. Elsewhere (Linux, local) the test skips.
"""

import os
import re
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "shared/work-system/skills/scaffold-artifact"
RENDERED = ROOT / "harnesses/suite-default/skills/scaffold-artifact"
DOCS = ("SKILL.md", "templates/mcp-server/AGENTS.md", "templates/mcp-server/README.md")
FENCE = re.compile(r"^(?P<indent>[ \t]*)```powershell\n(?P<body>.*?)^(?P=indent)```$", re.M | re.S)
POWERSHELL = shutil.which("powershell")  # Windows PowerShell 5.1, never pwsh: 5.1 is the shell without &&


def powershell_block(doc: Path) -> str:
    """The one ```powershell block in a doc, dedented, without its comment lines."""
    blocks = [textwrap.dedent(m["body"]) for m in FENCE.finditer(doc.read_text(encoding="utf-8"))]
    assert len(blocks) == 1, f"{doc}: expected one powershell block, found {len(blocks)}"
    return "\n".join(line for line in blocks[0].splitlines() if line.strip() and not line.lstrip().startswith("#"))


def test_the_three_docs_give_the_same_powershell_block():
    blocks = {rel: powershell_block(SKILL / rel) for rel in DOCS}
    assert len(set(blocks.values())) == 1, blocks
    assert "if ($?) { python -m pytest -q }" in blocks["templates/mcp-server/README.md"]
    skill = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    assert ".venv\\Scripts\\Activate.ps1" in skill and "Set-ExecutionPolicy -Scope Process RemoteSigned" in skill


def need_windows_powershell() -> None:
    if sys.platform == "win32" and POWERSHELL:
        return
    if os.environ.get("SCAFFOLD_POWERSHELL_REQUIRED") == "1":
        pytest.fail("this job must run the scaffold's PowerShell verify line, but Windows PowerShell is not here")
    pytest.skip("the PowerShell verify line runs only on Windows, under Windows PowerShell 5.1")


@pytest.fixture(scope="module")
def project(tmp_path_factory) -> Path:
    need_windows_powershell()
    dest = tmp_path_factory.mktemp("scaffold") / "weather-tools"
    r = subprocess.run([sys.executable, str(RENDERED / "scaffold.py"), "mcp-server", str(dest), "--name",
                        "weather-tools", "--ticket", "PROJ-12", "--description", "Weather lookups for the team"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    r = subprocess.run([sys.executable, "-m", "venv", ".venv"], cwd=dest, capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stderr
    return dest


def run_block(dest: Path) -> subprocess.CompletedProcess:
    # Step 4's activation, then the README's block as written. -Force only answers the confirmation prompt that an
    # interactive shell shows; -NonInteractive would otherwise turn it into an error.
    script = dest / "verify.ps1"
    script.write_text(
        "Set-ExecutionPolicy -Scope Process RemoteSigned -Force\n"
        ".venv\\Scripts\\Activate.ps1\n"
        # what the test checks the shell and the activation by, in files: console output may wrap a long path
        "Set-Content -Encoding ascii verify-shell.txt $PSVersionTable.PSVersion.Major\n"
        "Set-Content -Encoding utf8 verify-python.txt (Get-Command python).Source\n"
        f"{powershell_block(dest / 'README.md')}\n"
        "exit $LASTEXITCODE\n",
        encoding="utf-8",
    )
    env = {k: v for k, v in os.environ.items() if not k.startswith(("PYTEST_", "VIRTUAL_ENV"))}
    try:
        return subprocess.run(
            [POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(script)],
            cwd=dest, env=env, capture_output=True, text=True, errors="replace", timeout=1500,
        )
    finally:
        script.unlink()


def test_the_powershell_block_passes_on_a_clean_render(project):
    r = run_block(project)
    out = r.stdout + r.stderr
    assert r.returncode == 0, out
    assert (project / "verify-shell.txt").read_text(encoding="ascii").strip() == "5", "not Windows PowerShell 5.1"
    python = (project / "verify-python.txt").read_text(encoding="utf-8-sig").strip()
    assert os.path.samefile(python, project / ".venv" / "Scripts" / "python.exe"), f"activation left {python} first"
    assert re.search(r"\d+ passed", r.stdout), out  # pytest, the last link, ran


def test_the_powershell_block_stops_at_the_first_failing_tool(project):
    probe = project / "tests" / "test_lint_probe.py"
    probe.write_text("import os\n", encoding="utf-8")  # F401: ruff check fails, pyright and pytest would still pass
    try:
        r = run_block(project)
    finally:
        probe.unlink()
    out = r.stdout + r.stderr
    assert r.returncode != 0, "the block exited 0 although ruff check failed:\n" + out
    assert "F401" in out, out
    ran_on = re.search(r"\b\d+ errors?, \d+ warnings?", out) or re.search(r"\d+ passed", out)  # pyright, pytest
    assert not ran_on, "the chain ran on after ruff failed:\n" + out
