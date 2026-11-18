# Evals

- `golden/*.json`: one call per case, run by `tests/test_contract.py` on the fake backend. A case names the `tool`,
  its `arguments`, and what it returns: `structured_content`, or `"is_error": true` when the call should fail with a tool error (`ToolError`).
- The artifact check (team-harness's `artifact-check` workflow) runs the same cases over stdio, against
  `python tests/serve_fake.py`: the real server on the fake backend, so CI needs no service or credentials.
