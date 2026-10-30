An experiment's grader runs sealed, with the hidden tests outside the repo, but the grade can still be forged or
silently wrong: the grader command runs as the sandbox user and writes `$HANGAR_GRADE_OUT` where the trial's code can
overwrite it, nothing checks that the hidden tests actually fail without a fix, and nothing detects a leak of the
hidden tests. Add these to `src/hangar/experiments.py`:

- **Trust.** Each grade records `trust`: `isolated` (uid split, pristine copy and the `hangar-grade` runner),
  `best_effort` (no split) or `low` (`files_mode: in_repo`, or a command whose program isn't `hangar-grade`), plus
  `runner` (`hangar-grade` or `command`) and `isolation`. Where the uid split exists, the grade output belongs to
  hangar's user, not the command's.
- **Base must fail.** Once per task per experiment (shared by concurrent graders, kept in the state as
  `task_checks`, not rerun after a restart), run the hidden tests on the pinned base with no patch, in its own grader
  sandbox labelled `<task>/base/0`. If they pass, the task is invalid with reason `hidden tests pass on base`: every
  grade of the task and every trial carries `task_invalid: true`, and the experiment gets a note containing
  `invalid_task <task>`. An optional `Task.reference_patch` that fails the hidden tests or doesn't apply flags the
  task the same way.
- **Canaries.** `Grader.canary` is optional; unset, `CANARY_PREFIX` (`HANGAR-CANARY-`) plus a uuid4 is generated
  when the experiment starts and stored only in the spec. It is written as a comment into every hidden test file with
  a known comment syntax (`grade.canary_files` counts them; a `.txt` file takes none). A canary found in the trial's
  patch, summaries, trace or egress records marks the trial `contaminated: true`. It is shown as `CANARY_MASK` in the
  experiment's view, exports and grades.
- **Touched tests.** Each trial carries `touched_tests` (from the job's result, else derived from the patch).

`view` exposes `trust`, `task_invalid`, `contaminated` and `touched_tests` per trial. Update `docs/jobs.md` and the
experiment schema. Run `tests/test_interfaces.py`.
