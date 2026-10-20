"""scripts/check_registry.py's change-set profile check: the example passes, broken profiles say why."""

import copy
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import check_registry  # noqa: E402

EXAMPLE = yaml.safe_load((ROOT / "changesets/example-service.yaml").read_text())
ENVS = {"work-multirepo", "role-code"}


def test_example_is_well_formed():
    assert check_registry.profile_problems(EXAMPLE, ENVS) == []


def broken(edit):
    p = copy.deepcopy(EXAMPLE)
    edit(p)
    return check_registry.profile_problems(p, ENVS)


@pytest.mark.parametrize("edit,expect", [
    (lambda p: p.update(schema="hangar.changeset/v0"), "schema"),
    (lambda p: p.update(environment="nope"), "environment"),
    (lambda p: p["repos"]["code"].update(repo="not a repo"), "repos.code"),
    (lambda p: p["repos"]["code"].update(repo="example-org/example-service-db"), "different repo"),
    (lambda p: p.update(land_order=["database", "infra", "code", "deploy"]), "land_order"),
    (lambda p: p.update(land_order=["database", "database"]), "land_order"),
    (lambda p: p["repos"]["deploy"].pop("agent"), "deploy.role"),
    (lambda p: p["deploy"].update(after=["database", "unknown"]), "deploy.after"),
    (lambda p: p["deploy"]["apply"].pop("kind"), "deploy.apply"),
    (lambda p: p["deploy"].update(after=["database", "infra"]), "merge_sha"),
    (lambda p: p["deploy"].update(environments=[]), "deploy.environments"),
])
def test_broken_profiles(edit, expect):
    problems = broken(edit)
    assert any(expect in x for x in problems), problems
