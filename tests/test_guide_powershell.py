"""The teammate guide's Windows commands (KAN-469): what CI can check without a coworker's machine.

Every ```powershell block in docs/knowledge/ must parse. Quickstart step 3, the one block that touches files, runs
for real against a scratch knowledge clone: the inbox copy must keep the sample's text, carry the login, and be UTF-8
with no byte-order mark and LF line ends, which the record parser needs. The macOS block of the same step runs too.

The parse needs PowerShell and skips where it is missing (Linux CI runners have pwsh too). The step 3 run uses
Windows paths, so it runs only on the windows-latest CI job.
Commands that call ai-dlc, gh or the installer are parsed, not run: CI has no signed-in gh and no ai-dlc on Windows.
"""

import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
GUIDE = ROOT / "docs" / "knowledge"
SAMPLE = GUIDE / "sample" / "practice-sync.md"
FENCE = re.compile(r"^```(?P<lang>\w+)\n(?P<body>.*?)^```$", re.M | re.S)
POWERSHELL_TAGS = {"powershell", "pwsh", "ps1", "ps"}
POWERSHELL = shutil.which("pwsh") or shutil.which("powershell")
needs_powershell = pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is not installed here")


def _blocks(lang: str, text: str) -> list[str]:
    tags = POWERSHELL_TAGS if lang == "powershell" else {lang}
    return [m["body"] for m in FENCE.finditer(text) if m["lang"] in tags]


def _all_powershell() -> list[tuple[str, int, str]]:
    found = []
    for page in sorted(GUIDE.glob("*.md")):
        for i, body in enumerate(_blocks("powershell", page.read_text(encoding="utf-8"))):
            found.append((page.name, i, body))
    return found


def _step3(lang: str) -> str:
    text = (GUIDE / "quickstart.md").read_text(encoding="utf-8")
    section = text.split("## 3. ", 1)[1].split("\n## ", 1)[0]
    (body,) = _blocks(lang, section)
    return body


def _expected(login: str) -> bytes:
    return SAMPLE.read_bytes().replace(b"\r\n", b"\n").replace(b"YOUR-LOGIN", login.encode())


def _check_inbox_copy(knowledge: Path, login: str) -> None:
    out = (knowledge / "inbox" / f"practice-sync-{login}.md").read_bytes()
    assert not out.startswith(b"\xef\xbb\xbf"), "the copy starts with a byte-order mark"
    assert b"\r" not in out, "the copy has CRLF line ends"
    assert b"YOUR-LOGIN" not in out and login.encode() in out
    assert out.rstrip(b"\n") == _expected(login).rstrip(b"\n")


def test_the_guide_has_powershell_for_every_page_with_commands():
    blocks = _all_powershell()
    assert {name for name, _, _ in blocks} >= {"quickstart.md", "capture.md", "find.md"}
    assert len(blocks) >= 5


@needs_powershell
@pytest.mark.parametrize("page,index,body", [pytest.param(*b, id=f"{b[0]}-{b[1]}") for b in _all_powershell()])
def test_every_powershell_block_parses(tmp_path, page, index, body):
    script = tmp_path / "block.ps1"
    script.write_text(body, encoding="utf-8")
    probe = (
        "$errors = $null; $tokens = $null; "
        f"[void][System.Management.Automation.Language.Parser]::ParseFile('{script}', [ref]$tokens, [ref]$errors); "
        "$errors | ForEach-Object { $_.Message }"
    )
    result = subprocess.run([POWERSHELL, "-NoProfile", "-NonInteractive", "-Command", probe],
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "", f"{page} block {index} does not parse: {result.stdout}"


@pytest.mark.skipif(sys.platform != "win32", reason="the block writes Windows paths; it runs on the windows CI job")
def test_quickstart_step3_powershell_writes_a_parser_ready_copy(tmp_path):
    login = "tester-1"
    knowledge = tmp_path / "knowledge"
    (knowledge / "inbox").mkdir(parents=True)
    body = _step3("powershell")
    assert "gh api user --jq .login" in body and "$HOME\\src\\team-harness" in body
    # the only substitutions: no signed-in gh in CI, and the clone is this checkout rather than ~/src
    body = body.replace("gh api user --jq .login", f"'{login}'").replace("$HOME\\src\\team-harness", str(ROOT))
    script = tmp_path / "step3.ps1"
    script.write_text(f"$ErrorActionPreference = 'Stop'\n$env:KNOWLEDGE_REPO = '{knowledge}'\n{body}", encoding="utf-8")
    result = subprocess.run([POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(script)],
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    _check_inbox_copy(knowledge, login)


@pytest.mark.skipif(sys.platform == "win32" or shutil.which("sed") is None, reason="the macOS block needs POSIX sh and sed")
def test_quickstart_step3_macos_writes_the_same_copy(tmp_path):
    login = "tester-1"
    knowledge = tmp_path / "knowledge"
    (knowledge / "inbox").mkdir(parents=True)
    body = _step3("sh")
    assert "$(gh api user --jq .login)" in body and "~/src/team-harness" in body
    body = body.replace("$(gh api user --jq .login)", login).replace("~/src/team-harness", shlex.quote(str(ROOT)))
    result = subprocess.run(["sh", "-eu", "-c", body], env={"KNOWLEDGE_REPO": str(knowledge), "PATH": os.environ["PATH"]},
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    _check_inbox_copy(knowledge, login)
