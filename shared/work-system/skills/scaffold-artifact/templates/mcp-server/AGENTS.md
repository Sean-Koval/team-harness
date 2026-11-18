# @@project@@: guidance for agents

@@description@@ Started from ticket @@ticket@@.

## Owner and approvals

- Owner: {{owner}}.
- Approvals: {{approvals}}

## Verify

Run before every commit and keep it green; CI runs the same on Linux and Windows:

```sh
python -m pip install -e ".[dev]"
python -m ruff check . && python -m ruff format --check . && python -m pyright && python -m pytest -q
```

## Conventions

- One ticket, one branch (`<KEY>-slug`), one small PR whose title starts with the key.
- Each PR adds its changelog entry as `changes/<KEY>.md` (see `changes/README.md`).
- A new tool comes with its golden case in `evals/golden/`; `tests/test_contract.py` fails without one.
- The server reaches the service only through `Backend` (`backend.py`); tests use the fake in `tests/fakes.py`.
- Credentials come from the environment, never from a file in the repository.
- Files a tool generates (lock files, build output) are not edited by hand.
