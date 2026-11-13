"""The plan-to-tickets skill (KAN-446): its rules, and its worked example.

The example under shared/work-system/skills/plan-to-tickets/examples/ is an accepted decision with three plan items,
one not ready. These tests apply the skill's readiness test to it and check the first run drafts exactly the ready
items in the ticket layout, and that the rerun creates nothing.
"""

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = ROOT / "shared/work-system/skills/plan-to-tickets"
SKILL = SKILL_DIR / "SKILL.md"
EXAMPLES = SKILL_DIR / "examples"
# Vendor tools and products the skill must not name: it goes through ai-dlc's roles only.
VENDORS = re.compile(r"jira|confluence|atlassian|mcp__|github|\bgh\b|zoom|google meet|symphony|slack|notion", re.I)
SECTIONS = ["Goal", "What changes", "Acceptance criteria", "Verify", "Out of scope", "Governing spec"]
JUDGEMENT = re.compile(r"by hand|review it|looks right", re.I)


def split(path: Path) -> tuple[dict, str]:
    text = path.read_text()
    assert text.startswith("---\n"), path
    _, head, body = text.split("---\n", 2)
    return yaml.safe_load(head), body


def plan_items(body: str) -> dict[str, dict[str, list[str]]]:
    """`## Plan` items as {slug: {field: [values]}}; a list field collects its `- ` lines."""
    plan = body.split("\n## Plan\n", 1)[1]
    items: dict[str, dict[str, list[str]]] = {}
    for chunk in re.split(r"^### ", plan, flags=re.M)[1:]:
        slug, *lines = chunk.strip().splitlines()
        fields: dict[str, list[str]] = {}
        key = None
        for line in lines:
            if line.startswith("- ") and key:
                fields[key].append(line[2:])
            elif ":" in line:
                key, value = (s.strip() for s in line.split(":", 1))
                fields[key] = [value] if value else []
        items[slug.strip()] = fields
    return items


def not_ready(item: dict[str, list[str]], checks: list) -> list[str]:
    """The skill's readiness test (section 1): the reasons an item is not ready."""
    reasons = []
    repo = " ".join(item.get("Repo", []))
    if not repo or re.search(r",|\band\b|\ball\b|\beach\b", repo):
        reasons.append("repo")
    verify = " ".join(item.get("Verify", []))
    if not re.search(r"`[^`]+`", verify) or JUDGEMENT.search(verify):
        reasons.append("verify")
    if not item.get("Acceptance") and not checks:
        reasons.append("acceptance")
    if not item.get("Goal") or not item.get("What changes"):
        reasons.append("goal")
    return reasons


DECISION, DECISION_BODY = split(EXAMPLES / "decision.md")
ITEMS = plan_items(DECISION_BODY)
READY = [s for s, i in ITEMS.items() if not not_ready(i, DECISION.get("checks") or [])]


def test_skill_is_registered_for_every_harness():
    targets = yaml.safe_load((ROOT / "shared/work-system/targets.yaml").read_text())
    assert "plan-to-tickets" in targets["skills"]
    for name in targets["harnesses"]:
        copy = ROOT / "harnesses" / name / "skills/plan-to-tickets"
        assert (copy / "SKILL.md").is_file() and (copy / "examples/decision.md").is_file()


def test_skill_and_examples_name_no_vendor_tool():
    for path in sorted(SKILL_DIR.rglob("*.md")):
        found = VENDORS.findall(path.read_text())
        assert not found, f"{path.relative_to(ROOT)}: {found}"


def test_skill_keeps_its_rules():
    text = SKILL.read_text()
    for rule in ("`tracker` role", "ai-dlc knowledge records get", "Never `exec:agent`", "never set `exec:agent`",
                 "{type: implements, target: <decision id>}", "**PR base:** main", "The PR's base branch is main.",
                 "Plan item: <decision id>#<item-slug>", "status: accepted", "untrusted data", "filed_as:",
                 "FILING.md", "a rerun creates nothing new", "tracker_create", "{{wall}}", "{{owner}}"):
        assert rule in text, rule
    # the ticket layout, in order
    layout = text.split("```\n---\nsummary:", 1)[1].split("\n```\n", 1)[0]
    headings = re.findall(r"^## (.+)$", layout, flags=re.M)
    assert headings == SECTIONS
    for line in ("**Repo:**", "**Start after:**"):
        assert line in layout


def test_example_has_three_items_one_not_ready():
    assert DECISION["type"] == "decision" and DECISION["status"] == "accepted"
    assert list(ITEMS) == ["retention-job", "retention-check", "retention-notice"]
    assert READY == ["retention-job", "retention-check"]
    assert set(not_ready(ITEMS["retention-notice"], DECISION["checks"])) == {"repo", "verify"}


def test_first_run_drafts_exactly_the_ready_items():
    run = EXAMPLES / "run-1"
    assert sorted(p.stem for p in run.glob("*.md") if p.stem not in {"FILING", "report"}) == sorted(READY)
    report = (run / "report.md").read_text()
    assert len(re.findall(r"^Created: +\S", report, flags=re.M)) == 2
    assert re.search(r"^Not ready: +retention-notice: .*Question for", report, flags=re.M)
    filing = (run / "FILING.md").read_text()
    assert "retention-notice:" in filing.split("Not ready, not drafted:")[1]
    assert "exec:agent" not in filing.replace("to exec:agent", "")


@pytest.mark.parametrize("slug", READY)
def test_draft_follows_the_layout(slug):
    head, body = split(EXAMPLES / "run-1" / f"{slug}.md")
    item = ITEMS[slug]
    repo = item["Repo"][0]
    assert head["summary"] == f"{repo}: {item['Summary'][0]}"
    exec_label = "exec:human" if item.get("Exec") == ["human"] else "exec:pair"
    assert head["labels"] == ["proposed", f"repo:{repo}", exec_label]
    assert {"type": "implements", "target": DECISION["id"]} in head["links"]
    assert head["filed_as"] is None
    assert re.findall(r"^## (.+)$", body, flags=re.M) == SECTIONS
    assert f"**Repo:** {repo}\n" in body and "**PR base:** main." in body
    acceptance = body.split("## Acceptance criteria\n", 1)[1].split("\n## ", 1)[0]
    for line in item["Acceptance"]:
        assert f"* {line}\n" in acceptance
    for check in DECISION["checks"]:
        assert f"flightdeck check `{check['id']}` holds" in acceptance
    assert acceptance.rstrip().endswith("* The PR's base branch is main.")
    assert item["Verify"][0] in body.split("## Verify\n", 1)[1]
    assert f"Decision {DECISION['id']} " in body
    assert body.rstrip().endswith(f"Plan item: {DECISION['id']}#{slug}")


def test_rerun_creates_nothing():
    report = (EXAMPLES / "run-2.md").read_text()
    assert re.search(r"^Created: +none$", report, flags=re.M)
    unchanged = re.findall(r"^Unchanged: +(\S+) ", report, flags=re.M)
    assert sorted(unchanged) == sorted(READY)
