"""The scripts that build generated files read and write UTF-8 with LF on every OS (KAN-481).

Windows CI builds the locks, env files and candidate lines too. There Python's default encoding is the console code
page and its default line ending CRLF, so a call that names neither writes bytes that differ from Linux's build.
"""

import ast
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
BUILD = ["build_generated.py", "relock.py", "render_envs.py", "promote.py"]


def calls(path: Path, method: str) -> list[ast.Call]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [n for n in ast.walk(tree)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == method]


def keywords(call: ast.Call) -> dict[str, object]:
    return {k.arg: k.value.value for k in call.keywords if isinstance(k.value, ast.Constant)}


@pytest.mark.parametrize("script", BUILD)
def test_every_read_names_utf_8(script):
    bare = [c.lineno for c in calls(SCRIPTS / script, "read_text") if keywords(c).get("encoding") != "utf-8"]
    assert not bare, f"{script}: read_text without encoding='utf-8' on lines {bare}"


@pytest.mark.parametrize("script", BUILD)
def test_every_write_names_utf_8_and_lf(script):
    bare = [c.lineno for c in calls(SCRIPTS / script, "write_text")
            if keywords(c).get("encoding") != "utf-8" or keywords(c).get("newline") != "\n"]
    assert not bare, f"{script}: write_text without encoding='utf-8' and newline='\\n' on lines {bare}"
