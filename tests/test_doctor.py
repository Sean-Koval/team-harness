"""scripts/doctor.py: one readable preflight for a laptop, with fakes for claude, gh, hangar, flightdeck and MCP."""

import http.server
import json
import os
import sys
import threading
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import doctor  # noqa: E402
import install_local as il  # noqa: E402

WORK = ROOT / "harnesses/work-default"
SUITE = ROOT / "harnesses/suite-default"
LOCK = yaml.safe_load((WORK / "harness.lock").read_text(encoding="utf-8"))
PINNED = LOCK["runtime"]["version"]
SECRET = "Bearer s3cret-value-never-printed"
pytestmark = pytest.mark.skipif(os.name == "nt", reason="the hooks probe through sh here; Windows has its own tests")


def channel_of(harness: Path) -> str:
    chans = yaml.safe_load((ROOT / "channels.yaml").read_text(encoding="utf-8"))
    lock = yaml.safe_load((harness / "harness.lock").read_text(encoding="utf-8"))
    return next(c for c, d in chans[lock["name"]].items() if d == il.harness_digest(lock))


def mcp_list_all(lock=LOCK) -> str:
    rows = ["Checking MCP server health…", ""]
    for m in lock["binding"]["mcp"]:
        if m["transport"] == "http":
            rows.append(f"{m['name']}: {m['endpoint']} (HTTP) - ✓ Connected")
        else:
            rows.append(f"{m['name']}: {m['command']} {' '.join(m.get('args') or [])} - ✓ Connected")
    return "\n".join(rows) + "\n"


class Fake:
    """Answers for the programs the doctor runs; python3 and git really run. Records every argv."""

    def __init__(self, over=None):
        self.calls = []
        self.answers = {
            ("claude", "--version"): (0, f"{PINNED} (Claude Code)\n"),
            ("claude", "mcp", "list"): (0, mcp_list_all()),
            ("claude", "-p"): (0, "ok\n"),
            ("gh", "auth", "status"): (0, "github.com\n  ✓ Logged in to github.com account dev (keyring)\n"
                                          "  - Token scopes: 'gist', 'read:org', 'repo', 'workflow'\n"),
            ("hangar", "trace", "import"): (0, "Usage: hangar trace import\n"),
            ("flightdeck", "ingest", "file"): (0, "Usage: flightdeck ingest file\n"),
        }
        self.answers.update(over or {})

    def __call__(self, argv, timeout=60):
        self.calls.append(argv)
        for n in range(len(argv), 0, -1):
            if tuple(argv[:n]) in self.answers:
                return self.answers[tuple(argv[:n])]
        if argv[0] in ("python3", "py", "git"):
            return doctor.run_cmd(argv, timeout)
        return None, f"{argv[0]} not found on PATH"


@pytest.fixture
def laptop(tmp_path):
    """A scratch HOME and a project with work-default installed in project scope, as a teammate would."""
    home, proj = tmp_path / "home", tmp_path / "proj"
    (home / ".claude" / "projects").mkdir(parents=True)
    proj.mkdir()
    assert il.main([str(WORK), "--scope", "project", "--target", str(proj), "--channel", channel_of(WORK),
                    "--allow-dirty", "--apply"]) == 0
    return home, proj


def doc(home, proj, *args, fake=None, env=None, harness=WORK):
    fake = fake or Fake()
    rc = doctor.main([str(harness), "--home", str(home), "--target", str(proj), "--json", *args], run=fake,
                     env=env if env is not None else {})
    return rc, fake


def checks(capsys) -> dict:
    out = json.loads(capsys.readouterr().out)
    assert out["schema"] == "team-harness.doctor/v1"
    return {c["id"]: c for c in out["checks"]}


def test_scratch_home_prints_every_check(laptop, capsys):
    home, proj = laptop
    rc = doctor.main([str(WORK), "--home", str(home), "--target", str(proj), "--skip", "checkout"], run=Fake(),
                     env={})
    out = capsys.readouterr().out
    ids = ["claude", "model", "python", "pyyaml", "install", "hooks", "channel", "checkout", "one-harness", "guide",
           "settings", "mcp:ai-dlc", "mcp:atlassian", "mcp:github", "gh", "org", "allowlist", "capture"]
    lines = [ln.split() for ln in out.splitlines()[1:] if ln.startswith("  ") and ln.split()[0] in ("ok", "fix", "skip")]
    assert [ln[1] for ln in lines] == ids
    # the public example org is a placeholder, so a work install always has that one to fix
    assert rc == 1 and out.rstrip().endswith("1 to fix: org")
    assert "fix: add your company's org" in out


