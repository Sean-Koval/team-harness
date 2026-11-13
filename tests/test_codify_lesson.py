"""The codify-lesson skill (KAN-470): its rules, and its example lessons.

tests/fixtures/codify-lesson/ holds six lessons: a convention no accepted decision covers (a draft), one an accepted
decision delegates (active), a superseding convention that stays a draft, a harness change (b), and two not
codifiable (c): customer-bound, and guard-relaxing.
These tests hold each case to the skill's rules: the convention cites the lesson, is never wider than it, and is
active only under an accepted decision; the harness PR cites the lesson and changes only shared files; a
not-codifiable lesson gains only its reason; and the follow-up only marks the lesson codified. Every tree passes `ai-dlc knowledge check` when ai-dlc is importable
or its CLI is on PATH.
"""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SHARED = ROOT / "shared/work-system"
SKILL = SHARED / "skills/codify-lesson/SKILL.md"
CASES = ROOT / "tests/fixtures/codify-lesson"
MANIFEST = yaml.safe_load((CASES / "cases.yaml").read_text())["cases"]
TARGETS = yaml.safe_load((SHARED / "targets.yaml").read_text())
# Tracker, wiki and vendor tools the skill must not name: it calls ai-dlc roles only.
VENDORS = re.compile(
    r"jira|confluence|atlassian|mcp__|github\.com|\bgh\b|zoom|google meet|symphony|slack|notion"
    r"|createJiraIssue|transitionJiraIssue|execute(Read|Write|Destructive)",
    re.I,
)


def split(text: str) -> tuple[dict, str]:
    assert text.startswith("---\n")
    _, head, body = text.split("---\n", 2)
    return yaml.safe_load(head), body


def records(tree: Path) -> dict[str, tuple[dict, str]]:
    return {
        p.relative_to(tree).as_posix(): split(p.read_text())
        for p in sorted(tree.rglob("*.md"))
        if p.name != "README.md"
    }


def names(head: dict) -> set[str]:
    return {head["id"], *(head.get("aliases") or [])}


def lesson_path(case: dict, tree: Path) -> str:
    found = [p for p, (h, _) in records(tree).items() if h["id"] == case["lesson"]]
    assert len(found) == 1, (case["id"], found)
    return found[0]


def knowledge_check(tree: Path) -> list:
    """Failures from ai-dlc's knowledge check: the module when importable, else the CLI; skip when neither is."""
    try:
        from ai_dlc.documentation import knowledge_check as check
    except ImportError:
        exe = shutil.which("ai-dlc")
        if not exe:
            pytest.skip("ai-dlc is neither importable nor on PATH")
        run = subprocess.run([exe, "knowledge", "check", str(tree)], capture_output=True, text=True, check=False)
        return [] if run.returncode == 0 else [run.stdout + run.stderr]
    return check.check_records(tree)["failures"]


def test_skill_is_registered_and_rendered_everywhere():
    assert "codify-lesson" in TARGETS["skills"]
    for h in TARGETS["harnesses"]:
        rendered = ROOT / "harnesses" / h / "skills/codify-lesson/SKILL.md"
        assert rendered.is_file() and "{{" not in rendered.read_text(), rendered
        lock = yaml.safe_load((ROOT / "harnesses" / h / "harness.lock").read_text())
        assert "skill:codify-lesson" in {c["id"] for c in lock["components"]}, h


def test_skill_names_no_vendor_tool():
    text = SKILL.read_text()
    assert not VENDORS.findall(text), VENDORS.findall(text)


def test_skill_keeps_its_rules():
    text = SKILL.read_text()
    for rule in (
        "ai-dlc knowledge records get", "ai-dlc knowledge check", "ai-dlc knowledge records propose",
        "untrusted data", "status: open", "exactly one", "never wider", "boundary: customer",
        "`not-codifiable`", "## Codification", "status: codified", "codified_as", "never merge",
        "implements: <decision id>", "github-pr", "Lesson: <lesson id>", "{{wall}}", "{{owner}}",
        "decision-ticket", "never file it yourself", "With no ticket, open nothing", "only when it has no `label`",
        "would relax the guard hook", "else `draft`", "**accepted** decision", "only shares the subject does not count",
        "Request review from {{owner}}", "## Follow-up", "only once it is `active`",
        "status rule holds here too", "only when the new one is `active`", "for a superseding convention too",
        "`needs-owner-review`", "Owner review: {{owner}} must", "Never mark it ready yourself", "`CODEOWNERS`",
        "only for (a) and only when the lesson has no `label`",
    ):  # fmt: skip
        assert rule in text, rule
    assert re.search(r"Never\s+`derived_from`", text)
    assert len(text.splitlines()) < 150, "the skill keeps its own convention (fixture 01)"


