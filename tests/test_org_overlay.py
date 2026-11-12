"""The org overlay slot: orgs/<org>/org.yaml is validated, its params win, its skills are rendered into the harness,
and suite-default never takes one (the work/home wall)."""

import copy
import shutil
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import sync_shared  # noqa: E402

EXAMPLE = yaml.safe_load((ROOT / "orgs/example-co/org.yaml").read_text())
WD = "harnesses/work-default"


def copy_repo(tmp_path: Path) -> Path:
    for d in ("shared", "orgs", "harnesses/suite-default", "harnesses/work-default"):
        shutil.copytree(ROOT / d, tmp_path / d)
    return tmp_path


def edit_yaml(path: Path, change) -> None:
    data = yaml.safe_load(path.read_text())
    change(data)
    path.write_text(yaml.safe_dump(data, sort_keys=False))


def test_example_org_is_valid_and_a_placeholder():
    assert sync_shared.validate_org(EXAMPLE, "example") == []
    assert EXAMPLE["placeholder"] is True and EXAMPLE["name"] == "example-co"


def test_targets_name_the_example_org_for_work_default_only():
    t = yaml.safe_load((ROOT / "shared/work-system/targets.yaml").read_text())
    assert t["harnesses"]["work-default"]["org"] == "orgs/example-co"
    assert "org" not in (t["harnesses"]["suite-default"] or {})


def _broken(change):
    org = copy.deepcopy(EXAMPLE)
    change(org)
    return sync_shared.validate_org(org, "org.yaml", {"tracker", "kb_site", "kb_space", "owner"})


@pytest.mark.parametrize("change, message", [
    (lambda o: o.update(extra=1), "unknown key 'extra'"),
    (lambda o: o.update(schema="team-harness.org/v2"), "schema must be"),
    (lambda o: o["gates"][0].update(colour="red"), "unknown key 'colour'"),
    (lambda o: o["ticket_types"][0].update(owner="x"), "unknown key 'owner'"),
    (lambda o: o["review_request"].update(post=True), "unknown key 'post'"),
    (lambda o: o["gates"][1].update(id="sre"), "gate id 'sre' is not unique"),
    (lambda o: o["gates"][1].update(pr_line="sre"), "pr_line 'sre' is not unique"),
    (lambda o: o["gates"][0].update(pr_line="Jira"), "one of the PR check's own lines"),
    (lambda o: o["gates"][0].update(ticket="nope"), "not a ticket_types id"),
    (lambda o: o["gates"][0].update(ticket="work"), "must have role approval"),
    (lambda o: o["gates"][0].update(when="sometimes"), "when must be always"),
    (lambda o: o["gates"][0].update(when={"branches": ["main"]}), "when must be always"),
    (lambda o: o["gates"][0].update(when={"paths": []}), "when.paths must be a non-empty list"),
    (lambda o: o["gates"][0].update(filed_by="bot"), "filed_by must be agent or person"),
    (lambda o: o["gates"][0].update(links=["pr", "wiki"]), "links must be a list of"),
    (lambda o: o["ticket_types"][1].update(role="gate"), "role must be one of"),
    (lambda o: o["ticket_types"][1].update(summary="{nobody}"), "summary field {nobody}"),
    (lambda o: o["ticket_types"].append(dict(o["ticket_types"][0])), "ticket type id 'work' is not unique"),
    (lambda o: o["review_request"].update(template="{pr_url} {who}"), "template field {who}"),
    (lambda o: o["review_request"].pop("room"), "review_request.room is required"),
    (lambda o: o["params"].update(not_a_param="x"), "not a profile parameter"),
    (lambda o: o["params"].update(org_gates="x"), "generated from org.yaml"),
])
def test_validation_errors(change, message):
    problems = _broken(change)
    assert any(message in p for p in problems), problems


def test_when_paths_and_labels_are_accepted():
    assert _broken(lambda o: o["gates"][1].update(when={"paths": ["infra/**"], "labels": ["security"]})) == []


def test_invalid_org_fails_the_check(tmp_path):
    root = copy_repo(tmp_path)
    edit_yaml(root / "orgs/example-co/org.yaml", lambda o: o["gates"][0].update(filed_by="bot"))
    _, problems = sync_shared.plan(root)
    assert any("filed_by must be agent or person" in p for p in problems)


def test_org_params_win_over_the_profile(tmp_path):
    root = copy_repo(tmp_path)
    edit_yaml(root / "orgs/example-co/org.yaml", lambda o: o["params"].update(tracker="the PLACEHOLDER-TRACKER project"))
    stale, problems = sync_shared.plan(root)
    assert problems == []
    rendered = {dst.name: files for _, dst, files in stale}
    assert b"the PLACEHOLDER-TRACKER project" in rendered["jira-ticket"]["SKILL.md"]
    profile = yaml.safe_load((root / "shared/work-system/profiles/work-default.yaml").read_text())["params"]
    assert profile["tracker"].encode() not in rendered["jira-ticket"]["SKILL.md"]


