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
  `shared/work-system/profiles/<harness>.yaml`. Never write a person, a company or a site into a shared file. Never edit the copies under `harnesses/`.

## Parallel PRs (KAN-481)

- A PR commits sources only: `shared/`, `orgs/`, a harness's own files, scripts, tests, docs. It never commits generated
  files: the shared layer's copies in `harnesses/`, any `harness.lock` or `env.*.yaml`, the `candidate` lines in
  `channels.yaml`, or `AGENT_ENV_HARNESS_DIGEST` in `environments/agent.yaml`. CI builds them on the PR merged with
  main; `.github/workflows/generated.yml` commits them on main after each merge. So one PR's merge can't conflict
  with another's.
- To test locally, run `python scripts/build_generated.py` (needs hangar), run the tests, then
  `python scripts/build_generated.py --restore` before you commit; it puts back only generated files and lines. CI
  fails a PR that commits them (`--guard`); a lock frozen from a run goes in a PR labelled `generated-files`. After its
  build, CI also fails any generated file a PR commits that differs from the built one (`--drift`): edit the source.
- `generated.yml` pushes the build to main only after the same checks pass. Where main refuses the push (once
  code-owner review is on, KAN-220: locks and `channels.yaml` are owned paths) it opens a `bot/generated` PR and
  starts `check.yml` on it; that PR still needs a person's merge.
- The changelog entry is a fragment, `changes/<KEY>.md` (see `changes/README.md`); never edit `CHANGELOG.md`.
- `stable` and `releases/` still move only by `scripts/promote.py`, in a PR of its own.
- A new harness revision moves `candidate` in `channels.yaml`; only a promotion moves `stable`.
