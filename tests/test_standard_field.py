"""The field evaluator must grade current source in ordinary developer environments."""

import os
from pathlib import Path
import subprocess
import sys


RUNNER = Path(__file__).resolve().parents[1] / "evals/implement-standard/field/field.py"


def test_optimized_parent_preserves_behavior_assertions(tmp_path):
    project = tmp_path / "replay"
    subprocess.run([sys.executable, RUNNER, "prepare", "D01", project], check=True)
    result = subprocess.run(
        [sys.executable, RUNNER, "verify", "D01", project],
        env={**os.environ, "PYTHONOPTIMIZE": "1"}, capture_output=True, text=True,
    )
    assert result.returncode == 1
    assert "ordinary repo check: exit 0" in result.stdout
    assert "private behavior check: exit 1" in result.stdout


def test_mutation_check_ignores_existing_bytecode(tmp_path):
    project = tmp_path / "quota"
    subprocess.run([sys.executable, RUNNER, "prepare", "B10", project], check=True)
    (project / "test_boundary.py").write_text(
        "import unittest\nfrom quota import response\n"
        "class Boundary(unittest.TestCase):\n"
        "    def test_exhausted_quota(self):\n"
        "        self.assertEqual(response(0, 5, 5), (200, {}))\n"
        "        self.assertEqual(response(0, 4, 5), (429, {'Retry-After': '1'}))\n"
    )
    subprocess.run(
        [sys.executable, "-c", "import py_compile; py_compile.compile("
         "'quota.py', invalidation_mode=py_compile.PycInvalidationMode.UNCHECKED_HASH)"],
        cwd=project, check=True,
    )
    subprocess.run([sys.executable, RUNNER, "verify", "B10", project], check=True)
