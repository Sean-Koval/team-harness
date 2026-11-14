"""Skill intake (KAN-511): scripts/add_skill.py checks a team work skill and copies it into the shared layer.

The sample skill in tests/fixtures/add-skill/ passes; each bad variant is the sample with one line or field changed,
built here, so no secret-shaped string is committed. `test_every_shared_skill_passes_intake` is the CI check.
"""

import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import add_skill  # noqa: E402
import sync_shared  # noqa: E402

SAMPLE = ROOT / "tests" / "fixtures" / "add-skill" / "team-deploy-notes"


@pytest.fixture
def repo(tmp_path):
    """A copy of the parts of the repository intake reads and writes."""
    root = tmp_path / "repo"
    shutil.copytree(ROOT / "shared", root / "shared")
    shutil.copytree(ROOT / "orgs", root / "orgs")
    (root / "changes").mkdir()
    return root


@pytest.fixture
def skill(tmp_path):
    d = tmp_path / "in" / SAMPLE.name
    shutil.copytree(SAMPLE, d)
    return d


def _append(skill: Path, line: str) -> None:
    md = skill / "SKILL.md"
    md.write_text(md.read_text(encoding="utf-8") + line + "\n", encoding="utf-8")


def test_every_shared_skill_passes_intake():
    assert add_skill.check() == []


def test_intake_and_ci_share_one_vendor_rule():
    import skill_rules
    import test_skill_tool_names
    import test_skill_vendor_names
    assert add_skill.skill_rules is skill_rules
    assert test_skill_tool_names.ATLASSIAN_TOOL is skill_rules.ATLASSIAN_TOOL
    assert test_skill_vendor_names.VENDOR is skill_rules.VENDOR


def test_sample_is_added_registered_and_logged(repo, skill):
    (skill / "SKILL.md").write_bytes(b"\xef\xbb\xbf" + (skill / "SKILL.md").read_bytes().replace(b"\n", b"\r\n"))
    assert add_skill.add(skill, ["work-default"], "KAN-1", [], root=repo) == []
    dst = repo / "shared/work-system/skills/team-deploy-notes"
    md = (dst / "SKILL.md").read_bytes()
    assert b"\r" not in md and not md.startswith(b"\xef\xbb\xbf")
    assert (dst / "reference" / "format.md").is_file()
    assert sync_shared._skill_harnesses(dst / "SKILL.md") == ["work-default"]
    assert sync_shared._skill_name(dst / "SKILL.md") == "team-deploy-notes"
    frag = (repo / "changes" / "KAN-1.added.md").read_text(encoding="utf-8")
    assert frag.startswith("- work-default: + `team-deploy-notes` skill.")
    # the shared layer now ships it to work-default only
    targets = sync_shared.yaml.safe_load((repo / "shared/work-system/targets.yaml").read_text(encoding="utf-8"))
    common = sync_shared.shared_skills(repo / "shared/work-system", targets, targets["harnesses"], [])
    assert "team-deploy-notes" in common["work-default"] and "team-deploy-notes" not in common["suite-default"]
    # and the added skill still passes the CI check
    assert add_skill.check(root=repo) == []


def test_cli_adds_the_sample(repo, skill, monkeypatch, capsys):
    monkeypatch.setattr(add_skill, "ROOT", repo)
    assert add_skill.main([str(skill), "--harness", "work-default", "--key", "KAN-2"]) == 0
    assert "stable moves only by scripts/promote.py" in capsys.readouterr().out
    assert (repo / "changes/KAN-2.added.md").is_file()


BAD_LINES = {
    "vendor tool": ("Create it with `createJiraIssue`.", "or tool createJiraIssue"),
    "server-qualified tool": ("Call mcp__atlassian__getJiraIssue first.", "or tool mcp__atlassian__getJiraIssue"),
    "query language": ("Search with JQL for open tickets.", "vendor server, query language or tool JQL"),
    "connector": ("Use the Atlassian connector.", "vendor server, query language or tool Atlassian"),
    "any mcp tool": ("Open it with mcp__github__create_pull_request.", "mcp__github__create_pull_request"),
    "github token": ("Use ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4 to push.", "GitHub token"),
    "credential value": ("password = " + "hunter2hunter2hunter2", "credential value"),
    "private key": ("-----BEGIN RSA " + "PRIVATE KEY-----", "private key"),
    "email": ("Ask jane.doe@" + "acme-corp.com.", "e-mail address"),
    "site": ("Pages live on wiki.acme-corp.com.", "the host wiki.acme-corp.com"),
    "url": ("Open https://grafana.acme-corp.internal/d/x first.", "the host grafana.acme-corp.internal"),
    "quoted credential": ('API_KEY = "' + "a1b2c3d4e5f6g7h8i9" + '"', "credential value"),
    "profile person": ("Ask Sean before you post.", "profile's person or site"),
    "profile site": ("See the space on seanmkoval.atlassian.net.", "the host"),
}


