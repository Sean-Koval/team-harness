"""scripts/work_copilot_overlay.py: the org overlay feeds Work Copilot's config (KAN-381)."""

import copy
import json
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import install_local as il  # noqa: E402
import work_copilot_overlay as wco  # noqa: E402

EXAMPLE = yaml.safe_load((ROOT / "orgs/example-co/org.yaml").read_text(encoding="utf-8"))


def fictional() -> dict:
    """A filled-in fictional company: what a private fork's org.yaml looks like."""
    org = copy.deepcopy(EXAMPLE)
    org.update(name="fictional-co", placeholder=False)
    org["params"] = {"tracker": "the FIC project", "kb_site": "fictional.example.invalid", "kb_space": "FICDOCS"}
    org["ticket_types"][0]["project"] = "FIC"
    org["review_request"]["room"] = "Fictional review room"
    return org


def test_a_filled_in_org_renders_work_copilot_config():
    assert wco.overlay(fictional(), "orgs/fictional-co/org.yaml") == {
        "schema": "work-copilot.overlay/v1", "name": "fictional-co", "placeholder": False,
        "source": "orgs/fictional-co/org.yaml", "work_site": "fictional.example.invalid", "kb_space": "FICDOCS",
        "jira_project": "FIC", "room": "Fictional review room"}


def test_the_example_renders_as_a_placeholder():
    out = wco.render(ROOT, org="orgs/example-co")
    assert out["placeholder"] is True and out["name"] == "example-co" and out["jira_project"] == "WORKPROJ"


def test_the_overlay_carries_nothing_but_the_org_values():
    out = wco.overlay(fictional(), "x")
    assert set(out) <= {"schema", "name", "placeholder", "source", "work_site", "kb_space", "jira_project", "room"}
    assert not any(word in json.dumps(out).lower() for word in ("token", "secret", "password", "bearer"))


def test_an_invalid_org_is_refused():
    bad = fictional()
    bad["params"]["merge_rule"] = "anything"
    with pytest.raises(ValueError, match="merge_rule"):
        wco.overlay(bad, "orgs/fictional-co/org.yaml")


def test_only_a_directory_under_orgs_is_read(tmp_path):
    with pytest.raises(ValueError, match="under orgs/"):
        wco.render(ROOT, org="shared")
    with pytest.raises(ValueError, match="names no org"):
        wco.render(ROOT, harness="suite-default")


def test_the_cli_writes_the_file(tmp_path, capsys):
    out = tmp_path / "work-copilot-overlay.json"
    assert wco.main(["--org", "orgs/example-co", "--out", str(out)]) == 0
    assert json.loads(out.read_text(encoding="utf-8"))["name"] == "example-co"
    assert "work-copilot overlay apply" in capsys.readouterr().out
    assert wco.main(["--org", "orgs/missing"]) == 2


def test_install_local_prints_the_commands_only_for_a_harness_with_an_org():
    lines = il.work_copilot_commands(ROOT, "work-default")
    assert len(lines) == 2
    assert "work_copilot_overlay.py" in lines[0] and "--harness work-default" in lines[0]
    assert lines[1] == "work-copilot overlay apply work-copilot-overlay.json"
    assert il.work_copilot_commands(ROOT, "suite-default") == []
