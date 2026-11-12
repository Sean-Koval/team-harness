"""The shared work-system PreToolUse guard: work carries a ticket key, and agents don't move tickets."""

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "shared/work-system/hooks/guard_work_system.py"


def run(event) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(HOOK)], input=json.dumps(event), capture_output=True,
                          encoding="utf-8")


def bash(command: str, cwd: Path | None = None) -> int:
    event = {"tool_name": "Bash", "tool_input": {"command": command}}
    if cwd:
        event["cwd"] = str(cwd)
    return run(event).returncode


@pytest.fixture
def repo(tmp_path):
    def make(branch: str) -> Path:
        d = tmp_path / branch.replace("/", "_")
        d.mkdir()
        subprocess.run(["git", "init", "-q", "-b", branch, str(d)], check=True)
        return d
    return make


@pytest.mark.parametrize("branch", ["KAN-315-work-system-layer", "hangar/KAN-35-apply", "SVC-412-retry-queue",
                                    "nokey/fix-typo", "dependabot/pip/requests-2.33", "claude/wizardly-pascal-qolknc"])
def test_commit_allowed_on_keyed_or_exempt_branch(repo, branch):
    assert bash("git commit -m 'KAN-315: add the hook'", repo(branch)) == 0


@pytest.mark.parametrize("branch", ["main", "master", "fix-the-thing", "feature/retry"])
def test_commit_blocked_without_key(repo, branch):
    r = run({"tool_name": "Bash", "tool_input": {"command": "git add -A && git commit -m wip"}, "cwd": str(repo(branch))})
    assert r.returncode == 2
    assert "work-system hook" in r.stderr


def test_commit_with_git_c_reads_that_repo(repo):
    keyed, bare = repo("KAN-1-x"), repo("main")
    assert bash(f"git -C {keyed} commit -m x", bare) == 0
    assert bash(f"git -C {bare} commit -m x", keyed) == 2


def test_cd_then_commit_reads_the_new_directory(repo):
    keyed, bare = repo("KAN-2-y"), repo("main")
    assert bash(f"cd {bare} && git commit -m x", keyed) == 2
    assert bash(f"cd {keyed} && git commit -m x", bare) == 0


def test_outside_a_repository_is_not_judged(tmp_path):
    assert bash("git commit -m x", tmp_path) == 0


@pytest.mark.parametrize("command", [
    "git push -u origin KAN-315-work-system-layer",
    "git push --force-with-lease origin KAN-315-work-system-layer",
    "git push origin HEAD:KAN-315-work-system-layer",
])
def test_push_allowed(command):
    assert bash(command) == 0


@pytest.mark.parametrize("command", [
    "git push origin main",
    "git push origin HEAD:main",
    "git push origin +refs/heads/master",
    "git push --force origin KAN-1-x",
    "git push -f origin KAN-1-x",
    "git push -uf origin KAN-1-x",
    "git add -A && git push origin main",
])
def test_push_blocked(command):
    assert bash(command) == 2


GOOD_BODY = "What and why: adds the hook.\n\nJira: KAN-315\nDocs: README.md"


def test_pr_create_allowed_with_contract():
    cmd = f"gh pr create --title 'KAN-315: enforce the work system' --body {json.dumps(GOOD_BODY)}"
    assert bash(cmd) == 0


def test_pr_create_reads_body_file(tmp_path):
    (tmp_path / "body.md").write_text(GOOD_BODY)
    assert bash("gh pr create --title 'KAN-315: x' --body-file body.md", tmp_path) == 0
    (tmp_path / "bad.md").write_text("no lines here")
    assert bash("gh pr create --title 'KAN-315: x' --body-file bad.md", tmp_path) == 2


@pytest.mark.parametrize("command", [
    "gh pr create --fill",
    "gh pr create --title 'enforce the work system' --body 'Jira: KAN-315\nDocs: x'",
    "gh pr create --title 'KAN-315: x'",
    "gh pr create --title 'KAN-315: x' --body 'Docs: README.md'",
    "gh pr create --title 'KAN-315: x' --body 'Jira: KAN-999\nDocs: README.md'",
    "gh pr create --title 'KAN-315: x' --body 'Jira: KAN-315'",
])
def test_pr_create_blocked_without_contract(command):
    assert bash(command) == 2


@pytest.mark.parametrize("tool", ["mcp__jira__transitionJiraIssue", "mcp__atlassian__transitionJiraIssue",
                                  "mcp__Atlassian_MCP__transitionJiraIssue"])