@pytest.mark.parametrize("case", sorted(BAD_LINES))
def test_a_bad_line_is_refused_and_nothing_is_copied(repo, skill, case):
    line, expected = BAD_LINES[case]
    _append(skill, line)
    problems = add_skill.add(skill, ["work-default"], "KAN-3", [], root=repo)
    assert any(expected in p for p in problems), problems
    assert not (repo / "shared/work-system/skills/team-deploy-notes").exists()
    assert not (repo / "changes/KAN-3.added.md").exists()


def test_deny_list_word_is_refused(repo, skill, tmp_path, monkeypatch):
    _append(skill, "Built for the Initech billing team.")
    deny = tmp_path / "deny.txt"
    deny.write_text("# company and customer names\nInitech\n", encoding="utf-8")
    monkeypatch.setenv("TEAM_HARNESS_DENY", str(deny))
    problems = add_skill.add(skill, ["work-default"], "KAN-4", add_skill.deny_words(), root=repo)
    assert any("'Initech' is on your deny list" in p for p in problems), problems


def test_unknown_placeholder_is_refused(repo, skill):
    _append(skill, "Post it in {{team_room}}.")
    problems = add_skill.add(skill, ["work-default"], "KAN-5", [], root=repo)
    assert any("{{team_room}} is not a parameter work-default's profile fills" in p for p in problems), problems


def test_frontmatter_is_required(repo, skill):
    md = skill / "SKILL.md"
    text = md.read_text(encoding="utf-8")
    md.write_text(text.replace("name: team-deploy-notes", "name: deploy-notes")
                  .split("description:")[0] + "---\n", encoding="utf-8")
    problems = add_skill.add(skill, ["work-default"], "KAN-6", [], root=repo)
    assert any("frontmatter name must be 'team-deploy-notes'" in p for p in problems), problems
    assert any("needs a description" in p for p in problems), problems


def test_a_taken_name_is_refused(repo, tmp_path):
    d = tmp_path / "in" / "jira-ticket"
    shutil.copytree(SAMPLE, d)
    md = d / "SKILL.md"
    md.write_text(md.read_text(encoding="utf-8").replace("team-deploy-notes", "jira-ticket"), encoding="utf-8")
    assert any("is taken" in p for p in add_skill.add(d, ["work-default"], "KAN-7", [], root=repo))


def test_unknown_harness_and_bad_key_are_refused(repo, skill):
    assert any("does not list it" in p for p in add_skill.add(skill, ["nope"], "KAN-8", [], root=repo))
    assert any("ticket key" in p for p in add_skill.add(skill, ["work-default"], "kan 8", [], root=repo))


@pytest.mark.parametrize("line,host", [
    ("Deploy from build01.corp.internal first.", "build01.corp.internal"),
    ("The share is nas.home.arpa.", "nas.home.arpa"),
    ("Logs on log-1.lan and wiki.team.intranet.", "log-1.lan"),
    ("Ask db.prod.corp for a dump.", "db.prod.corp"),
    ("ssh build-02.local", "build-02.local"),
    ("Open initech.corp:8443 in a browser.", "initech.corp:8443"),
    ("The API is on initech.local:8080.", "initech.local:8080"),
    ("Its name is initech.internal.", "initech.internal"),
    ("Tickets live on jira.corp.", "jira.corp"),
    ("Run `curl https://initech.corp:8443/health`.", "initech.corp"),
    ("Run `curl jira.corp:8443/health`.", "jira.corp:8443"),
])
def test_a_private_network_host_is_refused_bare(line, host):
    problems = add_skill.content_problems({"SKILL.md": line + "\n"}, set(), [])
    assert any(f"the host {host}" in p for p in problems), problems


