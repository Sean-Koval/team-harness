# Evals

- `golden/*.json`: one call per case, run by `tests/test_contract.py` on the fake backend. A case names the `tool`,
  its `arguments`, and what it returns: `structured_content`, and `is_error` when the call should fail.
- Agent evals (`tasks/*.yaml`, with a model and a hard budget) come with the artifact-check workflow; none yet.
