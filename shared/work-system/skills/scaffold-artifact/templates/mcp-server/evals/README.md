# Evals

- `golden/*.json`: one call per case, run by `tests/test_contract.py` on the fake backend. A case names the `tool`,
  its `arguments`, and what it returns: `structured_content`, or `"is_error": true` when the call should fail with a tool error (`ToolError`).
- Agent evals (`tasks/*.yaml`, with a model and a hard budget) come with the artifact-check workflow; none yet.
