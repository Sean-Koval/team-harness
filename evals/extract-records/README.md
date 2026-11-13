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

Re-graded on 2026-11-12 with the severity split. The trustworthy subset is cases 10–12, extracted blind by a separate
agent: precision 100% and recall 100%. Of its records, 27% need a substantive edit and none a cosmetic one, so the
27% total is all substantive.

All of it is case 10: two records lack `belongs_to` the ticket the Source names, and one quote is not verbatim. Over
all cases, 14% are substantive and 3% cosmetic (17% total). Case 07 also lacks a `belongs_to` link, and case 08 has a
reworded title.

So the eval fails the new gate on the current recording. Missing `belongs_to` links are three of the four
substantive edits; a skill fix for them is in flight (KAN-435). Cases 01–09 are not blind: their author saw the case
list. `baseline.json` holds these numbers; it is not a gate.

## Next step for Sean

The recording predates the newest `SKILL.md`, so `--require-fresh`, and with it CI, fails until a live re-record.
That is intended. On a machine logged in to Claude Code, run
`python scripts/extract_eval.py --live --runner claude-cli --record`, then commit `recorded/` and update
`baseline.json` from its summary. Record again the same way after every skill change.
