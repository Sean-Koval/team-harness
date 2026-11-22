"""Exercise the worked UI standard with the same verifier people run locally."""

import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


DIALOG = (Path(__file__).resolve().parents[1]
          / "shared/work-system/skills/implement-standard/examples/dialog")


def verify_dialog(example):
    if importlib.util.find_spec("playwright") is None:
        message = "Install Playwright and Chromium as documented in the dialog example."
        if os.getenv("STANDARD_BROWSER_REQUIRED") == "1":
            pytest.fail(message)
        pytest.skip(message)
    return subprocess.run([sys.executable, "verify.py"], cwd=example, capture_output=True, text=True, timeout=30)


def test_dialog_verifier_accepts_removal_and_its_focus_fallback():
    result = verify_dialog(DIALOG)
    assert result.returncode == 0, result.stdout + result.stderr


def test_dialog_verifier_rejects_leaving_the_draft_visible(tmp_path):
    example = shutil.copytree(DIALOG, tmp_path / "dialog")
    drafts = example / "drafts.js"
    good = drafts.read_text(encoding="utf-8")
    remove_row = 'opener.closest("li").remove()'
    assert good.count(remove_row) == 1
    # The shared dialog still works and the missing opener still sends focus to
    # the right fallback. The feature must also remove the draft itself.
    drafts.write_text(good.replace(remove_row, "opener.remove()"), encoding="utf-8")

    result = verify_dialog(example)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "Locator expected to have count '0'" in result.stderr
    assert "Actual value: 1" in result.stderr
    assert "Quarterly update" in result.stderr
