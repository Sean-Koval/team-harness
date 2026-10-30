The docs have no reference pages generated from the code, so the CLI's documentation drifts from its commands.

Add `scripts/docs_reference.py`, which writes `docs/cli.md` (every `flightdeck` command and option) and the Parquet
column tables in `docs/contracts.md` from the code, and can tell when they are out of date. It must be importable as
a module with:

- `walk(command, path)`: yields `(path, command)` for every command under a Click command (from
  `typer.main.get_command(app)`), `path` being the tuple of names after `flightdeck`;
- `cli_reference() -> str`: the CLI page, with a `### \`flightdeck <path>\`` heading per command and each parameter
  listed as `` `NAME` `` (an argument, upper case) or by its first option string (`` `--out` ``);
- `stale()`: the generated pages that differ from what the script would write (empty when current).

Run it and commit the generated pages, and link them from the docs navigation. Pages under `docs/` follow the
repository's editorial and link checks.
