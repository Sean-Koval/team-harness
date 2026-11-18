# Artifact check

One cheap eval gate for a scaffolded repository, run on each PR before SRE and infosec see it (KAN-517). It writes a
receipt, `artifact-check.json`, that the [work-system PR check](../work-system-pr/README.md) reads (rule 9).

## What it checks

- **`mcp-server`** starts the server over stdio, on its fake backend, and lists its tools. Each tool needs a
  description and a valid JSON Schema object as its input schema. Every case in `evals/golden/*.json` is then called:
  its arguments must fit the schema, and the answer must match `structured_content`, or fail when `is_error` is true.
  A tool that no golden case calls fails. A broken schema fails with the tool named.
- **`agent`** and **`bot`** run each `evals/tasks/*.yaml` through the repository's own runner, with a hard budget.
  The cap is checked between tasks, and the runner gets what is left in `ARTIFACT_CHECK_BUDGET_USD`, so it can stop
  itself mid-task. A run stopped at the cap reports its partial results as `incomplete`, which never passes.

The runner gets the task file as its last argument, the model in `ARTIFACT_CHECK_MODEL` and the key in
`ARTIFACT_CHECK_API_KEY`. Its last line of output is one JSON object: `{"passed": true, "tokens": 1200,
"cost_usd": 0.004, "detail": ""}`.

## The receipt

[`receipt.schema.json`](receipt.schema.json) (`team-harness.artifact-check/v1`) is the contract. It holds the kind,
the result (`pass`, `fail` or `incomplete`), the model, budget, spend, tokens and pass rate, and one entry per case
with its result and why. The run also writes a table to the job summary.

## Adopt it

Call the reusable workflow, pinned by commit, and pass the same commit as `harness-ref`. Then hand the receipt to the
PR check:

```yaml
jobs:
  artifact:
    uses: <owner>/team-harness/.github/workflows/artifact-check.yml@<commit sha>
    with:
      kind: mcp-server
      harness-repository: <owner>/team-harness
      harness-ref: <commit sha>
      server: python -m tests.fake_server
  pr:
    needs: artifact
    if: always()
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/checkout@v5
      - uses: actions/download-artifact@v4
        with:
          name: artifact-check
        continue-on-error: true
      - uses: <owner>/team-harness/actions/work-system-pr@<commit sha>
        with:
          artifact-receipt: artifact-check.json
```

For `agent` or `bot`, pass `runner`, a cheap `model`, `budget-usd` (default 1) and, when fewer than all tasks must
pass, `pass-rate`. Pass the key as the `model-api-key` secret. Fork PRs get no secrets, so their agent eval fails;
run it on branches in the repository.

## Run it locally

```sh
pip install jsonschema pyyaml
python actions/artifact-check/artifact_check.py mcp-server --root ../my-server --server "python -m my_server.fake"
```

On Windows the server and runner commands are passed whole to the process, so quote paths as `cmd` does.