def test_a_vendor_name_is_reported_once():
    problems = add_skill.content_problems({"SKILL.md": "Call mcp__atlassian__getJiraIssue first.\n"}, set(), [])
    assert len(problems) == 1, problems


MUST_PASS = [
    "Read `config.internal` and `app.local`; `self.corp(x)` is a call.",
    "See https://docs.example.com/x, {{kb_site}} and git@github.com:org/repo.git.",
    "Log it with `logger.info(\"done\")`, then `df.info()` and `request.app.state.db`.",
    "Pin it in requirements.in; local overrides go in `settings.local`.",
    "`settings.local.x`, `config.internal(` and `env.corp.get(\"X\")` are code.",
    "`pd.io.json.dumps(x)` and `client.ai(x)` are calls, not hosts.",
    "Read https://docs.python.org/3/library/re.html and https://code.claude.com/docs/en/skills.",
    "Install from https://pypi.org/project/pyyaml/ or https://api.github.com/repos/o/r.",
    "Fetch https://raw.githubusercontent.com/o/r/main/x.md.",
    "token = os.environ.get(\"GITHUB_TOKEN\")",
    "password = getpass.getpass()",
    "Bearer token: Authorization header from the credential named in bindings.",
    "token: ${GITHUB_TOKEN} and api_key: {{tracker_server}}",
    "Jira and Confluence are the tracker and wiki; the jira-ticket skill reads a Jira project.",
]


@pytest.mark.parametrize("line", MUST_PASS)
def test_ordinary_skill_text_passes(line):
    assert add_skill.content_problems({"SKILL.md": line + "\n"}, {"Sean"}, []) == []


def test_allow_host_admits_a_public_docs_site():
    files = {"SKILL.md": "See https://docs.internal-tool.dev/guide.\n"}
    assert add_skill.content_problems(files, set(), [])
    assert add_skill.content_problems(files, set(), [], frozenset({"docs.internal-tool.dev"})) == []


def test_a_binary_or_nul_file_is_refused(repo, skill):
    (skill / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n\xff\x00")
    (skill / "zeros.md").write_bytes(b"\x00" * 16)
    problems = add_skill.add(skill, ["work-default"], "KAN-9", [], root=repo)
    assert any("logo.png: not UTF-8" in p for p in problems), problems
    assert any("zeros.md: holds NUL bytes" in p for p in problems), problems


DENY = "# company and customer names\nInitech\n"


@pytest.mark.parametrize("encoding", ["utf-8", "utf-8-sig", "utf-16", "utf-16-be-bom"])
def test_deny_file_reads_every_windows_encoding(tmp_path, encoding):
    f = tmp_path / "deny.txt"
    if encoding == "utf-16-be-bom":
        f.write_bytes(b"\xfe\xff" + DENY.replace("\n", "\r\n").encode("utf-16-be"))
    else:
        f.write_bytes(DENY.replace("\n", "\r\n").encode(encoding))  # utf-16 writes a BOM, as PowerShell 5.1 does
    assert add_skill.read_deny_file(str(f)) == ["Initech"]


def test_deny_file_path_takes_tilde_and_quotes(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    (tmp_path / ".team-harness-deny").write_text(DENY, encoding="utf-8")
    assert add_skill.read_deny_file('"~/.team-harness-deny"') == ["Initech"]
    monkeypatch.setenv("TEAM_HARNESS_DENY", "'~/.team-harness-deny'")
    assert add_skill.deny_words(["Globex"]) == ["Globex", "Initech"]


def test_unreadable_deny_file_fails_loudly(tmp_path, monkeypatch, capsys):
    bad = tmp_path / "deny.txt"
    bad.write_bytes(b"Init\xe9ch\xff\n")
    with pytest.raises(add_skill.DenyFileError, match="neither UTF-8 nor UTF-16"):
        add_skill.read_deny_file(str(bad))
    bom_less = tmp_path / "deny16.txt"
    bom_less.write_bytes("Initech\n".encode("utf-16-le"))
    with pytest.raises(add_skill.DenyFileError, match="NUL bytes"):
        add_skill.read_deny_file(str(bom_less))
    with pytest.raises(add_skill.DenyFileError, match="cannot read"):
        add_skill.read_deny_file(str(tmp_path / "missing.txt"))
    monkeypatch.setenv("TEAM_HARNESS_DENY", str(bad))
    assert add_skill.main(["--check"]) == 2
    assert "deny file" in capsys.readouterr().out