def test_transitions_blocked(tool):
    r = run({"tool_name": tool, "tool_input": {"issueIdOrKey": "KAN-1", "transition": {"id": "31"}}})
    assert r.returncode == 2
    assert "don't move tickets" in r.stderr


def test_generic_execute_transition_blocked():
    event = {"tool_name": "mcp__atlassian__executeWrite", "tool_input": {"name": "transitionJiraIssue", "inputs": {}}}
    assert run(event).returncode == 2


@pytest.mark.parametrize("tool", ["mcp__atlassian__executeDestructive", "mcp__jira__deleteJiraIssue"])
def test_destructive_blocked(tool):
    assert run({"tool_name": tool, "tool_input": {}}).returncode == 2


@pytest.mark.parametrize("tool, args", [
    ("mcp__jira__listJiraIssueTransitions", {"issueIdOrKey": "KAN-1"}),
    ("mcp__jira__getJiraIssue", {"issueIdOrKey": "KAN-1"}),
    ("mcp__jira__createJiraIssue", {"projectKey": "KAN", "issueType": "Decision", "summary": "Which?"}),
    ("mcp__jira__addOrEditJiraIssueComment", {"issueIdOrKey": "KAN-1", "commentBody": "Started."}),
    ("mcp__atlassian__executeWrite", {"name": "createJiraIssueLink", "inputs": {}}),
    ("mcp__atlassian__createConfluenceContent", {"title": "Note"}),
    ("Edit", {"file_path": "/workspace/code/app.py"}),
])
def test_ordinary_tracker_work_allowed(tool, args):
    assert run({"tool_name": tool, "tool_input": args}).returncode == 0


def test_key_pattern_is_configurable(repo):
    d = repo("ABC_12-x")
    env_cmd = [sys.executable, str(HOOK)]
    event = json.dumps({"tool_name": "Bash", "tool_input": {"command": "git commit -m x"}, "cwd": str(d)})
    assert subprocess.run(env_cmd, input=event, capture_output=True, text=True).returncode == 2
    r = subprocess.run(env_cmd, input=event, capture_output=True, text=True,
                       env={**os.environ, "WORK_SYSTEM_KEY": r"ABC_[0-9]+"})
    assert r.returncode == 0


def test_malformed_event_is_allowed():
    r = subprocess.run([sys.executable, str(HOOK)], input="not json", capture_output=True, text=True)
    assert r.returncode == 0


def test_mcp_create_pull_request_needs_the_contract():
    ok = {"tool_name": "mcp__github__create_pull_request",
          "tool_input": {"title": "KAN-315: add the gate", "body": GOOD_BODY, "head": "KAN-315-x", "base": "main"}}
    assert run(ok).returncode == 0
    bad = {"tool_name": "mcp__github__create_pull_request", "tool_input": {"title": "add the gate", "body": GOOD_BODY}}
    assert run(bad).returncode == 2
    no_docs = {"tool_name": "mcp__github__create_pull_request",
               "tool_input": {"title": "KAN-315: x", "body": "Jira: KAN-315"}}
    assert run(no_docs).returncode == 2


@pytest.mark.parametrize("tool, args", [
    ("mcp__jira__createJiraIssue", {"projectKey": "KAN", "issueType": "Task", "summary": "x", "labels": ["lane:agent"]}),
    ("mcp__atlassian__editJiraIssue", {"issueIdOrKey": "KAN-1", "fields": {"labels": ["lane:agent", "repo:x"]}}),
    ("mcp__atlassian__editJiraIssue", {"issueIdOrKey": "KAN-1", "fields": {"labels": ["lane:pair"]}}),
    ("mcp__atlassian__executeWrite", {"name": "editJiraIssue", "inputs": {"fields": {"labels": ["lane:human"]}}}),
    ("mcp__jira__createJiraIssue", {"projectKey": "KAN", "issueType": "Task", "summary": "x", "labels": ["exec:agent"]}),
    ("mcp__atlassian__editJiraIssue", {"issueIdOrKey": "KAN-1", "fields": {"labels": ["exec:pair"]}}),
])
def test_execution_labels_are_a_persons(tool, args):
    r = run({"tool_name": tool, "tool_input": args})
    assert r.returncode == 2 and "exec" in r.stderr