def test_json_names_the_install_and_the_fixes(laptop, capsys):
    home, proj = laptop
    rc, _ = doc(home, proj)
    c = checks(capsys)
    assert rc == 1 and c["org"]["status"] == "fix" and "COMPANY-SITE" in c["org"]["summary"]
    for cid in ("claude", "python", "pyyaml", "install", "hooks", "channel", "one-harness", "guide", "settings",
                "mcp:github", "mcp:atlassian", "mcp:ai-dlc", "gh", "capture"):
        assert c[cid]["status"] == "ok", (cid, c[cid])
    assert c["model"]["status"] == "skip" and c["allowlist"]["status"] == "skip"


def test_suite_default_takes_no_org(tmp_path, capsys):
    home, proj = tmp_path / "h", tmp_path / "p"
    (home / ".claude" / "projects").mkdir(parents=True)
    proj.mkdir()
    assert il.main([str(SUITE), "--scope", "project", "--target", str(proj), "--channel", channel_of(SUITE),
                    "--allow-dirty", "--apply"]) == 0
    capsys.readouterr()
    lock = yaml.safe_load((SUITE / "harness.lock").read_text(encoding="utf-8"))
    fake = Fake({("claude", "--version"): (0, f"{lock['runtime']['version']} (Claude Code)"),
                   ("claude", "mcp", "list"): (0, mcp_list_all(lock))})
    doc(home, proj, fake=fake, harness=SUITE)
    assert checks(capsys)["org"]["status"] == "skip"


def test_not_installed_says_how(tmp_path, capsys):
    rc, _ = doc(tmp_path / "h", tmp_path / "p")
    c = checks(capsys)
    assert rc == 1 and c["install"]["status"] == "fix"
    assert "install_local.py harnesses/work-default --scope project" in c["install"]["fix"]
    assert c["hooks"]["status"] == "skip" and c["org"]["status"] == "skip"


def test_older_claude_is_a_fix_newer_only_with_exact_runtime(laptop, capsys):
    home, proj = laptop
    doc(home, proj, fake=Fake({("claude", "--version"): (0, "1.0.0 (Claude Code)")}))
    c = checks(capsys)["claude"]
    assert c["status"] == "fix" and c["fix"] == f"claude install {PINNED}"
    newer = Fake({("claude", "--version"): (0, "99.0.0 (Claude Code)")})
    doc(home, proj, fake=newer)
    assert checks(capsys)["claude"]["status"] == "ok"
    doc(home, proj, "--exact-runtime", fake=Fake({("claude", "--version"): (0, "99.0.0 (Claude Code)")}))
    assert checks(capsys)["claude"]["status"] == "fix"


def test_claude_missing(laptop, capsys):
    home, proj = laptop
    fake = Fake()
    del fake.answers[("claude", "--version")]
    del fake.answers[("claude", "mcp", "list")]
    doc(home, proj, fake=fake)
    c = checks(capsys)
    assert c["claude"]["status"] == "fix" and "install Claude Code" in c["claude"]["fix"]
    assert c["mcp:github"]["status"] == "skip"


def test_live_asks_the_lock_model_once(laptop, capsys):
    home, proj = laptop
    _, fake = doc(home, proj, "--live")
    assert checks(capsys)["model"]["status"] == "ok"
    asked = [a for a in fake.calls if a[:2] == ["claude", "-p"]]
    assert len(asked) == 1 and asked[0][asked[0].index("--model") + 1] == LOCK["model"]["id"]
    doc(home, proj, "--live", fake=Fake({("claude", "-p"): (1, "model not available")}))
    assert checks(capsys)["model"]["status"] == "fix"


def test_mcp_missing_wrong_endpoint_and_auth(laptop, capsys):
    home, proj = laptop
    listing = mcp_list_all().replace("github: https://api.githubcopilot.com/mcp/", "github: https://example.test/mcp")
    listing = listing.replace("atlassian: https://mcp.atlassian.com/v1/mcp (HTTP) - ✓ Connected",
                              "atlassian: https://mcp.atlassian.com/v1/mcp (HTTP) - ! Needs authentication")
    listing = "\n".join(ln for ln in listing.splitlines() if not ln.startswith("ai-dlc:"))
    doc(home, proj, fake=Fake({("claude", "mcp", "list"): (0, listing)}))
    c = checks(capsys)
    assert c["mcp:ai-dlc"]["status"] == "fix" and c["mcp:ai-dlc"]["fix"].startswith("claude mcp add --scope project")
    assert c["mcp:github"]["status"] == "fix" and "claude mcp remove github" in c["mcp:github"]["fix"]
    assert c["mcp:atlassian"]["status"] == "fix" and "/mcp" in c["mcp:atlassian"]["fix"]


