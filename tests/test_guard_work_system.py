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


def test_input_that_is_not_json_fails_closed():
    r = subprocess.run([sys.executable, str(HOOK)], input="not json", capture_output=True, text=True)
    assert r.returncode == 2 and "not valid JSON" in r.stderr


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


# Bypasses from the KAN-371 review (comment 10491): commands hidden in substitutions, nested shells, groups and
# prefixes are judged like any other (KAN-459). The hook is still a convenience; branch protection and CI enforce.

@pytest.mark.parametrize("command", [
    "$(gh pr merge 5)",
    "echo $(gh pr merge 5 --squash)",
    "echo `gh pr merge 5`",
    "echo \"$(git push origin main)\"",
    "cat <(git push origin main)",
    "bash -c 'git push origin main'",
    "sh -c \"git status; git push --force origin KAN-1-x\"",
    "bash -lc 'gh pr merge 5'",
    "eval git push origin main",
    "eval 'gh pr merge 5'",
    "(git push origin main)",
    "( git push origin main )",
    "{ git push origin main; }",
    "env git push origin main",
    "env -i HOME=/x git push origin main",
    "command git push origin main",
    "exec gh pr merge 5",
    "if true; then git push origin main; fi",
    "gh api repos/o/r/pulls/5/merge -X PUT",
    "gh api -X PUT /repos/o/r/pulls/12/merge -f merge_method=squash",
    "gh api repos/o/r/merges -f base=main -f head=x",
    "bash -c \"bash -c 'eval git push origin main'\"",
])
def test_hidden_commands_are_judged(command):
    assert bash(command) == 2


