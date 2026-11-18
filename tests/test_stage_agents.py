"""KAN-513: stage subagents route cheap work to the cheap tier. Each harness carries triage, review-lint and designer
with a concrete model from its profile; the shared sources hold only the tier placeholders; the lock pins them."""

import json
import re
import shutil
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SHARED = ROOT / "shared/work-system"
sys.path.insert(0, str(ROOT / "scripts"))
TARGETS = yaml.safe_load((SHARED / "targets.yaml").read_text(encoding="utf-8"))
HARNESSES = sorted(TARGETS["harnesses"])
TIERS = {"triage": "model_cheap", "review-lint": "model_cheap", "designer": "model_strong"}
# a literal model ID, the way a provider names one: claude-opus-5-5, claude-3-haiku, gpt-5, gemini-2.5-pro ...
MODEL_ID = re.compile(r"\b(?:claude-[a-z0-9.-]*\d|gpt-\d[\w.-]*|o\d-[\w.-]+|gemini-[\w.-]+)\b", re.IGNORECASE)
# Routing must come from the profile, so these shared sources may not name a model (data files such as a usage
# hook's price table are not routing, and are not scanned).
ROUTING_SOURCES = ("agents", "skills", "guide")


def frontmatter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    m = re.match(r"---\n(.*?)\n---\n", text, re.S)
    assert m, f"{path} has no front matter"
    return yaml.safe_load(m.group(1))


def params(h: str) -> dict:
    return yaml.safe_load((SHARED / TARGETS["harnesses"][h]["profile"]).read_text(encoding="utf-8"))["params"]


def test_targets_list_the_three_stages():
    assert sorted(Path(a).stem for a in TARGETS["agents"]) == sorted(TIERS)


@pytest.mark.parametrize("stage", sorted(TIERS))
def test_the_shared_stage_names_its_tier_not_a_model(stage):
    fm = frontmatter(SHARED / "agents" / f"{stage}.md")
    assert fm["name"] == stage and fm["description"]
    text = (SHARED / "agents" / f"{stage}.md").read_text(encoding="utf-8")
    assert fm["model"] == "{{" + TIERS[stage] + "}}", text.splitlines()[:5]


@pytest.mark.parametrize("h", HARNESSES)
@pytest.mark.parametrize("stage", sorted(TIERS))
def test_each_harness_has_the_stage_with_its_profiles_model(h, stage):
    rendered = ROOT / "harnesses" / h / "native/claude-code/agents" / f"{stage}.md"
    fm = frontmatter(rendered)
    want = params(h)[TIERS[stage]]
    assert fm["model"] == want and MODEL_ID.fullmatch(want), (h, stage, fm["model"])
    assert "{{" not in rendered.read_text(encoding="utf-8")


@pytest.mark.parametrize("h", HARNESSES)
def test_every_profile_fills_the_three_tiers(h):
    p = params(h)
    for tier in ("model_cheap", "model_build", "model_strong"):
        assert isinstance(p.get(tier), str) and MODEL_ID.fullmatch(p[tier]), (h, tier)


def test_no_shared_routing_source_holds_a_literal_model_id():
    hits = [f"{p.relative_to(ROOT)}:{n}: {m.group(0)}"
            for d in ROUTING_SOURCES for p in sorted((SHARED / d).rglob("*")) if p.is_file()
            for n, line in enumerate(p.read_text(encoding="utf-8", errors="ignore").splitlines(), 1)
            for m in MODEL_ID.finditer(line)]
    assert hits == [], "name a profile tier ({{model_cheap}}, {{model_build}}, {{model_strong}}) instead: " + \
        "; ".join(hits)


def test_the_scan_catches_a_literal_model_id():
    assert MODEL_ID.search("model: claude-haiku-5-5") and MODEL_ID.search("use gpt-5 here")
    assert not MODEL_ID.search("model: {{model_cheap}}") and not MODEL_ID.search("claude-code hooks")


def test_the_skills_say_which_stage_to_delegate_to():
    start = (SHARED / "skills/work-start/SKILL.md").read_text(encoding="utf-8")
    pr = (SHARED / "skills/github-pr/SKILL.md").read_text(encoding="utf-8")
    assert "`triage` subagent" in start and "`designer` subagent" in start and "`review-lint`" in pr
    guide = (SHARED / "guide/knowledge.md").read_text(encoding="utf-8")
    assert "[capture] model" in guide and "{{model_cheap}}" in guide


@pytest.mark.parametrize("stage", sorted(TIERS))
def test_relock_pins_each_stage_file(stage, tmp_path):
    pytest.importorskip("hangar")
    from hangar import harness_lock as hl

    import relock

    h = tmp_path / "harnesses" / "suite-default"
    shutil.copytree(ROOT / "harnesses" / "suite-default", h)
    before = hl.load(h)
    assert f"native:claude-code/agents/{stage}.md" in {c["id"] for c in before["components"]}
    with (h / "native/claude-code/agents" / f"{stage}.md").open("a", encoding="utf-8") as f:
        f.write("\nOne more line.\n")
    after, _ = relock.relock(h)
    assert hl.harness_digest(after) != hl.harness_digest(before)