@pytest.mark.parametrize("labels", [["proposed", "lane:pair", "repo:hangar"], ["decision", "needs-sean", "lane:human"],
                                    ["proposed", "exec:pair", "repo:hangar"], ["type:decision", "exec:human"]])
def test_filing_with_pair_or_human_lane_is_allowed(labels):
    args = {"projectKey": "KAN", "issueType": "Task", "summary": "x", "labels": labels}
    assert run({"tool_name": "mcp__jira__createJiraIssue", "tool_input": args}).returncode == 0


def test_editing_without_touching_lanes_is_allowed():
    args = {"issueIdOrKey": "KAN-1", "fields": {"description": "more detail"}}
    assert run({"tool_name": "mcp__jira__editJiraIssue", "tool_input": args}).returncode == 0


def run_hook(hook: Path, event) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(hook)], input=json.dumps(event), capture_output=True,
                          encoding="utf-8")


SUITE_HOOK = ROOT / "harnesses/suite-default/native/claude-code/hooks/guard_work_system.py"
WORK_HOOK = ROOT / "harnesses/work-default/native/claude-code/hooks/guard_work_system.py"


@pytest.mark.parametrize("hook", [HOOK, WORK_HOOK])
def test_merge_refused_unless_the_harness_allows_it(hook):
    # the unrendered source and work-default both mean `never`
    r = run_hook(hook, {"tool_name": "Bash", "tool_input": {"command": "gh pr merge 12 --squash"}})
    assert r.returncode == 2 and "never merge" in r.stderr
    r = run_hook(hook, {"tool_name": "mcp__github__merge_pull_request", "tool_input": {"pullNumber": 12}})
    assert r.returncode == 2


def test_suite_default_may_merge_but_never_with_admin():
    ok = run_hook(SUITE_HOOK, {"tool_name": "Bash", "tool_input": {"command": "gh pr merge 12 --squash --delete-branch"}})
    assert ok.returncode == 0
    assert run_hook(SUITE_HOOK, {"tool_name": "mcp__github__merge_pull_request", "tool_input": {}}).returncode == 0
    admin = run_hook(SUITE_HOOK, {"tool_name": "Bash", "tool_input": {"command": "gh pr merge 12 --admin --squash"}})
    assert admin.returncode == 2 and "--admin" in admin.stderr


@pytest.mark.parametrize("hook", [SUITE_HOOK, WORK_HOOK])
def test_rendered_hooks_still_refuse_transitions(hook):
    r = run_hook(hook, {"tool_name": "mcp__atlassian__transitionJiraIssue", "tool_input": {"issueIdOrKey": "KAN-1"}})
    assert r.returncode == 2


# Native Windows (KAN-460): the same verdicts and the same message bytes on every platform.

