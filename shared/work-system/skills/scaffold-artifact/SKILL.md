---
name: scaffold-artifact
description: Use when a ticket asks for a new MCP server (a new repository or folder for one), before any feature code. Copies a template that already passes its own CI (lint, type check, contract test, Linux and Windows), fills its names from the ticket, and runs its verify command before the first commit.
---

# Scaffolding an artifact

A ticket for a new artifact starts from a scaffold that already passes CI, so the work goes into the tools, not the
setup. Only the `mcp-server` type exists today: a Python MCP server (the `mcp` SDK's decorator server), a contract
test, a golden-call eval, `changes/` fragments and CI on Linux and Windows. Agent and bot templates come later; for
those, say there is no template yet and stop.

## Steps

1. **Have the ticket.** The ticket key comes first (skill `work-start`). From the ticket take the server's name, as
   lowercase words joined by hyphens (`weather-tools`), and one line saying what it does.
2. **Pick the destination.** A new, empty directory: the new repository's clone, or a new folder in the repository
   the ticket names. Never scaffold over existing files; the script refuses a directory that is not empty.
3. **Render the template.** From this skill's directory:

   ```sh
   python scaffold.py mcp-server <destination> --name <name> --ticket <KEY> --description "<one line>"
   ```

   It copies `templates/mcp-server/`, fills `@@project@@` (the name), `@@package@@` (the name as a Python package,
   `weather_tools`), `@@ticket@@` and `@@description@@` in file names and contents, and fails if any token is left.
4. **Run the template's verify command** in the destination, before the first commit:

   ```sh
   python -m pip install -e ".[dev]"
   python -m ruff check . && python -m ruff format --check . && python -m pyright && python -m pytest -q
   ```

   All four must pass. If one fails, fix the scaffold, not the check, and report it: the template is meant to pass
   as rendered.
5. **Commit the scaffold alone**, as the first commit on the ticket's branch (`<KEY>-scaffold` or the ticket's
   branch), with the changelog fragment the template wrote (`changes/<KEY>.added.md`). Feature work comes after, in
   its own commits.
6. **Replace the example.** The template's `search` tool and its `Backend` are an example: replace them with the
   ticket's tools, keep `tests/test_contract.py` (it lists every tool and checks its schema) and add one golden case
   per tool under `evals/golden/`.

## What the scaffold holds

| Path | What it is |
| --- | --- |
| `src/<package>/server.py` | `build_server(backend)`: the tools, over a `Backend` the tests replace with a fake |
| `src/<package>/backend.py` | The `Backend` protocol and the real one, which you wire to the service |
| `tests/test_contract.py` | Lists the tools, validates each input schema, runs every `evals/golden/*.json` case on a fake |
| `evals/` | Golden calls now; agent evals later (`evals/README.md`) |
| `changes/` | Changelog fragments, `changes/<KEY>.md` or `changes/<KEY>.<kind>.md`, never one shared file |
| `AGENTS.md` | Owner, approvals, conventions and the verify command, for the agents that work in the repository |
| `.github/workflows/ci.yml` | ruff, pyright and pytest on `ubuntu-latest` and `windows-latest` |

The owner and approval steps in the rendered `AGENTS.md` come from this harness: owner {{owner}}; approvals:
{{approvals}}

## Rules

- Generated files (lock files the tools write, build output) never go in a PR by hand.
- No person, company, site or credential goes into the template's files beyond what this harness's profile filled.
- Keep each PR small: one ticket, one PR, its own changelog fragment.
