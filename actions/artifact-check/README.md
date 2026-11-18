# Artifact check

Unit tests don't show that an MCP server's tools can be called, or that an agent still does its job. This check does,
cheaply enough to run on every PR, before SRE and infosec see the artifact. It is repository-local; harness A/B stays
in flightdeck. The logic is [`artifact_check.py`](artifact_check.py); the reusable workflow is
[`.github/workflows/artifact-check.yml`](../../.github/workflows/artifact-check.yml).

## What it checks

- **mcp-server:** it starts the server over stdio and lists its tools. Each tool needs a description and a valid
  JSON Schema 2020-12 object as its input schema. Then it runs every `evals/golden/*.json` call, and each tool needs one
  (a `coverage:<tool>` case fails otherwise). A case with `"is_error": true` expects a tool error (`isError`), never a
  protocol error. At the end the server and everything it started are killed.
- **agent or bot:** it runs `evals/tasks/*.yaml` one at a time through the repository's agent command, on the given
  model. The budget is checked between tasks: once it is spent, no task starts and the rest are reported `not_run`. One
  task can overrun it, and a run that spent more than its budget fails. A task's spend counts even when it fails. When a task's cost can't be read (no `usage`, or a rate the price table lacks), no further
  task starts, since the budget could no longer be held.

Each server answer or task gets `timeout` seconds and the whole run `time-limit`; cases past it are `not_run`.

An MCP server passes only when every case passes. An agent or bot passes at `min-pass-rate`.

## The receipt

`artifact-check.json` holds the kind, each case's result, tokens, cost and model. It validates against
[`receipt.schema.json`](receipt.schema.json), is uploaded as the `artifact-check` run artifact and is summed up in the
job summary. Cost comes from the usage hook's price table (`shared/work-system/hooks/prices.json`). A model with no
row there is refused, since its budget couldn't be held.

## Call it from a repository

Pin the workflow and `harness-ref` to the same full commit SHA:

```yaml
jobs:
  artifact-check:
    uses: Sean-Koval/team-harness/.github/workflows/artifact-check.yml@<sha>
    with:
      kind: mcp-server
      harness-ref: <sha>
      command: python tests/serve_fake.py   # the scaffold template's server on its fake backend
```

`setup` installs the repository before the check; its default is `pip install -e ".[dev]"`, so a server in another
language sets its own. For an agent or bot, set `kind: agent`, `command` to a script that runs one task, and
`budget-usd`. Pass the model key as `secrets: {model-api-key: ...}`; the job token gets read access only.

It is a quality gate, not a security boundary. The PR's own setup and command run in the same job, so they could
rewrite the check or read the model key. Call it on `pull_request`, never `pull_request_target`, and give it a key
with a spending cap of its own, which is the only hard cap. The SHA check refuses a moving `harness-ref`; it can't tell that it matches the SHA
the workflow is pinned at.

## The agent command and its tasks

A task file has an `id`, an `input` and `expect: {contains: [...]}`, a non-empty list of strings the output must
hold; a task that checks nothing fails. The command reads
the task as JSON on stdin. `ARTIFACT_CHECK_MODEL` and `ARTIFACT_CHECK_BUDGET_USD` (what is left) are in its
environment. Its last stdout line is `{"output": "...", "usage": {...}}`, where `usage` is the API's usage object, or a
list of them for a multi-turn task.

On Windows the command reaches CreateProcess without a shell, which starts only `.exe` files: write `cmd /c npx ...`
for a `.cmd` shim such as `npx` or `npm`.