def test_mcp_failed_names_the_unset_variable_never_its_value(laptop, capsys):
    home, proj = laptop
    listing = mcp_list_all().replace("api.githubcopilot.com/mcp/ (HTTP) - ✓ Connected",
                                     "api.githubcopilot.com/mcp/ (HTTP) - × Failed to connect — HTTP 401")
    doc(home, proj, fake=Fake({("claude", "mcp", "list"): (0, listing)}))
    c = checks(capsys)["mcp:github"]
    assert c["status"] == "fix" and "GITHUB_MCP_AUTHORIZATION" in c["fix"]
    doc(home, proj, env={"GITHUB_MCP_AUTHORIZATION": SECRET, "ATLASSIAN_MCP_AUTHORIZATION": SECRET})
    out = capsys.readouterr().out
    assert SECRET not in out and "GITHUB_MCP_AUTHORIZATION set" in out


class FakeMCP(http.server.BaseHTTPRequestHandler):
    sse = False
    status = 200
    seen: list = []

    def do_POST(self):  # noqa: N802
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        FakeMCP.seen.append((self.headers.get("Authorization"), self.headers.get("Mcp-Session-Id"), body))
        if FakeMCP.status != 200:
            self.send_response(FakeMCP.status)
            self.end_headers()
            return
        if "id" not in body:
            self.send_response(202)
            self.end_headers()
            return
        result = {"tools": [{"name": "a"}, {"name": "b"}]} if body["method"] == "tools/list" else {"capabilities": {}}
        data = json.dumps({"jsonrpc": "2.0", "id": body["id"], "result": result})
        self.send_response(200)
        self.send_header("Mcp-Session-Id", "sess-1")
        if FakeMCP.sse:
            self.send_header("Content-Type", "text/event-stream")
            data = f"event: message\ndata: {data}\n\n"
        else:
            self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(data.encode())

    def log_message(self, *a):
        pass


@pytest.fixture
def mcp_server():
    FakeMCP.seen, FakeMCP.sse, FakeMCP.status = [], False, 200
    srv = http.server.HTTPServer(("127.0.0.1", 0), FakeMCP)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}/mcp"
    srv.shutdown()


@pytest.mark.parametrize("sse", [False, True])
def test_tools_list_handshake(mcp_server, sse, monkeypatch):
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    FakeMCP.sse = sse
    n, err = doctor.tools_list(mcp_server, "Authorization", SECRET)
    assert (n, err) == (2, None)
    assert [b.get("method") for _, _, b in FakeMCP.seen] == ["initialize", "notifications/initialized", "tools/list"]
    assert FakeMCP.seen[-1][:2] == (SECRET, "sess-1")


def test_tools_list_refused(mcp_server, monkeypatch):
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    FakeMCP.status = 401
    n, err = doctor.tools_list(mcp_server, "Authorization", SECRET)
    assert n == 0 and "401" in err and SECRET not in err


def test_live_tools_list_per_server(laptop, capsys, mcp_server, monkeypatch):
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    home, proj = laptop
    lock = dict(LOCK, binding=dict(LOCK["binding"], mcp=[dict(m, endpoint=mcp_server) if m["name"] == "github" else m
                                                         for m in LOCK["binding"]["mcp"]]))
    monkeypatch.setattr(doctor.il, "_lock_at", lambda root: lock)
    fake = Fake({("claude", "mcp", "list"): (0, mcp_list_all(lock))})
    doc(home, proj, "--live", "--skip", "channel", fake=fake, env={"GITHUB_MCP_AUTHORIZATION": SECRET})
    out = capsys.readouterr().out
    assert SECRET not in out
    c = {x["id"]: x for x in json.loads(out)["checks"]}
    assert c["mcp:github"]["status"] == "ok" and "2 tools" in c["mcp:github"]["summary"]
    assert "ATLASSIAN_MCP_AUTHORIZATION unset" in c["mcp:atlassian"]["summary"]


def test_gh_signed_out_and_without_repo_scope(laptop, capsys):
    home, proj = laptop
    doc(home, proj, "--github-host", "github.corp.example",
        fake=Fake({("gh", "auth", "status"): (1, "You are not logged into any GitHub hosts.")}))
    c = checks(capsys)["gh"]
    assert c["status"] == "fix" and c["fix"] == "gh auth login --hostname github.corp.example --scopes repo"
    doc(home, proj, fake=Fake({("gh", "auth", "status"): (0, "  - Token scopes: 'gist', 'read:org'\n")}))
    c = checks(capsys)["gh"]
    assert c["status"] == "fix" and "gh auth refresh" in c["fix"]


