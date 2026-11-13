"""knowledge-howto (KAN-469): a session asked "how do I..." answers from the teammate guide in docs/knowledge/.

The skill carries a map from questions to guide pages and sections, not a copy of the pages: the guide names tickets
and placeholders that must not ride into the work harness. These tests keep the map and the guide in step.
"""

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
GUIDE = ROOT / "docs" / "knowledge"
SKILL = ROOT / "shared" / "work-system" / "skills" / "knowledge-howto" / "SKILL.md"
ROW = re.compile(r"^\| [^|]+ \| `(?P<page>[A-Za-z]+\.md)`, (?P<section>[^|]+?) \| [^|]+ \|$", re.M)


def _rows() -> list[tuple[str, str]]:
    text = SKILL.read_text(encoding="utf-8")
    rows = [(m["page"], m["section"].strip()) for m in ROW.finditer(text)]
    table = [ln for ln in text.splitlines() if ln.startswith("| ") and not ln.startswith(("| Question", "| ---"))]
    assert len(rows) == len(table), "a map row does not read `| question | `page.md`, section | answer |`"
    return rows


def _headings(page: str) -> list[str]:
    text = (GUIDE / page).read_text(encoding="utf-8")
    return [h.strip() for h in re.findall(r"^## (.+)$", text, re.M)]


def test_skill_is_shipped_to_every_work_system_harness():
    targets = yaml.safe_load((ROOT / "shared/work-system/targets.yaml").read_text(encoding="utf-8"))
    assert "knowledge-howto" in targets["skills"]
    for h in targets["harnesses"]:
        assert (ROOT / "harnesses" / h / "skills" / "knowledge-howto" / "SKILL.md").is_file(), h


def test_every_guide_page_is_in_the_map():
    pages = {p.name for p in GUIDE.glob("*.md")}
    mapped = {page for page, _ in _rows()}
    assert pages and pages <= mapped, f"guide pages missing from the skill's map: {sorted(pages - mapped)}"


def test_every_section_the_map_names_exists_on_its_page():
    rows = _rows()
    assert len(rows) >= 10
    for page, section in rows:
        assert (GUIDE / page).is_file(), page
        if section.startswith("all "):
            continue
        headings = _headings(page)
        if section.isdigit():  # a quickstart step: "## 3. Put the sample meeting in the inbox"
            assert any(h.startswith(f"{section}. ") for h in headings), (page, section)
        else:
            assert any(h.startswith(section) for h in headings), (page, section, headings)


def test_quickstart_step_count_matches_the_map():
    steps = [h for h in _headings("quickstart.md") if re.match(r"\d+\. ", h)]
    assert any(section == f"all {['zero', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight'][len(steps)]} steps"
               for page, section in _rows() if page == "quickstart.md")


def test_skill_is_read_only_and_names_no_ticket():
    text = SKILL.read_text(encoding="utf-8")
    assert not re.search(r"\b[A-Z]+-\d+\b", text), "a ticket key would leak into the work harness"
    assert "Never run, propose, approve or merge anything" in text
    front = text.split("---")[1]
    assert "never invents a step" in front
    assert re.search(r"^allowed-tools: Read, Grep, Glob$", front, re.M), "the skill must be read-only by its tools"