@pytest.mark.parametrize("command", [
    "git commit -m 'KAN-1: a; git push origin main' --dry-run 2>/dev/null || true",
    "echo 'gh pr merge 5'",
    "gh api repos/o/r/pulls/5",
    "gh api repos/o/r/pulls/5/reviews",
    "bash -c 'git status'",
    "echo $(git rev-parse HEAD)",
    "(cd /tmp && ls)",
    "env FOO=1 git push origin KAN-1-x",
])
def test_quoted_and_harmless_commands_pass(command, tmp_path):
    assert run({"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(tmp_path)}).returncode == 0


def test_suite_default_merge_through_the_api_follows_its_rule():
    ok = run_hook(SUITE_HOOK, {"tool_name": "Bash", "tool_input": {"command": "gh api -X PUT repos/o/r/pulls/5/merge"}})
    assert ok.returncode == 0


# Role and server binding, not Atlassian tool names (KAN-459).

def run_bound(event, bindings: dict) -> subprocess.CompletedProcess:
    env = {**os.environ, "WORK_SYSTEM_MCP_BINDINGS": json.dumps(bindings)}
    return subprocess.run([sys.executable, str(HOOK)], input=json.dumps(event), capture_output=True,
                          encoding="utf-8", env=env)


FAKE = {"tracker": ["tickets"]}  # a tracker server that is not Atlassian's, with its own tool names


@pytest.mark.parametrize("tool, args", [
    ("mcp__tickets__issue_transition", {"key": "KAN-1", "to": "Done"}),
    ("mcp__tickets__moveTicket", {"key": "KAN-1", "status": "In Review"}),
    ("mcp__tickets__resolve_issue", {"key": "KAN-1"}),
    ("mcp__tickets__issues_delete", {"key": "KAN-1"}),
    ("mcp__tickets__removeTicket", {"key": "KAN-1"}),
    ("mcp__tickets__run", {"operation": "ticket_transition", "args": {}}),
    ("mcp__tickets__run", {"operation": "ticket_frobnicate"}),
    ("mcp__tickets__run", {}),
    ("mcp__tickets__frobnicate", {"key": "KAN-1"}),
    ("mcp__tickets__ticket_update", {"key": "KAN-1", "labels": ["exec:pair"]}),
    ("mcp__tickets__new_ticket_create", {"labels": ["exec:agent"]}),
])
def test_bound_tracker_with_other_tool_names_is_guarded(tool, args):
    assert run_bound({"tool_name": tool, "tool_input": args}, FAKE).returncode == 2
    # the same calls on a server bound to nothing, with no Atlassian-like name, are not the hook's
    assert run_bound({"tool_name": tool.replace("tickets", "notes"), "tool_input": args}, FAKE).returncode == 0


@pytest.mark.parametrize("tool, args", [
    ("mcp__tickets__get_ticket", {"key": "KAN-1"}),
    ("mcp__tickets__list_transitions", {"key": "KAN-1"}),
    ("mcp__tickets__search_tickets", {"query": "x"}),
    ("mcp__tickets__ticket_create", {"summary": "x", "labels": ["exec:pair"]}),
    ("mcp__tickets__add_comment", {"key": "KAN-1", "body": "file it exec:agent? no, exec:pair"}),
    ("mcp__tickets__run", {"operation": "get_ticket"}),
])
def test_bound_tracker_reads_and_ordinary_writes_pass(tool, args):
    assert run_bound({"tool_name": tool, "tool_input": args}, FAKE).returncode == 0


@pytest.mark.parametrize("tool, code", [
    ("mcp__ai-dlc__work_context", 0), ("mcp__ai-dlc__work_status", 0), ("mcp__ai-dlc__work_link", 0),
    ("mcp__ai-dlc__work_start", 0), ("mcp__ai-dlc__work_finish", 0), ("mcp__ai_dlc__knowledge_find", 0),
    ("mcp__ai-dlc__knowledge_append", 0), ("mcp__ai-dlc__project_docs_gate", 0), ("mcp__ai-dlc__doctor", 0),
    ("mcp__ai-dlc__work_transition", 2), ("mcp__ai-dlc__tracker_delete", 2), ("mcp__ai-dlc__work_frobnicate", 2),
])
def test_ai_dlc_tools_are_judged_by_role_verb(tool, code):
    assert run({"tool_name": tool, "tool_input": {"work_id": "KAN-1"}}).returncode == code


@pytest.mark.parametrize("tool", ["mcp__claude_ai_Atlassian__transitionJiraIssue",
                                  "mcp__plugin_x_jira__deleteJiraIssue", "mcp__Atlassian_MCP__executeDestructive"])
def test_unbound_atlassian_like_servers_are_still_guarded(tool):
    assert run({"tool_name": tool, "tool_input": {}}).returncode == 2


def test_profiles_bind_roles_to_the_servers_their_locks_pin():
    import yaml
    targets = yaml.safe_load((ROOT / "shared/work-system/targets.yaml").read_text())
    for h, entry in targets["harnesses"].items():
        params = yaml.safe_load((ROOT / "shared/work-system" / entry["profile"]).read_text())["params"]
        bindings = json.loads(params["mcp_bindings"])
        lock = yaml.safe_load((ROOT / "harnesses" / h / "harness.lock").read_text())
        pinned = {m["name"] for m in lock["binding"]["mcp"]}
        for role in ("tracker", "wiki"):
            assert bindings[role] and set(bindings[role]) <= pinned, (h, role, bindings[role], pinned)


@pytest.mark.parametrize("hook, server", [(SUITE_HOOK, "atlassian"), (WORK_HOOK, "jira")])
def test_rendered_hooks_carry_their_binding(hook, server):
    r = run_hook(hook, {"tool_name": f"mcp__{server}__frobnicate", "tool_input": {}})
    assert r.returncode == 2 and "fail closed" in r.stderr


@pytest.mark.parametrize("tool", ["mcp__ai-dlc__tracker_create", "mcp__tickets__tracker_create"])
def test_exec_agent_is_refused_on_any_tracker_role_create(tool):
    args = {"project": "KAN", "summary": "x", "labels": ["exec:agent", "repo:x"]}
    r = run_bound({"tool_name": tool, "tool_input": args}, FAKE)
    assert r.returncode == 2 and "exec:agent" in r.stderr
    args["labels"] = ["exec:pair"]
    assert run_bound({"tool_name": tool, "tool_input": args}, FAKE).returncode == 0


@pytest.mark.parametrize("tool", ["mcp__ai-dlc__tracker_update", "mcp__ai-dlc__work_update", "mcp__tickets__tracker_update"])
def test_execution_label_edits_are_refused_on_any_tracker_role_update(tool):
    r = run_bound({"tool_name": tool, "tool_input": {"key": "KAN-1", "labels": ["exec:human"]}}, FAKE)
    assert r.returncode == 2 and "execution label" in r.stderr


def test_ai_dlc_knowledge_notes_may_mention_labels():
    event = {"tool_name": "mcp__ai-dlc__knowledge_note", "tool_input": {"body": "Sean files it exec:agent later."}}
    assert run(event).returncode == 0


# The wiki wall (KAN-438): sessions propose records; only the render job writes the wiki.

WIKI_WRITES = [
    ("mcp__atlassian__createConfluencePage", {"cloudId": "x.atlassian.net", "spaceId": "SD", "title": "Note"}),
    ("mcp__atlassian__createConfluenceContent", {"title": "Note"}),
    ("mcp__atlassian__updateConfluencePage", {"cloudId": "x.atlassian.net", "pageId": "7", "body": "x"}),
    ("mcp__atlassian__createConfluenceFooterComment", {"pageId": "7", "body": "x"}),
    ("mcp__atlassian__executeWrite", {"name": "createConfluencePage", "inputs": {"spaceId": "SD"}}),
    ("mcp__jira__createPage", {"spaceKey": "SD"}),
]


@pytest.mark.parametrize("tool, args", WIKI_WRITES)
@pytest.mark.parametrize("hook", [HOOK, SUITE_HOOK, WORK_HOOK])
def test_wiki_writes_are_refused_by_default(hook, tool, args):
    r = run_hook(hook, {"tool_name": tool, "tool_input": args})
    assert r.returncode == 2 and "render job" in r.stderr


@pytest.mark.parametrize("tool, args", [
    ("mcp__atlassian__getConfluencePage", {"pageId": "7"}),
    ("mcp__atlassian__searchConfluenceUsingCql", {"cql": "space = SD"}),
    ("mcp__atlassian__createJiraIssue", {"projectKey": "KAN", "summary": "x"}),
])
def test_wiki_reads_and_tracker_writes_pass(tool, args):
    assert run({"tool_name": tool, "tool_input": args}).returncode == 0


def test_a_wiki_only_server_with_other_tool_names_is_walled():
    for tool in ("mcp__docs__new_document", "mcp__docs__frobnicate"):
        assert run_bound({"tool_name": tool, "tool_input": {}}, {"wiki": ["docs"]}).returncode == 2
    assert run_bound({"tool_name": "mcp__docs__get_document", "tool_input": {}}, {"wiki": ["docs"]}).returncode == 0


@pytest.fixture
def allowing_hook(tmp_path):
    allow = json.dumps([{"site": "kb.example.net", "space": "NOTES"}])
    hook = tmp_path / "guard_work_system.py"
    hook.write_text(HOOK.read_text(encoding="utf-8").replace("{{wiki_write_allow}}", allow), encoding="utf-8")
    return hook


@pytest.mark.parametrize("args, code", [
    ({"cloudId": "kb.example.net", "spaceKey": "NOTES", "title": "x"}, 0),                         # allowed pair
    ({"cloudId": "https://KB.example.net/wiki", "spaceId": "notes", "title": "x"}, 0),             # same, other form
    ({"name": "createConfluencePage", "cloudId": "kb.example.net", "inputs": {"spaceKey": "NOTES"}}, 0),
    ({"cloudId": "kb.example.net", "spaceKey": "OTHER", "title": "x"}, 2),                         # wrong space
    ({"cloudId": "elsewhere.example.net", "spaceKey": "NOTES", "title": "x"}, 2),                  # wrong site
    ({"cloudId": "kb.example.net", "pageId": "7", "title": "x"}, 2),                               # no space named
])
def test_wiki_write_allowlist(allowing_hook, args, code):
    tool = "mcp__atlassian__executeWrite" if "name" in args else "mcp__atlassian__createConfluencePage"
    r = run_hook(allowing_hook, {"tool_name": tool, "tool_input": args})
    assert r.returncode == code, r.stderr
    if code:
        assert "render job" in r.stderr


@pytest.mark.parametrize("label", ["EXEC:AGENT", "Exec:Agent", "exec : agent", " exec:agent ", "LANE:AGENT"])
def test_exec_agent_is_matched_in_any_case_and_spacing(label):
    args = {"projectKey": "KAN", "summary": "x", "labels": [label]}
    r = run({"tool_name": "mcp__jira__createJiraIssue", "tool_input": args})
    assert r.returncode == 2 and "exec:agent" in r.stderr
    edit = {"issueIdOrKey": "KAN-1", "fields": {"labels": [label.replace("agent", "pair").replace("AGENT", "PAIR")]}}
    assert run({"tool_name": "mcp__jira__editJiraIssue", "tool_input": edit}).returncode == 2


@pytest.mark.parametrize("tool", ["mcp__ai_dlc__wiki_upsert", "mcp__ai-dlc__wiki_create", "mcp__ai-dlc__wiki_page_update",
                                  "mcp__ai-dlc__confluence_publish", "mcp__ai-dlc__wiki_frobnicate"])
def test_ai_dlc_wiki_writes_are_walled(tool):
    r = run({"tool_name": tool, "tool_input": {"space": "SD", "title": "x"}})
    assert r.returncode == 2


@pytest.mark.parametrize("tool", ["mcp__ai-dlc__wiki_get", "mcp__ai-dlc__wiki_search", "mcp__ai-dlc__knowledge_append"])
def test_ai_dlc_wiki_reads_and_knowledge_writes_pass(tool):
    assert run({"tool_name": tool, "tool_input": {"query": "x"}}).returncode == 0


# The remaining bypasses (KAN-371): the merge routes around `gh pr merge`, scripts, xargs, source, aliases,
# interpreters, heredocs and HTTP writes to Jira or Confluence, and look-alike labels (comment 10526).

MERGE_ROUTES = [
    "gh -R o/r pr merge 5",
    "gh --repo=o/r pr merge 5 --auto",
    "gh pr review 5 --approve",
    "gh -R o/r pr review 5 -a",
    "gh api graphql -f query='mutation { mergePullRequest(input: {pullRequestId: \"x\"}) { clientMutationId } }'",
    "gh api graphql -f query='mutation { enablePullRequestAutoMerge(input: {}) { clientMutationId } }'",
    "gh api repos/o/r/pulls/5/reviews -f event=APPROVE",
    "gh api -X PUT repos/o/r/pulls/5/reviews/9/dismissals -f message=x",
    "curl -X PUT https://api.github.com/repos/o/r/pulls/5/merge",
    "bash -c 'gh -R o/r pr merge 5'",
]


@pytest.mark.parametrize("command", MERGE_ROUTES)
@pytest.mark.parametrize("hook", [HOOK, WORK_HOOK])
def test_every_merge_route_is_refused_at_work(hook, command):
    r = run_hook(hook, {"tool_name": "Bash", "tool_input": {"command": command}})
    assert r.returncode == 2, command


def test_suite_default_still_merges_with_a_repo_flag():
    for command in ("gh -R o/r pr merge 5 --squash", "gh pr review 5 --approve"):
        assert run_hook(SUITE_HOOK, {"tool_name": "Bash", "tool_input": {"command": command}}).returncode == 0


@pytest.mark.parametrize("tool, args", [
    ("mcp__github__enable_pr_auto_merge", {"pullNumber": 5}),
    ("mcp__github__pull_request_review_write", {"method": "create", "event": "APPROVE"}),
    ("mcp__github__create_pull_request_review", {"event": "approve"}),
])
@pytest.mark.parametrize("hook", [HOOK, WORK_HOOK])
def test_mcp_auto_merge_and_approval_are_refused_at_work(hook, tool, args):
    assert run_hook(hook, {"tool_name": tool, "tool_input": args}).returncode == 2
    assert run_hook(SUITE_HOOK, {"tool_name": tool, "tool_input": args}).returncode == 0


def test_mcp_comment_review_passes():
    args = {"method": "create", "event": "COMMENT", "body": "looks fine"}
    assert run({"tool_name": "mcp__github__pull_request_review_write", "tool_input": args}).returncode == 0


@pytest.fixture
def scripts(tmp_path):
    def write(name: str, text: str, executable: bool = False) -> None:
        p = tmp_path / name
        p.write_text(text, encoding="utf-8")
        if executable:
            p.chmod(0o755)
    write("merge.sh", "#!/bin/sh\necho ok\ngh pr merge 5\n", executable=True)
    write("merge.py", "import subprocess\nsubprocess.run([\"gh\", \"pr\", \"merge\", \"5\"])\n")
    write("ok.sh", "#!/bin/sh\necho ok\n", executable=True)
    write("notes.txt", "gh pr merge 5\n")
    return tmp_path


@pytest.mark.parametrize("command", [
    "bash merge.sh",
    "sh ./merge.sh",
    "./merge.sh",
    "source merge.sh",
    ". merge.sh",
    "python3 merge.py",
    "printf 'gh pr merge 5' > new.sh && chmod +x new.sh && ./new.sh",
    "cat > new.sh <<'EOF'\ngh pr merge 5\nEOF\nbash new.sh",
    "echo 5 | xargs gh pr merge",
    "echo main | xargs git push origin",
    "echo 5 | xargs -I{} sh -c 'gh pr merge {}'",
    "find . -name x -exec gh pr merge 5 \;",
    "alias m='gh pr merge'; m 5",
    "alias p='git push origin main'\np",
    "f() { gh pr merge 5; }; f",
    "X=merge; gh pr $X 5",
    "P='git push origin main'; $P",
    "$'\\x67h' pr merge 5",
    "git -c alias.p='push --force' p origin KAN-1-x",
    "git config alias.p 'push origin main'",
    "gh alias set mm 'pr merge'",
    "eval \"$(printf 'gh pr merge 5')\"",
    "watch -n 5 'gh pr merge 5'",
    "nohup setsid gh pr merge 5",
    "python3 -c 'import os; os.system(\"gh pr merge 5\")'",
    "python3 -c 'import subprocess; subprocess.run([\"git\", \"push\", \"--force\", \"origin\", \"x\"])'",
    "node -e 'require(\"child_process\").execSync(\"gh pr merge 5\")'",
    "perl -e 'system(\"git push origin main\")'",
    "pwsh -Command 'gh pr merge 5'",
    "awk 'BEGIN { system(\"gh pr merge 5\") }'",
    "python3 - <<'PY'\nimport subprocess\nsubprocess.run(['gh', 'pr', 'merge', '5'])\nPY",
    "bash <<'SH'\ngit push origin main\nSH",
    "cat <<'SH' | bash\ngh pr merge 5\nSH",
    "echo 'gh pr merge 5' | bash",
    "bash <<< 'gh pr merge 5'",
    "curl -X POST https://x.atlassian.net/rest/api/3/issue/KAN-1/transitions -d '{\"transition\": {\"id\": \"31\"}}'",
    "curl -sS -u u:t -H 'Content-Type: application/json' --data '{}' https://x.atlassian.net/wiki/api/v2/pages",
    "http PUT https://x.atlassian.net/rest/api/3/issue/KAN-1 labels:='[\"exec:agent\"]'",
    "python3 -c 'import requests; requests.post(\"https://x.atlassian.net/rest/api/3/issue/K-1/transitions\")'",
    "acli jira workitem transition --key KAN-1 --status Done",
])
def test_scripts_interpreters_and_http_writes_are_judged(scripts, command):
    r = run({"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(scripts)})
    assert r.returncode == 2, command


@pytest.mark.parametrize("command", [
    "bash ok.sh",
    "./ok.sh",
    "bash -euo pipefail ok.sh",
    "cat notes.txt",
    "python3 -m pytest -q",
    "python3 -c 'print(1)'",
    "python3 - <<'PY'\nprint('hi')\nPY",
    "cat > notes.md <<'EOF'\ngit push origin main\nEOF",
    "git commit -m \"$(cat <<'EOF'\nKAN-1: fix\n\nnotes.txt mentions gh pr merge 5; it's prose\nEOF\n)\" --dry-run",
    "echo 5 | xargs gh pr view",
    "ls | xargs wc -l",
    "find . -name '*.py' -exec grep -l x {} \;",
    "curl -sS https://x.atlassian.net/rest/api/3/issue/KAN-1",
    "curl -fsSL https://example.com -o out",
    "curl -H 'Accept: application/json' https://api.github.com/repos/o/r/pulls/5",
    "gh pr view 5 -R o/r",
    "gh pr review 5 --comment -b 'looks fine'",
])
def test_ordinary_scripts_and_reads_pass(scripts, command):
    r = run({"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(scripts)})
    assert r.returncode == 0, (command, r.stderr)


@pytest.mark.parametrize("label", ["exec​:agent", "exec：agent", "ｅxec:ａgent", "exec:⁠agent",
                                   "lane﹕agent"])
@pytest.mark.parametrize("hook", [HOOK, WORK_HOOK])
def test_look_alike_execution_labels_are_normalised(hook, label):
    args = {"projectKey": "KAN", "summary": "x", "labels": [label]}
    r = run_hook(hook, {"tool_name": "mcp__jira__createJiraIssue", "tool_input": args})
    assert r.returncode == 2 and "exec:agent" in r.stderr
    edit = {"issueIdOrKey": "KAN-1", "fields": {"labels": [label.replace("agent", "pair")]}}
    assert run_hook(hook, {"tool_name": "mcp__jira__editJiraIssue", "tool_input": edit}).returncode == 2


# Coordinator follow-ups on #35: parameter defaults, and GraphQL piped in on stdin.

@pytest.mark.parametrize("command", ["gh ${X:-pr} merge 5", "gh ${X:=pr} merge 5", "X=pr; gh ${X:-issue} merge 5",
                                     "git push origin ${B:-main}"])
@pytest.mark.parametrize("hook", [HOOK, WORK_HOOK])
def test_parameter_defaults_are_expanded(hook, command):
    assert run_hook(hook, {"tool_name": "Bash", "tool_input": {"command": command}}).returncode == 2


@pytest.mark.parametrize("command", [
    "echo '{\"query\": \"mutation { mergePullRequest(input: {}) { clientMutationId } }\"}' | gh api graphql --input -",
    "printf 'mutation { enablePullRequestAutoMerge(input: {}) { clientMutationId } }' | gh api graphql -F query=@-",
    "cat <<'Q' | gh api graphql --input -\n{\"query\": \"mutation { addPullRequestReview(input: {event: APPROVE}) { clientMutationId } }\"}\nQ",
    "echo '{\"query\": \"mutation { mergePullRequest(input: {}) { x } }\"}' | curl -sS --data-binary @- https://api.github.com/graphql",
])
@pytest.mark.parametrize("hook", [HOOK, WORK_HOOK])
def test_graphql_on_stdin_is_judged(hook, command):
    assert run_hook(hook, {"tool_name": "Bash", "tool_input": {"command": command}}).returncode == 2


def test_harmless_graphql_on_stdin_and_defaults_pass():
    assert bash("echo '{\"query\": \"{ viewer { login } }\"}' | gh api graphql --input -") == 0
    assert bash("gh ${X:-pr} view 5") == 0


@pytest.mark.parametrize("command", [
    "git push origin main",
    "git push --force origin KAN-1-x",
    "gh pr merge 12 --squash",
    "git push -u origin KAN-315-work-system-layer",
    "gh pr list",
])
def test_powershell_calls_are_judged_like_bash(command):
    """On Windows without Git Bash, Claude Code's shell tool is PowerShell (KAN-482): the same command gets the same
    verdict and the same reason."""
    as_bash = run({"tool_name": "Bash", "tool_input": {"command": command}})
    as_ps = run({"tool_name": "PowerShell", "tool_input": {"command": command}})
    assert (as_ps.returncode, as_ps.stderr) == (as_bash.returncode, as_bash.stderr)
    assert command.startswith(("git push origin main", "git push --force", "gh pr merge")) == (as_ps.returncode == 2)


def _tool(tool: str, command) -> subprocess.CompletedProcess:
    event = {"tool_name": tool, "tool_input": {"command": command}}
    return subprocess.run([sys.executable, str(HOOK)], input=json.dumps(event).encode(), capture_output=True)


@pytest.mark.parametrize("tool", ["PowerShell", "Bash"])
@pytest.mark.parametrize("command", [
    "Start-Process gh -ArgumentList 'pr','merge','12'",
    "Start-Process -FilePath gh -ArgumentList 'pr merge 12'",
    "saps gh 'pr','merge','12'",
    "iex 'gh pr merge 12'",
    'Invoke-Expression "gh pr merge 12"',
    'gh pr `\nmerge 12',
    'gh pr `merge 12',
    "$c='merge'; gh pr $c 12",
    "$c = 'merge'; gh pr $c 12",
    "$C = 'merge'; gh pr $c 12",
    'cmd /c gh pr merge 5',
    '& gh pr merge 5',
    "& 'gh' pr merge 5",
    'gh.exe pr merge 5',
    'git.exe push origin HEAD:main',
])
def test_powershell_s_own_spellings_are_blocked(tool, command):
    """PowerShell runs these as the plain command: iex and Invoke-Expression are eval, Start-Process and cmd /c are sh -c,
    a backtick escapes the next character or the line end, and $c = 'x' is c=x (PR 40 review). The .exe name
    and a quoted program name are the same program in either shell."""
    if tool == "Bash" and "`" in command:
        pytest.skip("a lone backtick is an unclosed substitution in bash: nothing runs")
    r = _tool(tool, command)
    assert r.returncode == 2, (command, r.stderr)


@pytest.mark.parametrize("tool", ["PowerShell", "Bash"])
@pytest.mark.parametrize("command", ['git status', 'Get-ChildItem', 'Start-Process notepad', "Write-Output 'a`b'", '$x = 1; git log -1', 'cmd /c dir', "iex 'git status'"])
def test_ordinary_powershell_still_passes(tool, command):
    assert _tool(tool, command).returncode == 0, command


@pytest.mark.parametrize("data", [b"null", b"[]", b"7", b'"x"', b'{"tool_name": "Bash"}',
                                  b'{"tool_name": "PowerShell", "tool_input": {"command": 5}}',
                                  b'{"tool_name": "Bash", "tool_input": []}'])
def test_a_call_that_is_not_an_object_or_has_no_command_text_fails_closed(data):
    r = subprocess.run([sys.executable, str(HOOK)], input=data, capture_output=True)
    assert r.returncode == 2 and b"cannot be checked" in r.stderr, (data, r.stderr)


@pytest.mark.skipif(os.name == "nt", reason="closes stdin with the POSIX shell")
def test_a_closed_stdin_fails_closed():
    """With stdin closed, sys.stdin is None: the hook used to crash with exit 1, which lets the call through."""
    r = subprocess.run(["/bin/sh", "-c", f'"{sys.executable}" "{HOOK}" <&-'], capture_output=True)
    assert r.returncode == 2 and b"could not be read" in r.stderr and b"Traceback" not in r.stderr


@pytest.mark.parametrize("command", [
    "iex('gh pr merge 12')",
    'Invoke-Expression("gh pr merge 12")',
    "Invoke-Expression -Command 'gh pr merge 12'",
    "iex -Command:'gh pr merge 12'",
    'Invoke-Command {gh pr merge 12}',
    'icm -ScriptBlock { gh pr merge 12 }',
    'Invoke-Command -ComputerName build -ScriptBlock { git push origin HEAD:main }',
    'Invoke-Command{gh pr merge 12}',
    'INVOKE-EXPRESSION -Command:"gh pr merge 12"',
    "Invoke-Expression -C 'gh pr merge 12'",
    "iex -Com 'gh pr merge 12'",
    "iex -Command('gh pr merge 12')",
    "iex('gh pr merge 12; echo ''hi''')",
    "'gh pr merge 12' | iex",
    'Invoke-Command -ScriptBlock {param($n) gh pr merge $n} -ArgumentList 12',
    'Invoke-Command { if ($true) { gh pr merge 12 } }',
    "Invoke-Command -ArgumentList 'a|b' -ScriptBlock {gh pr merge 12}",
    '$sb={gh pr merge 12}; Invoke-Command $sb',
    '1 | % { gh pr merge 12 }',
    'Start-Job { gh pr merge 12 }',
    "$s = @'\nit's\n'@\nicm { gh pr merge 5 }",
    'Write-Output "x`"y"; icm { gh pr merge 5 }',
    'icm -ScriptBlock {[CmdletBinding()]param($n) gh pr merge 5}',
    "iex(\n'gh pr merge 5')",
    "Invoke-Expression @('gh pr merge 5')",
    # the PR 54 review: a nested or quoted parenthesis in param(...), and code a parenthesis runs
    "icm { param([ValidateScript({ $_ -gt (1) })]$n) gh pr merge 1 }",
    "icm { param($a=(1+(2))) gh pr merge 1 }",
    "icm { param($a = '(') gh pr merge 1 }",
    'icm { param($a = ")") gh pr merge 1 }',
    "icm { param($a = (gh pr merge 1)) }",
    "icm { param([ValidateScript({ gh pr merge 1 })]$a) }",
    "$x = (gh pr merge 1)",
    "Write-Output (gh pr merge 1)",
    "Write-Output $(gh pr merge 1)",
    # the fix round's review: code a double-quoted `$(...)` runs, and a quote inside a comment
    '"$(Write-Output (gh pr merge 1))"',
    '"$(% {gh pr merge 1})"',
    'Write-Host "$(1 | % { gh pr merge 1 })"',
    "# it's\ngh pr merge 1 # '",
    "# it's\nicm { gh pr merge 1 } # '",
    "<# it's #>gh pr merge 1<# ' #>",
    "<# x #> gh pr merge 1",
    "gh <# x #> pr merge 1",
])
def test_powershell_iex_and_invoke_command_forms_are_blocked(command):
    """KAN-491, the PR 40 post-merge review: iex('...'), -Command, an Invoke-Command or icm script block, and a
    program name in another letter case all run the plain command."""
    r = _tool("PowerShell", command)
    assert r.returncode == 2, (command, r.stderr)


@pytest.mark.parametrize("command", [
    "iex('git status')", 'Invoke-Command { git log -1 }', 'icm {Get-ChildItem}', "'git status' | iex",
    "git commit -m 'icm { gh pr merge 5 } is now blocked'", 'Get-ChildItem | Where-Object { $_.Length -gt 0 }',
    '$c = "x"; Write-Output ${c}', "Get-Item (Join-Path a b)", 'git commit -m "fix (thing)"',
    "icm { param([ValidateRange(1, 5)][int]$n = (1 + 2)) git status }",
    'Write-Output "price: $(1+2) (approx)"', "git status # it's fine", '$x = "#not a comment"; git status',
    'gh pr create --title "KAN-1: x" --body-file (Join-Path . body.md)',
])
def test_harmless_iex_and_invoke_command_still_pass(command):
    assert _tool("PowerShell", command).returncode == 0, command


def test_a_long_powershell_call_is_judged_in_linear_time():
    """The unwrapping is one pass: thousands of `icm` or `iex(` words cannot hold the hook past its timeout (10 s),
    which would let the call through. Whatever the machine, judging stops at the 5 s deadline and blocks."""
    import time
    for filler in ("icm ", "iex('", "{param($n) } ", "{param((", "| iex ", "(", "$(", "param("):
        start = time.monotonic()
        r = _tool("PowerShell", "Write-Output " + filler * 30000 + "; iex('gh pr merge 1')")
        assert time.monotonic() - start < load_hook().DEADLINE + 2, filler
        assert r.returncode == 2, (filler, r.stderr)


@pytest.mark.parametrize("command", ["# it's\ngh pr merge 1 # '", "x=1 # it's\ngh pr merge 1 # '"])
def test_a_quote_in_a_bash_comment_hides_nothing(command):
    assert bash(command) == 2, command


def test_a_hash_inside_a_word_is_not_a_comment():
    assert bash("echo a#b; git status") == 0
    assert bash("echo a#b; gh pr merge 1") == 2


def test_code_scanned_for_hidden_commands_is_judged_in_linear_time(tmp_path):
    """The fix round's review: the scan's URL and API-path patterns restarted at every `http://` or `pulls/`, so 84 KB
    of them held the hook for 12 s, past its timeout."""
    import time
    (tmp_path / "p.py").write_text("pulls/" * 50000, encoding="utf-8")
    for command in ['python3 -c "#' + "http://" * 12000 + '"; gh pr merge 1', "python3 p.py; gh pr merge 1",
                    'python3 -c "#' + "pulls/" * 30000 + '/merge"',
                    'curl -d "' + "addPullRequestReview" * 40000 + '" https://example.com; gh pr merge 1',
                    "echo '" + "a" * 1_000_000 + "'; gh pr merge 1"]:
        start = time.monotonic()
        r = run({"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(tmp_path)})
        assert time.monotonic() - start < load_hook().DEADLINE, command[:40]
        assert r.returncode == 2, (command[:40], r.stderr)


def test_the_word_splitter_reads_as_shlex_does():
    """_posix_words replaces shlex, which builds a word a character at a time: quadratic on a long word."""
    import random
    import shlex
    mod = load_hook()

    def ref(text, escape):
        lex = shlex.shlex(text, posix=True)
        lex.whitespace_split, lex.commenters = True, ""
        if not escape:
            lex.escape = ""
        try:
            return list(lex)
        except ValueError:
            return "error"

    def ours(text, escape):
        try:
            return mod._posix_words(text, escape)
        except ValueError:
            return "error"

    rng = random.Random(491)
    for _ in range(20000):
        text = "".join(rng.choice(["a", "b", " ", "\t", "\n", "'", '"', "\\", "$", "#"])
                       for _ in range(rng.randint(0, 12)))
        for escape in (True, False):
            assert ours(text, escape) == ref(text, escape), (text, escape)


def test_a_cached_script_verdict_follows_the_call_state(tmp_path):
    """The fix round's review: a script's verdict depends on the variables, the directory and the reading it is
    judged in, so the cache keys on them."""
    (tmp_path / "s.sh").write_text("gh pr $A 1\n", encoding="utf-8")
    (tmp_path / "s2.sh").write_text("./x.sh\n", encoding="utf-8")
    for d, body in (("d1", "echo ok\n"), ("d2", "gh pr merge 1\n")):
        (tmp_path / d).mkdir()
        (tmp_path / d / "x.sh").write_text(body, encoding="utf-8")
        (tmp_path / d / "x.sh").chmod(0o755)
    for tool, command in (("Bash", "bash ./s.sh; export A=merge; bash ./s.sh"),
                          ("Bash", "cd d1; bash ../s2.sh; cd ../d2; bash ../s2.sh"),
                          ("PowerShell", 'Set-Content w.sh "gh pr m`erge 1"; bash ./w.sh')):
        r = run({"tool_name": tool, "tool_input": {"command": command}, "cwd": str(tmp_path)})
        assert r.returncode == 2, (command, r.stderr)


def test_a_command_over_one_megabyte_is_blocked_unread():
    """PR 54's re-review: the deadline is checked between commands, so an 8 MB call overshot it by 1.3 s."""
    import time
    mod = load_hook()
    long_call = "echo " + "a" * mod.MAX_COMMAND
    start = time.monotonic()
    r = _tool("PowerShell", long_call)
    assert time.monotonic() - start < 2 and r.returncode == 2 and b"too long to judge" in r.stderr, r.stderr
    assert "too long to judge" in mod.why({"tool_name": "Bash", "tool_input": {"command": long_call}})
    assert mod.why({"tool_name": "Bash", "tool_input": {"command": "echo " + "a" * (mod.MAX_COMMAND - 5)}}) is None


def _big_script(path: Path) -> Path:
    line = "echo hello world; ls -la /tmp | grep x\n"
    path.write_text(line * (300_000 // len(line)), encoding="utf-8")
    return path


def test_a_script_run_many_times_is_judged_once(tmp_path, monkeypatch):
    """The PR 54 review: six runs of one large script took 13 s to judge, past the hook's timeout."""
    _big_script(tmp_path / "s.sh")
    mod = load_hook()
    judged = []
    verdict = mod._script_verdict
    monkeypatch.setattr(mod, "_script_verdict", lambda *a: judged.append(a[0]) or verdict(*a))
    event = {"tool_name": "Bash", "cwd": str(tmp_path),
             "tool_input": {"command": "bash ./s.sh; " * 6 + "gh pr merge 1"}}
    assert mod.why(event).startswith("agents never merge")
    assert judged == ["./s.sh"]


def test_a_call_that_takes_too_long_to_judge_is_blocked(tmp_path, monkeypatch):
    """Past the deadline the hook blocks rather than let its timeout kill it, which would let the call through."""
    for k in range(3):
        _big_script(tmp_path / f"s{k}.sh")
    mod = load_hook()
    monkeypatch.setattr(mod, "DEADLINE", 0.01)
    event = {"tool_name": "Bash", "cwd": str(tmp_path),
             "tool_input": {"command": "bash ./s0.sh; bash ./s1.sh; bash ./s2.sh"}}
    assert "longer than 0.01 s to judge" in mod.why(event)
    monkeypatch.setattr(mod, "DEADLINE", 60.0)
    assert mod.why(event) is None
