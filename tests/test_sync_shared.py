"""scripts/sync_shared.py: the shared work-system layer is edited once and every target harness carries the same bytes."""

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import sync_shared  # noqa: E402


def copy_repo(tmp_path: Path) -> Path:
    for d in ("shared", "orgs", "harnesses/suite-default", "harnesses/work-default"):
        shutil.copytree(ROOT / d, tmp_path / d)
    return tmp_path


def test_repository_is_in_sync():
    stale, problems = sync_shared.plan(ROOT)
    assert stale == [] and problems == []


def test_hand_edited_copy_is_caught(tmp_path):
    root = copy_repo(tmp_path)
    skill = root / "harnesses/work-default/skills/decision-ticket/SKILL.md"
    skill.write_text(skill.read_text(encoding="utf-8") + "\nan edit made in the copy\n", encoding="utf-8", newline="\n")
    stale, _ = sync_shared.plan(root)
    assert [dst for _, dst, _ in stale] == [root / "harnesses/work-default/skills/decision-ticket"]


def test_unregistered_hook_is_a_problem(tmp_path):
    root = copy_repo(tmp_path)
    settings = root / "harnesses/suite-default/native/claude-code/settings.json"
    data = json.loads(settings.read_text(encoding="utf-8"))
    data["hooks"]["PreToolUse"] = []
    settings.write_text(json.dumps(data), encoding="utf-8")
    _, problems = sync_shared.plan(root)
    assert any("does not register" in p for p in problems)


def test_hook_must_see_mcp_tools(tmp_path):
    root = copy_repo(tmp_path)
    settings = root / "harnesses/suite-default/native/claude-code/settings.json"
    data = json.loads(settings.read_text(encoding="utf-8"))
    data["hooks"]["PreToolUse"][0]["matcher"] = "Bash|PowerShell"
    settings.write_text(json.dumps(data), encoding="utf-8")
    _, problems = sync_shared.plan(root)
    assert any("must match Bash, PowerShell and mcp__" in p for p in problems)


def test_hook_must_see_powershell_calls(tmp_path):
    """On Windows without Git Bash, Claude Code's shell tool is PowerShell (KAN-482)."""
    root = copy_repo(tmp_path)
    settings = root / "harnesses/suite-default/native/claude-code/settings.json"
    data = json.loads(settings.read_text(encoding="utf-8"))
    data["hooks"]["PreToolUse"][0]["matcher"] = "Bash|mcp__.*"
    settings.write_text(json.dumps(data), encoding="utf-8")
    _, problems = sync_shared.plan(root)
    assert any("must match Bash, PowerShell and mcp__" in p for p in problems)


def test_unfilled_placeholder_is_a_problem(tmp_path):
    root = copy_repo(tmp_path)
    skill = root / "shared/work-system/skills/work-docs/SKILL.md"
    skill.write_text(skill.read_text(encoding="utf-8") + "\nAsk {{nobody_defined_this}}.\n", encoding="utf-8", newline="\n")
    _, problems = sync_shared.plan(root)
    assert any("nobody_defined_this" in p for p in problems)


def test_no_copy_keeps_a_placeholder():
    for h in ("suite-default", "work-default"):
        for p in (ROOT / "harnesses" / h).rglob("*"):
            if p.is_file() and p.suffix in (".md", ".py"):
                assert not sync_shared.PLACEHOLDER.search(p.read_text(encoding="utf-8")), p


def test_work_default_carries_no_personal_rules():
    """The hard wall: the company harness names no person, no personal label and no personal knowledge base."""
    for p in (ROOT / "harnesses/work-default").rglob("*"):
        if p.is_file():
            text = p.read_text(encoding="utf-8").lower()
            for word in ("sean", "needs-sean", "human-decision", "second brain", "seanmkoval", "kan-"):
                assert word not in text, f"{p.relative_to(ROOT)} mentions {word!r}"


