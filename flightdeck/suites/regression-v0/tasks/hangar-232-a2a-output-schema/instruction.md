Two problems around structured results and hand-offs:

1. Over A2A, a `SendMessage` whose `output_schema` is invalid (for example `{"type": 5}` in the message's
   `metadata.outputSchema`, or a schema on a text part's `metadata.schema`) is answered as `-32603 Internal error`
   with a logged traceback. It must be an invalid-params error, `-32602`, whose message names `output_schema`, as a
   rejected job is. A valid schema on the text part must reach the job (`job.output_schema`; message metadata wins
   over the part), and the agent's `hangar-agent result` comes back as the task's `Structured result` artifact.
2. The bundled `repo-conventions` skill (`envs/skills/repo-conventions/SKILL.md`) tells the agent to hand off in its
   final message or in notes files, which disagrees with the job prompt (`src/hangar/jobs.py` asks for a summary in
   `RESULT.md`). Its **Hand off** step must say to write the summary with `hangar-agent done` or to the
   `` `RESULT.md` path your task names ``, never into the repo; the final message only when the task names neither;
   and no notes files.

Document structured results in `docs/a2a.md`. Run `tests/test_a2a.py` and `tests/test_frontdoor.py`.
