# Repository guidance

This is the example team harness: `harnesses/<name>/` is what agents run with, pinned by `harness.lock` (see [README.md](README.md)). This file is guidance for working on the repository itself, not part of any harness.

## Tracking

- Work is tracked in Jira project KAN (<https://seanmkoval.atlassian.net>). GitHub Projects is retired; GitHub Issues are for outside reports only.
- Work tied to a ticket carries its key, so the GitHub for Jira app links it: the branch starts with it (`KAN-35-apply-atomic`), the PR title starts with it (`KAN-35: make hangar apply all or nothing`) and the PR body has a `Jira: KAN-35` line. Commits may mention it. Work without a ticket (typo fixes, outside contributions) needs no key.
- A lane is a project: its Jira epic. Who executes a ticket is its execution label:
  - Only `exec:agent` tickets start a hangar job, when moved to "Ready for agent". They must be job-sized: one repo or
    one change-set profile, acceptance criteria and a verify command (`templates/ticket.md`).
  - `exec:pair` is Sean with Claude Code.
  - `exec:human` is Sean only.

  The older `lane:*` names are accepted until Jira is relabelled (KAN-326).
- Merging: agents may merge PRs on this and the other suite repositories once checks are green and no review was asked
  for (suite-default `github-pr`). They never merge at work (work-default).

## The shared work-system layer

- Edit the work-system skills and hook only in `shared/work-system/`. What differs per harness (owner, Decision type,
  knowledge-base site and space, merge rule, approval steps) is a `{{placeholder}}` filled from
  `shared/work-system/profiles/<harness>.yaml`. Never write a person, a company or a site into a shared file. Then run `python scripts/sync_shared.py`, `python scripts/relock.py harnesses/<h> --write` and `python scripts/render_envs.py harnesses/<h>` for each harness in `shared/work-system/targets.yaml`. Never edit the copies under `harnesses/`.
- A new harness revision moves `candidate` in `channels.yaml`; only a promotion moves `stable`.
