A repository policy's naming conventions (`branch_template`, `require_ticket`, `title_template`) can only be set over
REST today. Add them to the CLI's `hangar repo set OWNER/REPO`:

- `--branch-template TEXT`, `--title-template TEXT`, and a tri-state `--require-ticket` / `--no-require-ticket`
  (like the existing `--rerun-flaky`).
- Each goes into the PUT body only when given; omitted flags keep their stored values. An empty string (`''`)
  clears a template by sending an explicit `null` for it.
- A value the server refuses (a branch template without `{job}`, an unknown placeholder in a title template) fails
  with exit code 1 and the server's message (`error 400: ...`), and changes nothing.
- The policy line printed by `repo set` and `repo list` shows them when set: `branch: <template>`,
  `ticket required` or `ticket not required`, and `PR title: <template>`. `repo get` already prints the JSON.
- `hangar repo unset` must be able to clear them (list them in its help).

Document the flags in `docs/repo-policy.md` and mention them in `docs/changesets.md`. `tests/test_editorial.py`
holds each docs page under a word ceiling that only goes down: `docs/changesets.md` must end at or under 1,397
words of prose (its other limits unchanged). Run `tests/test_frontdoor.py` and `tests/test_editorial.py`.