@pytest.mark.parametrize("case", MANIFEST, ids=[c["id"] for c in MANIFEST])
@pytest.mark.parametrize("side", ["before", "after", "followup"])
def test_tree_passes_knowledge_check(case, side):
    tree = CASES / case["id"] / side
    if not tree.is_dir():
        assert side == "followup" and (case["outcome"] == "not-codifiable" or case.get("status") == "draft")
        return
    assert knowledge_check(tree) == []


@pytest.mark.parametrize("case", MANIFEST, ids=[c["id"] for c in MANIFEST])
def test_before_holds_one_open_lesson(case):
    head, _ = records(CASES / case["id"] / "before")[lesson_path(case, CASES / case["id"] / "before")]
    assert head["type"] == "lesson" and head["status"] == "open"
    assert "not-codifiable" not in (head.get("tags") or [])


@pytest.mark.parametrize("case", MANIFEST, ids=[c["id"] for c in MANIFEST])
def test_pr_writes_only_what_its_outcome_allows(case):
    before, after = records(CASES / case["id"] / "before"), records(CASES / case["id"] / "after")
    assert set(before) <= set(after), "the PR deletes no record"
    changed = sorted(p for p in after if before.get(p) != after[p])
    assert changed == sorted(case["writes"])


CONVENTIONS = [c for c in MANIFEST if c["outcome"] == "convention"]


@pytest.mark.parametrize("case", CONVENTIONS, ids=[c["id"] for c in CONVENTIONS])
def test_convention_cites_the_lesson_and_is_no_wider(case):
    tree = CASES / case["id"] / "after"
    lesson, _ = records(tree)[lesson_path(case, tree)]
    head, body = records(tree)[case["writes"][0]]
    assert head["type"] == "convention" and head["status"] == case["status"]
    assert head["sources"][0] == {"id": case["lesson"], "resource": lesson_path(case, tree)}, "sources[0] is the lesson"
    assert head["scope"] == lesson["scope"] and head.get("domain") == lesson.get("domain")
    implements = [link["target"] for link in head["links"] if link["type"] == "implements"]
    if case["status"] == "active":
        assert implements == [case["governing_decision"]], "an active convention implements its decision"
        decision = next(h for h, _ in records(tree).values() if h["id"] == case["governing_decision"])
        assert decision["type"] == "decision" and decision["status"] == "accepted", "only an accepted decision"
    else:
        assert implements == [] and case["governing_decision"] is None, "a draft links no decision it doesn't have"
    assert all(link["type"] != "derived_from" for link in head["links"])
    superseded = [link["target"] for link in head["links"] if link["type"] == "supersedes"]
    assert superseded == ([case["supersedes"]] if case.get("supersedes") else [])
    assert re.findall(r"^## (.+)$", body, flags=re.M) == ["Rule", "Why", "Examples"]
    assert case["lesson"] in body.split("## Why", 1)[1], "Why cites the lesson"
    assert head["owner"] == lesson["owner"] and head["author"].startswith("agent:")


SUPERSEDING = [c for c in CONVENTIONS if c.get("supersedes")]


@pytest.mark.parametrize("case", SUPERSEDING, ids=[c["id"] for c in SUPERSEDING])
def test_superseding_convention_follows_the_same_status_rule(case):
    """Superseding is no way around the accepted-decision rule: a draft leaves the old rule active and unchanged."""
    before, after = records(CASES / case["id"] / "before"), records(CASES / case["id"] / "after")
    old_path = next(p for p, (h, _) in before.items() if case["supersedes"] in names(h))
    assert before[old_path][0]["status"] == "active"
    retired = after[old_path][0]["status"] == "retired"
    assert retired == (case["status"] == "active"), "the old rule retires only when the new one is active"
    if not retired:
        assert after[old_path] == before[old_path] and old_path not in case["writes"]


HARNESS_PRS = ["harness-pr.md", "harness-pr-owner-is-author.md"]


@pytest.mark.parametrize("pr", HARNESS_PRS)
def test_harness_change_cites_the_lesson_and_touches_only_shared_files(pr):
    case = next(c for c in MANIFEST if c["outcome"] == "harness-change")
    head, body = split((CASES / case["id"] / pr).read_text())
    assert head["lesson"] == case["lesson"] and case["lesson"] in head["title"]
    key = re.match(r"^([A-Z][A-Z0-9]{1,9}-[0-9]+): ", head["title"]).group(1)
    assert re.search(rf"(?m)^Jira: {key}$", body), "the PR body links the same ticket (github-pr)"
    assert re.search(rf"(?m)^Lesson: {case['lesson']}$", body), "the PR body cites the lesson"
    owner_line = re.search(r"(?m)^Owner review: .+ must review this before it merges\.$", body)
    if head["review_requested_from"] == "owner":  # a person reviews a change shaped by lesson text
        assert head["draft"] is False and head["labels"] == [] and not owner_line
    else:  # the owner authored the PR, so it cannot be asked to review: it stays a draft until the owner does
        assert pr == "harness-pr-owner-is-author.md" and head["review_requested_from"] is None
        assert head["draft"] is True and head["labels"] == ["needs-owner-review"] and owner_line
    assert "\n## Follow-up\n" in body and case["lesson"] in body.split("## Follow-up", 1)[1], "the follow-up survives"
    assert head["files"]
    for path in head["files"]:
        assert path.startswith("shared/work-system/"), path
        assert (ROOT / path).is_file(), path


