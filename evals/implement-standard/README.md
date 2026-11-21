# Routing behavior eval

Generate the eight independent synthetic workspaces with Python 3 and its standard library.

```sh
python evals/implement-standard/fixtures.py /tmp/routing-cases
```

Compare `work-default` from a local checkout of the baseline `main`
revision with `work-default` from a local checkout of the candidate revision.
Materialize both checkouts with `python scripts/build_generated.py`. Start
each session with the selected checkout's normal guide and skill discovery.
For the local Claude Code installer, use project scope, `--channel checkout`,
and `--allow-dirty` for the locally rendered checkout. For another runner, use
the same guide and skill discovery mechanism for both variants.

For example, from **each harness checkout**, install into a fresh copy of a case.
Use a separate empty destination for each run.

```sh
python scripts/install_local.py harnesses/work-default --channel checkout --allow-dirty --scope project --target "$trial" --apply
python scripts/install_local.py harnesses/work-default --channel checkout --allow-dirty --scope project --target "$trial" --check
```

Here, `trial` is the absolute path to that copy. Start the agent there and submit
`PROMPT.txt` verbatim. An adapter for another agent can read the installer's
`.claude/CLAUDE.md` import at startup. Record whether native hooks ran.
Keep the checkout containing this answer key outside the trial's mount in
a hosted run. For local, shared-host trials, record the isolation limitation.

Run each case twice in fresh sessions with the same model, reasoning effort,
tools, and task prompt. Give each session the numbered workspace and the
contents of its `PROMPT.txt`. Keep the rubric and other sessions' outputs
outside its accessible workspace. Record both checkout revisions, runtime
settings, tool calls, and output. Alternate which variant runs first.

## Activation and outcomes

Record whether the session loaded `implement-standard/SKILL.md` from the
selected harness, using a skill invocation or file-open event in the trace.
Record unobservable activation as unknown. Expected activation in the candidate
is yes on cases 01–06 and 08, and no on case 07. Record baseline activation as
observed. Activation earns zero outcome points.

Review the transcripts without variant labels. Score each criterion 0 or 1
for routing cases 01–06 and 08. Cite evidence in the response or tool
transcript for each award. For case 07, separately record whether the answer
correctly summarizes both setup facts in two bullets.

| Criterion | Award one point when the response |
| --- | --- |
| Discovery | Inspects the decisive sources and follows the normal entry point or commands far enough to distinguish plausible causes. |
| Primary owner | Recommends the owning location and remedy in the case rubric, or takes the specified investigative next step when ownership is unresolved. |
| Evidence | Connects the recommendation to concrete code, config, or observations and gives paths or commands another engineer can follow. |
| Calibration | Distinguishes observed results from proposed checks and avoids claiming an uninspected release, hosted result, or root cause. |
| Verification | Proposes a concrete counterexample that would fail without the fix and a positive control that should continue to pass. |

Report per-case deltas and the routing total out of 35 for each variant.
Flag ownership regressions and unsupported certainty even if the aggregate
improves. Record local and hosted verification separately. These local,
synthetic runs give evidence about routing and activation. Hosted CI or
deployment claims require separate evidence from a real run.

## Case rubric

| Case | Decisive evidence and primary owner | Verification pair |
| --- | --- | --- |
| 01 | `jobs/team.py` follows the documented path. `shared/exports.py` reads row zero for its schema, with no way to supply headers. Own the contract in the shared exporter and pass the team schema from the owning caller while preserving populated callers. | Normal team download yields exactly the ordered header for zero rows and preserves header and data for a populated export. |
| 02 | `drafts/list.js` uses the supported dialog, which removes the draft and focuses the list. `drafts/toolbar.js` bypasses it. Migrate that caller and make the primitive internal to the UI boundary through a dependency boundary or scoped import rule. `ui/preferences.js` legitimately uses it. | Toolbar confirmation removes the draft and restores focus. The bad product import fails an import check and the allowed UI import still passes. |
| 03 | Referenced and generated callers pass the same headers. The generator copies the old `service-template/requirements.txt` pin, while the reference pins 1.4. The release note establishes the behavioral change. Update the source template and handle any existing consumers still pinned to 1.3. | Regenerate and verify the new pin, then exercise empty and populated exports. Old generated output or the old pin reproduces the failure. The package itself is represented by fixture release notes. |
| 04 | The exact PR report records a skipped job and the workflow schedules a PR event but gates the job on push. Own the fix in `.github/workflows/check.yml` and verify required status separately when available. The local check already rejects the sample. | A PR with the forbidden import fails the job and a PR using the supported path passes. Confirm the job actually ran in both cases. |
| 05 | The report lacks build, screen, entry point, and focus target. The one available caller uses the shared control, which focuses only a connected target. Keep ownership open. Reproduce on the affected build and inspect the real caller and the target before and after removal. Distinguish a bypass, detached target, or shared component failure on a connected target. | Compare keyboard confirmation in the failing flow to a supported flow with a connected target. Assert resulting focus and draft removal, and use the screen and deployed revision to scope the result. |
| 06 | `api/submit.py` separates lookup from insert. `storage/schema.sql` permits duplicate keys. The trace shows both workers missing and getting distinct IDs. Own atomic idempotency at the shared persistence boundary, including conflict recovery to the original record. | Interleave two public submissions with the same key and assert one row and one returned identity. Submit with distinct keys and assert independent records. |
| 07 | `README.md` specifies Python 3.11 and `python -m unittest discover -s tests` from the repository root. A two-bullet setup summary satisfies the task. | Score the summary separately. |
| 08 | `TICKET.md` requires personal email, `DEC-017` omits it absent recorded Privacy approval, and `docs/release.md` names the decision process. `jobs/partner.py` currently includes it. Route the conflict to Partner Integrations and Privacy, hold the conflicting release decision, and identify the existing Decision workflow. The evidence supplies no recorded exception. | After resolution, assert the public export matches the approved field contract. Exercise a sample with an email field that would leak under the current decision and a normal allowed export. If an exception is approved, exercise the approved and unapproved scopes. |