def load_hook():
    spec = importlib.util.spec_from_file_location("guard_work_system", HOOK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run_bytes(data: bytes) -> subprocess.CompletedProcess:
    # no PYTHONIOENCODING/PYTHONUTF8: the hook must not depend on the console code page
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONIOENCODING", "PYTHONUTF8")}
    return subprocess.run([sys.executable, str(HOOK)], input=data, capture_output=True, env=env)


def test_blocked_message_is_the_same_utf8_bytes_everywhere():
    event = {"tool_name": "Bash", "tool_input": {"command": "git push origin main"}}
    r = run_bytes(json.dumps(event).encode())
    assert r.returncode == 2
    assert r.stderr == b"blocked by the work-system hook: never push to main: push the ticket branch and open a PR.\n"


def test_utf8_event_with_non_ascii_text_is_still_judged():
    # raw UTF-8 (not \\u escapes), as Claude Code sends it; a cp1252 decode would fail and let it through
    blocked = {"tool_name": "Bash", "tool_input": {"command": "git commit -m 'café ✓' && git push origin main"}}
    assert run_bytes(json.dumps(blocked, ensure_ascii=False).encode("utf-8")).returncode == 2
    ok = {"tool_name": "mcp__github__create_pull_request",
          "tool_input": {"title": "KAN-315: naïve résumé ✓", "body": "Jira: KAN-315\nDocs: none needed – café"}}
    assert run_bytes(json.dumps(ok, ensure_ascii=False).encode("utf-8")).returncode == 0


def test_event_with_a_byte_order_mark_is_read():
    event = {"tool_name": "Bash", "tool_input": {"command": "git push origin main"}}
    assert run_bytes(b"\xef\xbb\xbf" + json.dumps(event).encode()).returncode == 2


def test_non_ascii_reason_is_written_as_utf8(repo):
    d = repo("fix-café")
    event = {"tool_name": "Bash", "tool_input": {"command": "git commit -m x"}, "cwd": str(d)}
    r = run_bytes(json.dumps(event).encode())
    assert r.returncode == 2
    assert "'fix-café' has no ticket key".encode("utf-8") in r.stderr


@pytest.mark.parametrize("encoding, bom", [("utf-8", b""), ("utf-8", b"\xef\xbb\xbf"), ("utf-16-le", b"\xff\xfe")])
def test_body_file_from_any_windows_editor(tmp_path, encoding, bom):
    # Windows PowerShell 5 `Out-File` writes UTF-16 with a BOM; Notepad may add a UTF-8 BOM
    (tmp_path / "body.md").write_bytes(bom + (GOOD_BODY + " – é").replace("\n", "\r\n").encode(encoding))
    assert bash("gh pr create --title 'KAN-315: x' --body-file body.md", tmp_path) == 0
    (tmp_path / "bad.md").write_bytes(bom + "no lines – é".encode(encoding))
    assert bash("gh pr create --title 'KAN-315: x' --body-file bad.md", tmp_path) == 2


@pytest.mark.parametrize("segment, words", [
    (r"git -C C:\Users\me\repo commit -m x", ["git", "-C", r"C:\Users\me\repo", "commit", "-m", "x"]),
    (r'cd "C:\Users\me\my repo"', ["cd", r"C:\Users\me\my repo"]),
    (r"git commit -m a\ b", ["git", "commit", "-m", "a b"]),  # POSIX escapes still hold without a drive path
])
def test_windows_drive_paths_keep_their_backslashes(segment, words):
    assert load_hook()._words(segment) == words


@pytest.mark.parametrize("command", [
    "git.exe push origin main",
    "GIT.EXE push --force origin KAN-1-x",
    r'"C:\Program Files\Git\cmd\git.exe" push origin main',
    "/mingw64/bin/git push origin main",
    "gh.exe pr merge 12 --admin",
    r"C:\tools\gh.exe pr create --fill",
])
def test_windows_program_names_are_recognised(command):
    assert bash(command) == 2


def test_relative_body_file_with_backslashes(tmp_path):
    (tmp_path / "pr").mkdir()
    (tmp_path / "pr" / "body.md").write_text(GOOD_BODY, encoding="utf-8")
    sep = "\\" if os.name == "nt" else "/"
    assert bash(f"gh pr create --title 'KAN-315: x' --body-file 'pr{sep}body.md'", tmp_path) == 0


@pytest.mark.skipif(os.name != "nt", reason="Git Bash drive paths exist only on Windows")
def test_git_bash_drive_path_is_mapped(repo):
    bare, keyed = repo("main"), repo("KAN-3-z")
    msys = "/" + str(bare)[0].lower() + str(bare)[2:].replace("\\", "/")
    assert bash(f"cd {msys} && git commit -m x", keyed) == 2
    assert bash(f"git -C {msys} commit -m x", keyed) == 2


@pytest.mark.skipif(os.name != "nt", reason="native Windows only")
def test_backslash_drive_paths_reach_the_right_repository(repo):
    keyed, bare = repo("KAN-4-w"), repo("main")
    assert bash(f'git -C "{bare}" commit -m x', keyed) == 2
    assert bash(f"cd {keyed} && git commit -m x", bare) == 0


# Every command in a call is judged, however it is separated (KAN-460 review).

@pytest.mark.parametrize("command", [
    "echo ok\ngit push origin main",
    "echo ok\r\ngit push --force origin KAN-1-x",
    "true & git push origin main",
    "git status\n  gh pr merge 12 --admin",
    "echo a; gh pr create --fill",
    "git \\\npush origin main",
])
def test_every_line_and_separator_is_judged(command):
    assert bash(command) == 2


def test_newline_commit_on_main_is_judged(repo):
    assert bash("git add -A\ngit commit -m wip", repo("main")) == 2


def test_redirect_ampersand_is_not_a_separator():
    assert bash("git push origin KAN-1-x 2>&1 | tail -1") == 0


def test_input_that_is_not_utf8_fails_closed():
    r = run_bytes(b'{"tool_name": "Bash", "tool_input": {"command": "git status \xe9\xff"}}')
    assert r.returncode == 2 and b"not valid UTF-8" in r.stderr
