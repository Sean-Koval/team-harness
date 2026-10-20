# Repository guidance

This is the example team harness: `harnesses/<name>/` is what agents run with, pinned by `harness.lock` (see [README.md](README.md)). This file is guidance for working on the repository itself, not part of any harness.

## Tracking

- Work is tracked in Jira project KAN (<https://seanmkoval.atlassian.net>). GitHub Projects is retired; GitHub Issues are for outside reports only.
- Work tied to a ticket carries its key, so the GitHub for Jira app links it: the branch starts with it (`KAN-35-apply-atomic`), the PR title starts with it (`KAN-35: make hangar apply all or nothing`) and the PR body has a `Jira: KAN-35` line. Commits may mention it. Work without a ticket (typo fixes, outside contributions) needs no key.
- Lanes: only `lane:agent` tickets (job-sized: one repo or one change-set profile, acceptance criteria, a verify command) start a hangar job, when moved to "Ready for agent". `lane:pair` is Sean with Claude Code; `lane:human` is Sean only.
