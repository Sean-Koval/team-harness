# regression-v0: the selection rule

Written 2026-10-29, before any pull request was listed or any test run (KAN-222). The suite README reports what
the rule produced; this file is the rule as it stood before that.

## Window and model

- Model: `claude-opus-5-5` (`decision.yaml`, both arms). Its training cutoff is June 2026; it was released
  2026-09-21 (hangar `tests/fixtures/models/anthropic.json`). Every repository below was created after 2026-10-10,
  so no pull request predates either.
- Window end: merged before 2026-10-29T00:00:00Z.
- Window start: walk back from the end over merged pull requests of all repositories, newest first, and keep each
  that qualifies until 20 are kept. The start is the merge time of the 20th. Every qualifying pull request merged
  inside the window is in the suite.
- `mined_after` of a task is its pull request's merge date.

## Repositories

- flightdeck, team-harness and ai-dlc: any pull request that qualifies.
- hangar: only one-module pull requests, whose fix changes exactly one file, a `.py` under `src/hangar/`.

## A pull request qualifies when

1. It was merged (a merge commit on `main`), into the default branch.
2. It changes or adds a test file (`tests/**/test_*.py`).
3. Fail-to-pass: on the merge commit's first parent (`base_sha`), at least one test in the hidden files fails; on
   the merge commit, every test in them passes. Run twice on the merge commit; a test that flips is excluded.
   Skipped tests count as neither. Run without network, Docker or KVM, as a hangar grader sandbox has none.
4. The fix (changed files outside `tests/` and `docs/`, and not `*.md`) is 1 to N = 3 files, and includes code
   (`.py` or another source file), not only configuration.

## Excluded

- Docs-only pull requests (no fix file).
- Dependency bumps: only `pyproject.toml`, `uv.lock`, requirements or workflow pins change, or the title starts with
  `Bump` or `build(deps)`.
- Fixes over N = 3 files, and hangar pull requests whose fix is not one module.
- Pull requests whose hidden tests cannot fit hangar's one grader per experiment: at most 3 grader files per task
  (`test.sh`, the PR's test file(s) holding the fail-to-pass tests, and `conftest.py` when they need it), and
  1 MB for all 20 tasks together (`MAX_GRADER_FILES`, 64 files).

## If fewer than 20 qualify

Widen N to 5, then extend the window back, and record which was done. Fail-to-pass is never relaxed.

## The hidden test

The pull request's version of each changed test file that holds a fail-to-pass test, run whole: its other tests
are pass-to-pass checks. The instruction comes from the linked Jira ticket or the PR body, rewritten so it states the
problem and not the fix.
