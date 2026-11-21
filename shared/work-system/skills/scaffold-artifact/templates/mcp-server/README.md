# @@project@@

@@description@@

An MCP server over stdio. Run it with `python -m @@package@@`; point a client at that command.

## Develop

```sh
# macOS, Linux or Git Bash
python -m pip install -e ".[dev]"
python -m ruff check . && python -m ruff format --check . && python -m pyright && python -m pytest -q
```

```powershell
# Windows PowerShell (5.1 has no &&)
python -m pip install -e ".[dev]"
python -m ruff check .; if ($?) { python -m ruff format --check . }; if ($?) { python -m pyright }; if ($?) { python -m pytest -q }
```

Tools live in `src/@@package@@/server.py`; the service they call is `src/@@package@@/backend.py`. Every tool needs a
golden case in `evals/golden/` (see `evals/README.md`).