def test_suite_default_decisions_carry_the_human_decision_label():
    """Sean's decisions view filters on `human-decision` (KAN-484): a Decision filed by the skill must carry it."""
    skill = (ROOT / "harnesses/suite-default/skills/decision-ticket/SKILL.md").read_text(encoding="utf-8")
    labels = next((line for line in skill.splitlines() if line.startswith("| Labels |")), "")
    assert labels, "the decision-ticket skill has no Labels row"
    for label in ("`decision`", "`human-decision`", "assign it to Sean"):
        assert label in labels, label


def test_merge_rules_differ_by_harness():
    suite = (ROOT / "harnesses/suite-default/skills/github-pr/SKILL.md").read_text(encoding="utf-8")
    work = (ROOT / "harnesses/work-default/skills/github-pr/SKILL.md").read_text(encoding="utf-8")
    assert "you may merge" in suite and "Merging: never." in work
    assert (ROOT / "harnesses/work-default/skills/release-approvals/SKILL.md").is_file()
    assert not (ROOT / "harnesses/suite-default/skills/release-approvals").exists()


def test_needs_owner_review_prs_stay_drafts_and_unmerged():
    # codify-lesson leaves a PR a draft labelled needs-owner-review when its owner can't be asked to review it (KAN-470).
    # Neither the ready step nor the merge rule may undo that (KAN-488).
    def skill(harness):
        text = (ROOT / f"harnesses/{harness}/skills/github-pr/SKILL.md").read_text(encoding="utf-8")
        return " ".join(text.split())

    for harness in ("suite-default", "work-default"):
        text = skill(harness)
        assert "unless it carries the label `needs-owner-review` or its body has an `Owner review:` line" in text, \
            harness
        assert "gh pr view <n> --json labels,body" in text, harness
        assert "never mark it ready, remove the label, drop its `Owner review:` line or open a new PR for its branch" \
            " yourself" in text, harness
    assert "stays a draft until Sean has reviewed it" in skill("suite-default")
    assert "stays a draft until the ticket's owner has reviewed it" in skill("work-default")
    suite = skill("suite-default")
    assert "A draft, a PR labelled `needs-owner-review` or one whose body has an `Owner review:` line counts as one" \
        " somebody asked to review" in suite
    assert "never merge such a PR or turn on auto-merge for it" in suite and "--json isDraft,labels,body" in suite


def test_ticket_template_is_the_one_the_skill_ships():
    assert (ROOT / "templates/ticket.md").read_bytes() == \
        (ROOT / "shared/work-system/skills/jira-ticket/ticket-template.md").read_bytes()


# --- KAN-353: the behavior specs' approval regex is the org's approval summaries


def _org(*summaries, role="approval"):
    return {"ticket_types": [{"id": f"t{i}", "role": role, "summary": s} for i, s in enumerate(summaries)]}


def test_approval_regex_is_each_summarys_fixed_text():
    import re
    rx = sync_shared.approval_regex(_org("SRE approval: {pr_title}", "Infosec review: {repo} {work_key}"))
    assert rx == r"(?i)(\bSRE approval:|\bInfosec review:)"
    assert re.search(rx, '{"summary": "sre APPROVAL: SVC-1 add the queue"}')
    assert not re.search(rx, '{"summary": "Infosec reviewer onboarding"}')


def test_approval_regex_escapes_and_skips_what_has_no_fixed_text():
    import re
    rx = sync_shared.approval_regex(_org("[CAB] change (P1) {pr_title}", "{work_key} review", "CAB: {x}",
                                         "CAB: {y}"))
    assert rx == r"(?i)(\[CAB\] change \(P1\)|\bCAB:)"
    assert re.search(rx, "[cab] change (p1) ship it") and not re.search(rx, "CAB change P1")
    assert sync_shared.approval_regex(_org("{work_key} review")) == sync_shared.NEVER
    assert sync_shared.approval_regex(_org("SRE approval: {x}", role="routine")) == sync_shared.NEVER
    assert not re.search(sync_shared.NEVER, "a") and not re.search(sync_shared.NEVER, "")


