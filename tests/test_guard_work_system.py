"""The shared work-system PreToolUse guard: work carries a ticket key, and agents don't move tickets."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "shared/work-system/hooks/guard_work_system.py"


def run(event) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(HOOK)], input=json.dumps(event), capture_output=True, text=True)


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
                       env={"PATH": "/usr/bin:/bin", "WORK_SYSTEM_KEY": r"ABC_[0-9]+"})
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
    return subprocess.run([sys.executable, str(hook)], input=json.dumps(event), capture_output=True, text=True)


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


@pytest.mark.parametrize("event", [
    {"tool_name": "Bash", "tool_input": {"command": "gh -R acme/svc pr merge 12 --squash"}},
    {"tool_name": "Bash", "tool_input": {"command": "gh --repo=acme/svc pr merge 12"}},
    {"tool_name": "Bash", "tool_input": {"command": "gh api -X PUT repos/acme/svc/pulls/12/merge"}},
    {"tool_name": "Bash", "tool_input": {"command": "gh api graphql -f query='mutation { enablePullRequestAutoMerge(input: {}) { clientMutationId } }'"}},
    {"tool_name": "Bash", "tool_input": {"command": "gh api repos/acme/svc/pulls/12/reviews -f event=APPROVE"}},
    {"tool_name": "Bash", "tool_input": {"command": "gh pr review 12 --approve"}},
    {"tool_name": "Bash", "tool_input": {"command": "bash -c \"gh pr merge 12\""}},
    {"tool_name": "mcp__github__enable_pr_auto_merge", "tool_input": {"pullNumber": 12}},
    {"tool_name": "mcp__github__pull_request_review_write", "tool_input": {"method": "create", "event": "APPROVE"}},
])
@pytest.mark.parametrize("hook", [HOOK, WORK_HOOK])
def test_no_route_around_never_merge(hook, event):
    r = run_hook(hook, event)
    assert r.returncode == 2 and "never merge" in r.stderr


@pytest.mark.parametrize("event", [
    {"tool_name": "Bash", "tool_input": {"command": "gh pr review 12 --comment -b 'looks fine'"}},
    {"tool_name": "Bash", "tool_input": {"command": "gh api repos/acme/svc/pulls/12/files"}},
    {"tool_name": "Bash", "tool_input": {"command": "gh -R acme/svc pr view 12"}},
    {"tool_name": "mcp__github__pull_request_review_write", "tool_input": {"method": "create", "event": "COMMENT"}},
])
def test_reading_and_commenting_still_allowed_at_work(event):
    assert run_hook(WORK_HOOK, event).returncode == 0


def test_gh_repo_flag_does_not_skip_the_pr_contract():
    r = run_hook(WORK_HOOK, {"tool_name": "Bash", "tool_input": {"command": "gh -R acme/svc pr create --fill"}})
    assert r.returncode == 2


def test_suite_default_still_merges_with_a_repo_flag():
    ok = run_hook(SUITE_HOOK, {"tool_name": "Bash", "tool_input": {"command": "gh -R o/r pr merge 12 --squash"}})
    assert ok.returncode == 0
