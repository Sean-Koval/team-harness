An experiment checks each trial against the trial's pin set, so a trial whose environment drifted after the pin set
was recorded ends as `infra_error` with `infra_reason: drift` and is excluded. That check is flaky: when a trial's
turn is short and finishes between two of the experiment's polls of its job, the drift is never noticed and the
drifted trial counts as the agent's result.

Make the outcome independent of poll timing. A trial whose environment drifted must end as `infra_error` / `drift`,
excluded, even when its job has already ended by the time the experiment looks at it (for example with
`settings.job_poll_seconds = 5`). The check must still run only once per trial, and an already-ended job must not
be cancelled again.

The code is in `src/hangar/` (experiments and pin sets). Run the repository's own tests for these areas
(`tests/test_pinsets.py`, `tests/test_trialcache.py`) before you finish.