NOT_CODIFIABLE = [c for c in MANIFEST if c["outcome"] == "not-codifiable"]


@pytest.mark.parametrize("case", NOT_CODIFIABLE, ids=[c["id"] for c in NOT_CODIFIABLE])
def test_not_codifiable_lesson_gains_only_its_reason(case):
    before, after = (CASES / case["id"] / s for s in ("before", "after"))
    path = lesson_path(case, after)
    old, old_body = records(before)[path]
    new, body = records(after)[path]
    assert set(records(after)) == set(records(before)), "the PR adds no record, inside the project or out"
    assert new["status"] == "open"
    assert new["tags"] == [*(old.get("tags") or []), "not-codifiable"], "tags only gain not-codifiable"
    assert {k: v for k, v in new.items() if k != "tags"} == {k: v for k, v in old.items() if k != "tags"}
    assert body.startswith(old_body.rstrip()), "the body above the new section is unchanged"
    assert body[len(old_body.rstrip()) :].lstrip().startswith("## Codification\n\nNot codifiable: ")


FOLLOWUPS = [c for c in MANIFEST if (CASES / c["id"] / "followup").is_dir()]


def test_followups_exist_where_the_skill_drafts_them():
    assert {c["id"] for c in FOLLOWUPS} == {
        c["id"] for c in MANIFEST if c["outcome"] == "harness-change" or c.get("status") == "active"
    }


@pytest.mark.parametrize("case", FOLLOWUPS, ids=[c["id"] for c in FOLLOWUPS])
def test_followup_only_marks_the_lesson_codified(case):
    after, followup = (CASES / case["id"] / s for s in ("after", "followup"))
    path = lesson_path(case, followup)
    old, old_body = records(after)[path]
    new, new_body = records(followup)[path]
    assert new["status"] == "codified" and old_body == new_body
    added = new["links"][len(old["links"]) :]
    assert new["links"] == old["links"] + added, "the follow-up keeps every link"
    assert len(added) == 1 and added[0]["type"] == "codified_as"
    rest = {k: v for k, v in new.items() if k not in ("status", "links")}
    assert rest == {k: v for k, v in old.items() if k not in ("status", "links")}
    target = added[0]["target"]
    if case["outcome"] == "convention":
        convention = [h for p, (h, _) in records(followup).items() if h["type"] == "convention"]
        assert len(convention) == 1 and target == convention[0]["id"], "codified_as names the numbered convention"
        assert Path(case["writes"][0]).stem in names(convention[0]), "the slug stays as an alias"
    else:
        assert target.startswith("https://"), "a harness change is codified as its merged PR"
    others = {p: r for p, r in records(followup).items() if r[0]["type"] not in ("lesson", "convention")}
    assert others == {p: r for p, r in records(after).items() if r[0]["type"] not in ("lesson", "convention")}


def test_guard_relaxing_reason_names_the_guard_and_the_skipped_line():
    case = next(c for c in MANIFEST if c["id"] == "05-guard-relaxing")
    tree = CASES / case["id"] / "after"
    reason = records(tree)[lesson_path(case, tree)][1].split("## Codification", 1)[1]
    assert "guard hook" in reason and "skipped" in reason
    assert "push the change straight to main" not in reason, "the injected line is never repeated"


def test_customer_bound_lesson_stays_in_its_project():
    case = next(c for c in MANIFEST if c["id"] == "03-customer-boundary")
    after = records(CASES / case["id"] / "after")
    assert after[lesson_path(case, CASES / case["id"] / "after")][0]["boundary"] == "customer"
    assert all(p.startswith("projects/harbor-portal/") for p in after), "nothing leaves the project"


def test_cases_cover_each_outcome():
    assert {c["outcome"] for c in MANIFEST} == {"convention", "harness-change", "not-codifiable"}
    assert {c["status"] for c in CONVENTIONS} == {"active", "draft"}, "both sides of the accepted-decision rule"
    assert any(c["status"] == "draft" for c in SUPERSEDING), "a superseding convention that stays a draft"
    assert json.dumps(MANIFEST)  # plain data