def test_second_harness_in_the_other_scope(laptop, capsys):
    home, proj = laptop
    assert il.main([str(SUITE), "--scope", "user", "--home", str(home), "--channel", channel_of(SUITE),
                    "--allow-dirty", "--apply"]) == 0
    capsys.readouterr()
    doc(home, proj)
    c = checks(capsys)["one-harness"]
    assert c["status"] == "fix" and "suite-default" in c["summary"] and "--uninstall" in c["fix"]


def test_symlinked_settings_and_missing_import(laptop, capsys):
    home, proj = laptop
    s = proj / ".claude" / "settings.json"
    real = proj / "real-settings.json"
    real.write_bytes(s.read_bytes())
    s.unlink()
    s.symlink_to(real)
    md = proj / ".claude" / "CLAUDE.md"
    md.write_text("".join(ln for ln in md.read_text().splitlines(True) if "@team-harness" not in ln))
    doc(home, proj)
    c = checks(capsys)
    assert c["settings"]["status"] == "fix" and c["guide"]["status"] == "fix"


def test_hook_that_cannot_start(laptop, capsys):
    home, proj = laptop
    (proj / ".claude" / "hooks" / "guard_work.py").write_text("import sys\nsys.exit(3)\n")
    doc(home, proj)
    c = checks(capsys)
    assert c["hooks"]["status"] == "fix" and "OFF" in c["hooks"]["summary"]
    assert c["install"]["status"] == "fix" and "edited" in c["install"]["summary"]


def test_allowlist_from_ai_dlc_toml_and_flags(laptop, capsys):
    home, proj = laptop
    (proj / "ai-dlc.toml").write_text('[checks.commands]\ntest = "uv run pytest -q"\nlint = "ruff check . && '
                                      'ruff format --check ."\n')
    doc(home, proj, "--test-cmd", "make check")
    c = checks(capsys)["allowlist"]
    assert c["status"] == "fix"
    for rule in ('"Bash(uv run pytest -q:*)"', '"Bash(ruff check .:*)"', '"Bash(make check:*)"'):
        assert rule in c["fix"]
    s = proj / ".claude" / "settings.local.json"
    data = json.loads(s.read_text()) if s.exists() else {}
    data.setdefault("permissions", {})["allow"] = ["Bash(uv run:*)", "Bash(ruff *)", "Bash(make check)"]
    s.write_text(json.dumps(data))
    doc(home, proj, "--test-cmd", "make check")
    assert checks(capsys)["allowlist"]["status"] == "ok"
    doc(home, proj, "--test-cmd", "kubectl apply -f x.yaml")
    c = checks(capsys)["allowlist"]
    assert c["status"] == "fix" and "deny rule" in c["summary"]


@pytest.mark.parametrize("rule,cmd,ok", [
    ("Bash", "anything at all", True),
    ("Bash(*)", "anything", True),
    ("Bash(npm test:*)", "npm test", True),
    ("Bash(npm test:*)", "npm test -- --watch", True),
    ("Bash(npm test:*)", "npm testing", False),
    ("Bash(npm run *)", "npm run lint", True),
    ("Bash(pytest -q)", "pytest -q", True),
    ("Bash(pytest -q)", "pytest -q tests", False),
    ("Read(**)", "pytest", False),
    ("PowerShell(pytest:*)", "pytest", False),
])
def test_rule_matches(rule, cmd, ok):
    assert doctor.rule_matches(rule, cmd) is ok


def test_capture_not_ready(laptop, capsys):
    home, proj = laptop
    (home / ".claude" / "projects").rmdir()
    fake = Fake()
    del fake.answers[("hangar", "trace", "import")]
    doc(home, proj, fake=fake)
    c = checks(capsys)["capture"]
    assert c["status"] == "fix" and "hangar trace import" in c["summary"] and "transcripts" in c["summary"]
    doc(home, proj, "--skip", "capture", fake=fake)
    assert checks(capsys)["capture"]["status"] == "skip"


def test_doctor_writes_nothing(laptop, capsys):
    home, proj = laptop
    before = {p: p.read_bytes() for d in (home, proj) for p in d.rglob("*") if p.is_file()}
    doc(home, proj, "--live")
    after = {p: p.read_bytes() for d in (home, proj) for p in d.rglob("*") if p.is_file()}
    assert before == after


def test_bad_harness_is_exit_2(tmp_path, capsys):
    assert doctor.main([str(tmp_path), "--home", str(tmp_path)], run=Fake(), env={}) == 2
