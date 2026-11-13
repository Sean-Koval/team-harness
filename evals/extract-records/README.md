# Extraction eval

Measures the `extract-records` skill (KAN-435) on fixed sources with expected records (KAN-464).

- **Cases:** the skill's examples in `tests/fixtures/extract-records/`, plus regression cases in `cases/`. Cases 10 to 12 are long, messy synthetic sources shaped like real ones. `cases.yaml`
  adds per-case limits on how many records a run may produce.
- **Extractor:** sees the rendered skill and a case's `before/` tree only. `recorded/` holds one run's proposals, and
  `run.json` says who made them and against which `SKILL.md`.
- **Grader:** `scripts/extract_grade.py`, deterministic. It pairs records of one type on their verbatim source quote;
  the title only breaks ties. A pair whose title says another day, number or a negated verb is wrong. It counts
  edits to title, status, scope, owner, date, `valid_to`, links and quote, and a description that is empty or
  copies the title, and any record `knowledge check` refuses. Whether a description gives the why needs a person: `run.json`'s `needs_human` lists those.
  Cases in `run.json`'s `pending` have no recording yet and are reported, not graded. It runs ai-dlc's
  `knowledge check` on the result.
- **Severity** (KAN-474): each edited or dropped record is substantive or cosmetic. Substantive: a wrong type, scope,
  boundary, status, owner, date, `valid_to` or link; a quote that is not verbatim; a record the check refuses; a
  contradicting claim; a deletion. Cosmetic: title or description wording. A `needs_human` record is its own class.
  `classify_pr_edit` applies the same rules to a live records PR, for `knowledge stats` (KAN-467).
- **Gates** (`config.yaml`, from north-star outcome O3): recall at least 80%; under 10% of records need a substantive
  edit or deletion; no limit, link or check failures; cost under $5 a run. Cosmetic edits and the old 25% total figure
  are reported beside the gate and never fail a run. The report names the case and field of every substantive edit.

## Three ways to run it

```sh
python scripts/extract_eval.py --require-fresh             # fixture: replays recorded/, no login, no key (CI)
python scripts/extract_eval.py --live --runner claude-cli  # live, default: Claude Code CLI on your own login
python scripts/extract_eval.py --live --runner api         # live: Messages API with ANTHROPIC_API_KEY
```

Both live runners use the one `model` in `config.yaml`; `--case <id>` runs one case. The CLI runner works in an
empty temporary directory with every tool off, so it cannot read `after/`. In CI the nightly live job needs a
`CLAUDE_CODE_OAUTH_TOKEN` secret (from `claude setup-token`); without it the job reports itself skipped.

## Current numbers

Cases 10–12 are run 4: blind, by a separate agent, with the skill from #30 at abb5fe1, which sets `belongs_to` by
type. Precision and recall are 100%, and no record needs an edit. Over all cases, 3% are substantive and 3% cosmetic
(7% total), so the 10% gate passes.

The one substantive edit is case 07's missing `belongs_to` link; the cosmetic one is case 08's reworded title. Cases
01–09 are not blind: their author saw the case list. `baseline.json` holds these numbers; it is not a gate.

## Next step for Sean

The recording predates the newest `SKILL.md`, so `--require-fresh`, and with it CI, fails until a live re-record.
That is intended. On a machine logged in to Claude Code, run
`python scripts/extract_eval.py --live --runner claude-cli --record`, then commit `recorded/` and update
`baseline.json` from its summary. Record again the same way after every skill change.
