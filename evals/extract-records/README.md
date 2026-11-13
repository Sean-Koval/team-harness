# Extraction eval

Measures the `extract-records` skill (KAN-435) on fixed sources with expected records (KAN-464).

- **Cases:** the skill's examples in `tests/fixtures/extract-records/`, plus regression cases in `cases/`. `cases.yaml`
  adds per-case limits on how many records a run may produce.
- **Extractor:** sees a case's `before/` tree only. `recorded/` holds one run's proposals and `run.json` says who made
  them and against which `SKILL.md`.
- **Grader:** `scripts/extract_grade.py`, deterministic. It pairs records by type and similar title, compares status,
  scope, owner, date, `valid_to`, links and the source quote, and runs ai-dlc's `knowledge check` on the result.
- **Gates** (`config.yaml`, from north-star outcome O3): recall at least 80%; under 25% of records need an edit or
  deletion; no limit, link or check failures; blind precision and recall within 5 points of `baseline.json`.

```sh
python scripts/extract_eval.py                    # fixture mode: replays recorded/, no key needed
python scripts/extract_eval.py --require-fresh    # CI: also fails when recorded/ predates SKILL.md
ANTHROPIC_API_KEY=... python scripts/extract_eval.py --live --record   # rerun the model, replace recorded/
```

After changing the skill, rerun live with `--record` and commit `recorded/`. Live runs use the model pinned in
`config.yaml`; `--model latest` asks the API for its newest.
