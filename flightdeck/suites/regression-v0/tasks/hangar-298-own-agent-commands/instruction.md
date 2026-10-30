Under `approvals: ask`, the agent's closing `hangar-agent done "<summary>"` is held as a pending Bash approval, so
every ask-mode turn needs a pointless click at the end.

Add `own_command(tool, data) -> bool` to `src/hangar/driver.py`: true only for a shell tool call (Claude Code's
`Bash`, Codex's `shell`) that is exactly one `hangar-agent done | progress | ask | result '<json>'` command.

- Single-quoted text may hold anything; multi-line quoted summaries and `$VAR` inside double quotes are fine.
- Anything else still asks: `;`, `&&`, `||`, `|`, `&`, redirections, subshells, unquoted newlines, a trailing or
  line-continuing backslash, backquotes, `$(...)` and `${...}` (also inside double quotes), unclosed quotes, a
  first word other than the bare `hangar-agent` (a path, an env assignment, `sudo`, `bash -c '...'`), and the
  subcommands that read or run other things (`artifact`, `result @FILE`, `env`, `svc`, and the computer commands).
- For Codex, look into the command's argv only in its three-item `[<bash>, "-lc", SCRIPT]` form, on SCRIPT with its
  quoting intact; any other argv doesn't count.

`Driver.request` answers such a call `allow` at once under `ask` and `deny-risky`, still emitting the
`hangar.approval_request` and a `hangar.approval_resolved` with `by: policy`; `auto` is unchanged. Document it in
`docs/steering.md`. Run `tests/test_driver.py`.
