Scripts can't read `hangar sb ls` or `hangar env list`: they print tables only.

Add a `--json` flag to both. With it, print the API's list (from the CLI's `_call` helper) as indented JSON, through
the CLI's existing `_print` helper. Without it, the table output stays exactly as it is. The CLI is
`src/hangar/cli.py`.
