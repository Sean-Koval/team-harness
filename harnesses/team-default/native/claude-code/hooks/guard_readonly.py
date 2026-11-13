#!/usr/bin/env python3
"""PreToolUse hook: keep production read-only from the agent's shell.

Claude Code passes the tool call as JSON on stdin. For a Bash call, this blocks commands that would change a
cluster or print a credential, by exiting 2 with the reason on stderr (Claude Code shows it to the agent and skips
the call). Everything else is allowed with exit 0. It reads only the command text, runs nothing and writes nothing.

The MCP servers are read-only on their own (`--read-only`, viewer roles); this covers the shell, where an
environment may also have `kubectl`, `helm` or `gcloud`.
"""

from __future__ import annotations

import json
import re
import sys

BLOCKED = [
    (r"\bkubectl\b(?:\s+-\S+(?:\s+\S+)?)*\s+(apply|create|replace|patch|edit|delete|scale|autoscale|annotate|label|"
     r"taint|cordon|uncordon|drain|set|rollout\s+(restart|undo|pause|resume)|exec|cp|port-forward|debug)\b",
     "kubectl may only read (get, describe, logs, top, events, rollout status/history)"),
    (r"\bkubectl\b.*\bget\b.*\bsecrets?\b.*(-o|--output)[ =]?(yaml|json|jsonpath|go-template)",
     "Secret values stay unread: list Secret names only"),
    (r"\bhelm\s+(install|upgrade|uninstall|delete|rollback)\b",
     "helm may only read (list, status, history, get values)"),
    (r"\bgcloud\s+container\s+(clusters|node-pools)\s+(create|delete|update|resize|upgrade)\b",
     "gcloud container may only read"),
    (r"\bgcloud\s+auth\s+(print-access-token|print-identity-token)\b", "never print a credential"),
    (r"(^|[;&|]\s*)(printenv|env)\s*($|[;&|])", "don't dump the environment: it holds credentials"),
    (r"\bcat\b.*(\.kube/config|kubeconfig|credentials\.json|\.git-credentials)", "never print a credential file"),
]


def _commands(command: str) -> list[str]:
    """The whole call with each line ending made a `;`, then every single command in it. Each is judged, so a
    newline, `;`, `&&`, `||`, `|` or `&` cannot hide a command from a pattern."""
    joined = re.sub(r"\s*\r?\n\s*", " ; ", re.sub(r"\\\r?\n", " ", command))
    return [joined] + [c for c in re.split(r"\s*(?:;|&&|\|\||\||(?<![<>])&(?![>&]))\s*", joined) if c]


def _read_event() -> tuple[object, str | None]:
    """(event, problem): the event read as UTF-8 bytes on every platform (on Windows sys.stdin decodes with the
    console code page). problem names why the input cannot be checked (not UTF-8, not JSON): the caller fails closed."""
    try:
        text = sys.stdin.buffer.read().decode("utf-8-sig")
    except UnicodeDecodeError:
        return None, "the tool call is not valid UTF-8, so it cannot be checked"
    except OSError:
        return None, None
    try:
        return json.loads(text), None
    except ValueError:
        return None, "the tool call is not valid JSON, so it cannot be checked"


def _block(message: str) -> int:
    sys.stderr.flush()
    sys.stderr.buffer.write((message + "\n").encode("utf-8"))
    sys.stderr.buffer.flush()
    return 2


def main() -> int:
    event, problem = _read_event()
    if problem:
        return _block(f"blocked by the team harness: {problem}. Diagnose read-only and propose the change in a PR.")
    if not isinstance(event, dict) or event.get("tool_name") != "Bash":
        return 0
    for command in _commands(str((event.get("tool_input") or {}).get("command") or "")):
        for pattern, why in BLOCKED:
            if re.search(pattern, command):
                return _block(f"blocked by the team harness: {why}. Diagnose read-only and propose the change in a PR.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
