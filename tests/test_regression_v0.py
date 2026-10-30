"""flightdeck/suites/regression-v0 (KAN-222): 20 valid tasks that fit one hangar experiment, named before trial 1."""

import re
import tomllib
from datetime import date
from pathlib import Path

import pytest
import yaml

flightdeck_format = pytest.importorskip("flightdeck.tasks.format")

ROOT = Path(__file__).resolve().parents[1]
SUITE = ROOT / "flightdeck" / "suites" / "regression-v0"
TASKS = sorted(p for p in (SUITE / "tasks").iterdir() if p.is_dir())
CUTOFF = date(2026, 6, 30)  # claude-opus-5-5's knowledge cutoff (June 2026): tasks must be mined after it
REPOS = {"https://github.com/Sean-Koval/flightdeck.git", "https://github.com/Sean-Koval/hangar.git",
         "https://github.com/Sean-Koval/team-harness.git", "https://github.com/Sean-Koval/ai-dlc.git"}


def test_twenty_tasks_load_and_fit_one_hangar_experiment():
    tasks = [flightdeck_format.load_task(p) for p in TASKS]
    assert len(tasks) == 20
    spec_tasks, grader = flightdeck_format.to_hangar(tasks)  # one grader: 64 files, 1 MB, one command
    assert len(spec_tasks) == 20 and grader["command"].endswith("bash tests/test.sh")
    assert all(t["repo"] in REPOS and re.fullmatch(r"[0-9a-f]{40}", t["base_sha"]) for t in spec_tasks)
    assert all(t.get("reference_patch") for t in spec_tasks)  # hangar's base-must-fail check has a known fix


@pytest.mark.parametrize("task", TASKS, ids=lambda p: p.name)
def test_each_task_is_open_mined_after_the_cutoff_and_from_a_merged_pr(task):
    fd = tomllib.loads((task / "task.toml").read_text())["flightdeck"]
    assert fd["sealed"] is False and "regression-v0" in fd["tags"]
    assert date.fromisoformat(fd["mined_after"]) > CUTOFF
    assert re.fullmatch(r"https://github\.com/Sean-Koval/[\w-]+/pull/\d+", fd["mined_from"])
    hidden = sorted(p.name for p in (task / "tests").iterdir())
    assert "test.sh" in hidden and any(n.startswith("test_") and n.endswith(".py") for n in hidden)


def test_the_readme_lists_every_task_and_the_rule_came_first():
    readme = (SUITE / "README.md").read_text()
    assert all(f"`{t.name}`" in readme for t in TASKS)
    assert (SUITE / "SELECTION.md").is_file() and "SELECTION.md" in readme


def test_the_preregistration_names_regression_v0_and_keeps_its_verdict_keys():
    text = (ROOT / "flightdeck" / "decision.yaml").read_text()
    comments = "\n".join(line for line in text.splitlines() if line.lstrip().startswith("#"))
    assert "regression-v0" in comments and "before trial 1" in comments
    d = yaml.safe_load(text)
    assert (d["metric"], d["direction"], d["margin"], d["min_tasks"]) == ("cost_usd", "lower", 0.40, 20)
    suite = yaml.safe_load((ROOT / "flightdeck" / "suite.yaml").read_text())
    assert suite["tasks"] == ["suites/regression-v0/tasks"] and suite["n"] == 3
    assert {v["model"] for v in suite["variants"].values()} == {"claude-opus-5-5"}
    assert {v["approvals"] for v in suite["variants"].values()} == {"deny-risky"}
