Add `hangar pack list` to the CLI: it lists the harnesses from the server's `GET /api/harnesses` (through the CLI's
`_call` helper, like the other list commands).

- `--json` prints the list as returned, as JSON.
- Otherwise one line per harness: the name padded to 16 characters, a space, then the version; for an agent the
  version is padded to 12 characters and followed by ` agent`, plus ` (deprecated)` when `deprecated` is set. For
  example `f"{'claude-code':16} {'latest':12} agent"` and `f"{'git':16} latest"`.

The CLI is `src/hangar/cli.py`.