def test_org_skills_are_copied_rendered():
    copied = ROOT / WD / "skills/org-process/SKILL.md"
    assert copied.read_bytes() == (ROOT / "orgs/example-co/skills/org-process/SKILL.md").read_bytes()
    lock = yaml.safe_load((ROOT / WD / "harness.lock").read_text())
    assert "skill:org-process" in {c["id"] for c in lock["components"]}


def test_org_skill_may_use_placeholders(tmp_path):
    root = copy_repo(tmp_path)
    skill = root / "orgs/example-co/skills/org-process/SKILL.md"
    skill.write_text(skill.read_text() + "\nTickets go to {{tracker}}.\n")
    stale, problems = sync_shared.plan(root)
    assert problems == []
    files = {dst.name: f for _, dst, f in stale}["org-process"]
    assert b"Tickets go to the WORKPROJ project on COMPANY-SITE.atlassian.net." in files["SKILL.md"]


def test_drifted_org_skill_copy_is_caught(tmp_path):
    root = copy_repo(tmp_path)
    copied = root / WD / "skills/org-process/SKILL.md"
    copied.write_text(copied.read_text() + "\nedited in the copy\n")
    stale, _ = sync_shared.plan(root)
    assert [dst for _, dst, _ in stale] == [root / WD / "skills/org-process"]


def test_org_needs_its_org_process_skill(tmp_path):
    root = copy_repo(tmp_path)
    shutil.rmtree(root / "orgs/example-co/skills/org-process")
    _, problems = sync_shared.plan(root)
    assert any("org-process/SKILL.md is missing" in p for p in problems)


def test_org_skill_cannot_shadow_a_shared_skill(tmp_path):
    root = copy_repo(tmp_path)
    shutil.copytree(root / "shared/work-system/skills/github-pr", root / "orgs/example-co/skills/github-pr")
    _, problems = sync_shared.plan(root)
    assert any("org skill github-pr has the name of a shared skill" in p for p in problems)


def test_suite_default_refuses_an_org(tmp_path):
    root = copy_repo(tmp_path)
    edit_yaml(root / "shared/work-system/targets.yaml",
              lambda t: t["harnesses"]["suite-default"].update(org="orgs/example-co"))
    _, problems = sync_shared.plan(root)
    assert any("suite-default: takes no org overlay" in p for p in problems)


def test_org_outside_orgs_is_refused(tmp_path):
    root = copy_repo(tmp_path)
    edit_yaml(root / "shared/work-system/targets.yaml",
              lambda t: t["harnesses"]["work-default"].update(org="shared/work-system"))
    _, problems = sync_shared.plan(root)
    assert any("must be a directory under orgs/" in p for p in problems)


def test_release_approvals_without_an_org_names_the_missing_org(tmp_path):
    root = copy_repo(tmp_path)
    edit_yaml(root / "shared/work-system/targets.yaml", lambda t: t["harnesses"]["work-default"].pop("org"))
    _, problems = sync_shared.plan(root)
    assert any("org_gates" in p and "needs an org" in p for p in problems)


def test_placeholder_example_renders_and_files_nothing():
    text = (ROOT / WD / "skills/release-approvals/SKILL.md").read_text()
    assert "**The org overlay is not applied.**" in text and "File no ticket" in text
    assert "| `sre` | `sre-approval` in `SREPROJ` | always |" in text
    assert "`Infosec: <KEY>`" in text and "Review please: {pr_url}" in text
    assert "drafted, never posted" in text and "read `org-process`" in text
    assert len(text.splitlines()) <= 90


def test_placeholder_is_a_warning_not_an_error():
    warnings: list[str] = []
    stale, problems = sync_shared.plan(ROOT, warnings)
    assert stale == [] and problems == []
    assert any("placeholder org" in w for w in warnings)


def test_real_org_drops_the_placeholder_status(tmp_path):
    root = copy_repo(tmp_path)
    edit_yaml(root / "orgs/example-co/org.yaml", lambda o: o.update(placeholder=False))
    warnings: list[str] = []
    stale, problems = sync_shared.plan(root, warnings)
    assert problems == [] and warnings == []
    files = {dst.name: f for _, dst, f in stale}["release-approvals"]
    assert b"**The org overlay is not applied.**" not in files["SKILL.md"]
    assert b"Run them as written." in files["SKILL.md"]


def test_suite_default_renders_as_before_and_has_no_org_skill():
    assert not (ROOT / "harnesses/suite-default/skills/org-process").exists()
    for p in (ROOT / "harnesses/suite-default").rglob("*.md"):
        assert "org-process" not in p.read_text() and "WORKPROJ" not in p.read_text(), p


def test_work_default_names_no_person_or_personal_site():
    for p in (ROOT / WD).rglob("*"):
        if p.is_file():
            text = p.read_text().lower()
            for word in ("sean", "seanmkoval", "second brain"):
                assert word not in text, f"{p.relative_to(ROOT)} mentions {word!r}"


def test_work_default_guides_point_at_org_process():
    guide = (ROOT / WD / "CLAUDE.md").read_text()
    assert (ROOT / WD / "AGENTS.md").read_text() == guide
    assert "`org-process`" in guide and guide.index("org-process") < guide.index("**Plan across the repos.**")
    assert "release-approvals" in guide and "gates the company's" in guide