@pytest.mark.parametrize("stage", sorted(TIERS))
def test_no_stage_edits_files(stage):
    # Claude Code's own edit tools are denied; the guard hook still covers the tracker's write tools
    denied = {t.strip() for t in str(frontmatter(SHARED / "agents" / f"{stage}.md")["disallowedTools"]).split(",")}
    assert {"Write", "Edit", "NotebookEdit"} <= denied


# KAN-544: each stage names the tools it may use, not only the edit tools it may not. A stage reads: the files, the
# skills, the ticket (triage, designer), the knowledge CLI and the diff (designer's and review-lint's shell).
READ_TOOLS = {"Read", "Grep", "Glob", "Skill"}
SHELL = {"designer", "review-lint"}
READS_TRACKER = {"triage", "designer"}
NEVER = {"Write", "Edit", "NotebookEdit", "MultiEdit", "Agent", "Task", "WebFetch", "WebSearch"}


def tool_list(fm: dict, key: str = "tools") -> set[str]:
    return {t.strip() for t in str(fm.get(key) or "").split(",") if t.strip()}


def read_servers(h: str) -> set[str]:
    bindings = json.loads(params(h)["mcp_bindings"])
    return {s for role in ("tracker", "wiki", "ai-dlc") for s in bindings.get(role) or []}


@pytest.mark.parametrize("stage", sorted(TIERS))
def test_the_shared_stage_has_a_tools_allowlist(stage):
    tools = tool_list(frontmatter(SHARED / "agents" / f"{stage}.md"))
    want = READ_TOOLS | ({"Bash"} if stage in SHELL else set()) | \
        ({"{{stage_mcp_tools}}"} if stage in READS_TRACKER else set())
    assert tools == want, (stage, sorted(tools))


@pytest.mark.parametrize("h", HARNESSES)
@pytest.mark.parametrize("stage", sorted(TIERS))
def test_each_harness_stage_reaches_only_its_read_servers(h, stage):
    tools = tool_list(frontmatter(ROOT / "harnesses" / h / "native/claude-code/agents" / f"{stage}.md"))
    mcp = {t for t in tools if t.startswith("mcp__")}
    want_mcp = {f"mcp__{s}__*" for s in read_servers(h)} if stage in READS_TRACKER else set()
    assert mcp == want_mcp, (h, stage, sorted(mcp))
    assert tools - mcp == READ_TOOLS | ({"Bash"} if stage in SHELL else set()), (h, stage, sorted(tools))
    assert not tools & NEVER, (h, stage, sorted(tools & NEVER))
    assert stage != "triage" or "Bash" not in tools


def test_the_stage_servers_follow_the_bindings():
    import sync_shared

    bindings = {"tracker": ["corp-jira"], "wiki": ["corp-jira", "wiki.corp"], "ai-dlc": ["ai-dlc"],
                "github": ["github"]}
    assert sync_shared.stage_mcp_tools({"mcp_bindings": json.dumps(bindings)}) == \
        "mcp__ai-dlc__*, mcp__corp-jira__*, mcp__wiki_corp__*"
    for bad in ('{"github": ["github"]}', "not json", "[]", ""):
        assert sync_shared.stage_mcp_tools({"mcp_bindings": bad}) == ""


def test_a_harness_binding_no_read_server_is_a_problem(tmp_path):
    import sync_shared

    for d in ("shared", "harnesses", "orgs"):
        shutil.copytree(ROOT / d, tmp_path / d, ignore=shutil.ignore_patterns("__pycache__"))
    profile = tmp_path / "shared/work-system/profiles/suite-default.yaml"
    text = profile.read_text(encoding="utf-8")
    assert "mcp_bindings: '" in text
    profile.write_text(re.sub(r"mcp_bindings: '.*'", "mcp_bindings: '{\"github\": [\"github\"]}'", text),
                       encoding="utf-8")
    _, found = sync_shared.plan(tmp_path)
    assert any("suite-default: mcp_bindings binds no tracker" in p for p in found), found


def test_work_default_tiers_stay_on_its_locked_model():
    # work-default routes nothing to another model until the company approves one: every tier is the lock's model,
    # so a lock that moves to a new model must move the tiers with it (or name the approved cheaper ones here)
    lock = yaml.safe_load((ROOT / "harnesses/work-default/harness.lock").read_text(encoding="utf-8"))
    p = params("work-default")
    assert {p["model_cheap"], p["model_build"], p["model_strong"]} == {lock["model"]["id"]}


def test_a_dropped_stage_file_is_removed_not_pinned(tmp_path):
    import sync_shared

    for d in ("shared", "harnesses", "orgs"):
        shutil.copytree(ROOT / d, tmp_path / d, ignore=shutil.ignore_patterns("__pycache__"))
    stray = tmp_path / "harnesses/suite-default/native/claude-code/agents/old-stage.md"
    stray.parent.mkdir(parents=True, exist_ok=True)
    stray.write_text("---\nname: old-stage\n---\n", encoding="utf-8")
    stale, _ = sync_shared.plan(tmp_path)
    assert (stray, stray, None) in stale
    sync_shared.write([s for s in stale if s[0] == stray], root=tmp_path)
    assert not stray.exists()