def test_render_spec_sets_only_the_marked_lines():
    mark = sync_shared.SPEC_MARK
    text = (f'a:\n    where: {{input: {{regex: "old \\" quoted"}}}}  {mark}\n'
            f'    where: {{input: {{regex: "kept"}}}}\nb:\n  where: {{input: {{regex: "x"}}}}  {mark}\n')
    out, n = sync_shared.render_spec(text, r"(?i)(\bSRE approval:)")
    assert n == 2
    assert out.splitlines() == [
        "a:", f'    where: {{input: {{regex: "(?i)(\\\\bSRE approval:)"}}}}  {mark}',
        '    where: {input: {regex: "kept"}}', "b:", f'  where: {{input: {{regex: "(?i)(\\\\bSRE approval:)"}}}}  {mark}']
    import yaml
    assert yaml.safe_load(out.splitlines()[1].split("  #")[0].strip())["where"]["input"]["regex"] == \
        r"(?i)(\bSRE approval:)"


def test_a_changed_org_restales_the_work_spec(tmp_path):
    root = copy_repo(tmp_path)
    shutil.copytree(ROOT / "flightdeck" / "specs", root / "flightdeck" / "specs")
    assert sync_shared.plan(root) == ([], [])
    org = root / "orgs/example-co/org.yaml"
    org.write_text(org.read_text(encoding="utf-8").replace("SRE approval: {pr_title}", "Change request: {pr_title}"),
                   encoding="utf-8", newline="\n")
    stale, problems = sync_shared.plan(root)
    assert problems == []
    spec = root / "flightdeck/specs/work-default.yaml"
    entry = next(s for s in stale if s[1] == spec)
    rendered = entry[2][""].decode("utf-8")
    assert rendered.count(r'"(?i)(\\bChange request:|\\bInfosec review:)"') == 2 and "SRE approval:" not in rendered
    sync_shared.write([entry], root)
    assert spec.read_text(encoding="utf-8") == rendered and not [s for s in sync_shared.plan(root)[0] if s[1] == spec]


def test_a_spec_without_the_mark_is_a_warning(tmp_path):
    root = copy_repo(tmp_path)
    (root / "flightdeck/specs").mkdir(parents=True)
    (root / "flightdeck/specs/work-default.yaml").write_text("id: x\n", encoding="utf-8")
    warnings: list[str] = []
    stale, problems = sync_shared.plan(root, warnings)
    assert stale == [] and problems == [] and any("has no line marked" in w for w in warnings)


def test_no_word_boundary_before_a_non_ascii_letter():
    assert sync_shared.approval_regex(_org("Überprüfung: {x}", "SRE approval: {y}")) == \
        r"(?i)(Überprüfung:|\bSRE approval:)"


def test_check_specs_ignores_the_generated_copies(monkeypatch, capsys):
    """CI checks the specs before it builds the copies a PR doesn't commit."""
    spec = sync_shared.ROOT / "flightdeck/specs/work-default.yaml"
    copy = sync_shared.ROOT / "harnesses/work-default/skills/decision-ticket"
    org = sync_shared.ROOT / "orgs/example-co/org.yaml"
    shared = sync_shared.ROOT / "shared/work-system/skills/decision-ticket"

    def plan(warnings=None):
        return [(shared, copy, {"": b""})], []
    monkeypatch.setattr(sync_shared, "plan", plan)
    assert sync_shared.main(["--check", "--specs"]) == 0 and sync_shared.main(["--check"]) == 1
    monkeypatch.setattr(sync_shared, "plan", lambda warnings=None: ([(org, spec, {"": b""})], []))
    assert sync_shared.main(["--check", "--specs"]) == 1
    assert "(edit orgs/example-co/org.yaml, then python scripts/sync_shared.py)" in capsys.readouterr().err
