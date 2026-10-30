When a job fails (for example the sandbox's image build was denied), the issue comment hangar posts says only
`**Finished with problems** - hangar job ... (error)` and tells the reader to reply on a PR that doesn't exist.

Make the final comment (`JobService._final_comment`) explain the failure and how to retry: include a
`What went wrong: <message>` line taken from the job's last event (e.g.
`What went wrong: error: failed to create sandbox: ...`). Point at the PR (`on the PR`) only when the job has one;
otherwise say to comment `/hangar` or re-add the `hangar` label to retry (the phrase ``re-add the `hangar` label``).
The code is in `src/hangar/jobs.py`; run `tests/test_jobs.py`.
