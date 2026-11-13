"""The extract-records skill (KAN-435): its seams, and the example sources with expected records.

The fixture cases under tests/fixtures/extract-records/ are reused by the extraction eval (KAN-464). These tests check
the cases are consistent on their own; with ai-dlc importable, or its CLI on PATH (as in CI), they also run
`knowledge check` over each tree.
"""

import os
import re
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest
import sys

import yaml

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "shared/work-system/skills/extract-records/SKILL.md"
CASES = ROOT / "tests/fixtures/extract-records"
MANIFEST = yaml.safe_load((CASES / "cases.yaml").read_text())["cases"]
# Vendor tools and products the skill must not name: it calls ai-dlc roles only.
VENDORS = re.compile(r"jira|confluence|atlassian|mcp__|github|\bgh\b|zoom|google meet|symphony|slack|notion", re.I)


def header(path: Path) -> dict:
    text = path.read_text()
    assert text.startswith("---\n"), path
    return yaml.safe_load(text.split("---\n", 2)[1])


def tree(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def test_skill_is_registered_for_every_harness():
    targets = yaml.safe_load((ROOT / "shared/work-system/targets.yaml").read_text())
    sys.path.insert(0, str(ROOT / "scripts"))
    import sync_shared

    common = sync_shared.shared_skills(ROOT / "shared/work-system", targets, targets["harnesses"], [])
    assert all("extract-records" in skills for skills in common.values())
    for name in targets["harnesses"]:
        assert (ROOT / "harnesses" / name / "skills/extract-records/SKILL.md").is_file()


def test_skill_calls_ai_dlc_roles_only():
    text = SKILL.read_text()
    assert not VENDORS.findall(text), VENDORS.findall(text)
    assert "ai-dlc knowledge check" in text
    assert "ai-dlc knowledge records propose" in text
    assert "{{wall}}" in text and "{{scope_map}}" in text


def test_skill_keeps_the_trial_1_rules():
    text = SKILL.read_text()
    for rule in ("untrusted data", "owner: unknown", "Never write to the wiki", "never merges",
                 "never `team` by default", "Never a copy of the title", "never a ticket key",
                 "quotable sentence", "Restated rules produce nothing", "would a reviewer delete this?",
                 "Ceilings per Source", "Default: fold it into the decision record"):
        assert rule in text, rule


@pytest.mark.parametrize("case", MANIFEST, ids=[c["id"] for c in MANIFEST])
def test_case_is_consistent(case):
    before, after = CASES / case["id"] / "before", CASES / case["id"] / "after"
    assert header(before / case["source"])["status"] == "raw"
    source = header(after / case["filed_as"])
    assert source["type"] == "source" and source["status"] == "processed"
    roots = tomllib.loads((after / "knowledge.toml").read_text())["check"]["roots"]
    assert case["filed_as"].split("/")[0] in roots and case["source"].split("/")[0] not in roots
    old, new = tree(before), tree(after)
    assert old[case["source"]] == new[case["source"]], "the inbox payload is left to expire"
    changed = sorted(p for p in new if old.get(p) != new[p])
    assert changed == sorted(case["expect"]), "after/ differs from before/ exactly in the expected files"
    assert set(old) <= set(new), "a run never deletes a file"
    records = [p for p in new if p.endswith(".md") and not p.endswith("README.md")]
    ids = {header(after / p)["id"]: header(after / p) for p in records}
    for path in case["expect"]:
        record = header(after / path)
        if record["type"] == "source":
            continue
        assert record.get("description") != record.get("title"), path
        for link in record["links"]:
            if link["type"] == "derived_from":
                assert ids[link["target"]]["type"] == "source", f"{path}: derived_from must name a source record"
        if record["type"] == "action" and record["owner"] == "unknown":
            assert "owner-unknown" in record.get("tags", []), path
        if path not in old:
            assert {"type": "derived_from", "target": source["id"]} in record["links"], path
            assert any(e.get("id") == source["id"] and e.get("hash") for e in record["sources"]), path


@pytest.mark.parametrize("case", MANIFEST, ids=[c["id"] for c in MANIFEST])
def test_case_passes_knowledge_check(case):
    """Each example passes `knowledge check` at the pinned ai-dlc: through the CLI that CI installs at AI_DLC_REF, so
    a pin bump that breaks an example fails CI (KAN-485), else through the module where only that is importable."""
    cli = shutil.which("ai-dlc")
    knowledge_check = None
    if cli is None:
        try:
            from ai_dlc.documentation import knowledge_check
        except ImportError:
            knowledge_check = None
    if knowledge_check is None and cli is None:
        if os.environ.get("CI"):
            pytest.fail("CI installs the ai-dlc CLI at AI_DLC_REF (.github/workflows/check.yml); it is not on PATH")
        pytest.skip("needs ai-dlc (the module or the CLI)")
    for side in ("before", "after"):
        tree = CASES / case["id"] / side
        if knowledge_check is not None:
            result = knowledge_check.check_records(tree)
            assert result["failures"] == [], (side, result["failures"])
        else:
            r = subprocess.run([cli, "knowledge", "check", "."], cwd=tree, capture_output=True, text=True)
            assert r.returncode == 0, (side, r.stdout + r.stderr)
