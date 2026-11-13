#!/usr/bin/env python3
"""PreToolUse hook: keep production read-only from the agent's shell.

Claude Code passes the tool call as JSON on stdin. For a Bash call (or a PowerShell call, Claude Code's shell tool
on Windows without Git Bash), this blocks commands that would change a cluster or print a credential, by exiting 2
with the reason on stderr and printing the same reason as a PreToolUse deny on stdout, which Claude Code reads
alongside the exit 2 (it shows the reason to the agent and skips the call). Each command is also judged as it runs
once PowerShell's and Windows' spellings are taken off (a quoted or `& 'kubectl'` program name, `Kubectl.EXE`,
backtick escapes, a variable the call sets), in any letter case. A call it cannot read (not UTF-8, JSON or an object,
no command text, a closed stdin, an error in the hook) is blocked. Everything else is allowed with exit 0. It reads
only the command text, runs nothing and writes nothing.

The MCP servers are read-only on their own (`--read-only`, viewer roles); this covers the shell, where an
environment may also have `kubectl`, `helm` or `gcloud`.
"""

from __future__ import annotations

import json
import re
import sys

SHELL_TOOLS = {"Bash", "PowerShell"}  # PowerShell: Claude Code's shell tool on Windows without Git Bash

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
    """The whole call with each line ending made a `;`, then every single command in it, each also as the program
    would run it. Each is judged, so a newline, `;`, `&&`, `||`, `|` or `&` cannot hide a command from a pattern, and
    neither can PowerShell's or Windows' spellings of it (see _plain)."""
    out = []
    for text in dict.fromkeys([command, _plain(command)]):
        joined = re.sub(r"\s*\r?\n\s*", " ; ", re.sub(r"\\\r?\n", " ", text))
        out += [joined] + [c for c in re.split(r"\s*(?:;|&&|\|\||\||(?<![<>])&(?![>&]))\s*", joined) if c]
    return list(dict.fromkeys(out))


def _plain(command: str) -> str:
    """The call with the spellings that hide a program from a pattern taken off: PowerShell's backtick escapes and
    line continuations, its call operator `& 'kubectl'`, quotes around words, a `.exe` suffix, the commas of an
    `-ArgumentList`, and variables the call sets itself (`$c='delete'`, `c=delete`) put back where they are used.
    `iex`, `Invoke-Expression`, `Start-Process` and `cmd /c` need no unwrapping: the patterns search the whole text."""
    text = re.sub(r"`\r?\n", " ", command)
    text = re.sub(r"`(.)", r"\1", text)
    names = {}
    for m in re.finditer(r"(?:^|[\s;&|(])\$?\{?([A-Za-z_]\w*)\}?\s*=(?!=)\s*(['\"]?)([^'\";&|\r\n]*)\2", text):
        names[m.group(1).lower()] = m.group(3).strip()
    if names:
        text = re.sub(r"\$\{?([A-Za-z_]\w*)\}?", lambda m: names.get(m.group(1).lower(), m.group(0)), text)
    text = re.sub(r"(^|[;&|(\n]\s*)&\s*", r"\1", text)  # the call operator: & 'kubectl' delete
    text = re.sub(r"['\"]", "", text)
    text = re.sub(r"(?i)\.exe\b", "", text)
    return text.replace(",", " ")


def _read_event() -> tuple[object, str | None]:
    """(event, problem): the event read as UTF-8 bytes on every platform (on Windows sys.stdin decodes with the
    console code page). problem names why the input cannot be checked (not UTF-8, not JSON): the caller fails closed."""
    try:
        text = sys.stdin.buffer.read().decode("utf-8-sig")
    except UnicodeDecodeError:
        return None, "the tool call is not valid UTF-8, so it cannot be checked"
    except (OSError, AttributeError, ValueError):  # AttributeError: no stdin at all; ValueError: it is closed
        return None, "the tool call could not be read, so it cannot be checked"
    try:
        event = json.loads(text)
    except ValueError:
        return None, "the tool call is not valid JSON, so it cannot be checked"
    if not isinstance(event, dict):
        return None, "the tool call is not a JSON object, so it cannot be checked"
    if event.get("tool_name") in SHELL_TOOLS and not (isinstance(event.get("tool_input"), dict) and
                                                      isinstance(event["tool_input"].get("command"), str)):
        return None, "the shell call carries no command text, so it cannot be checked"
    return event, None


def _block(message: str) -> int:
    # Exit 2 with the reason on stderr is the verdict: Claude Code blocks the call and shows the agent the reason.
    # PowerShell's -Command turns a native exit 2 into 1, so the installer's Windows hook commands end in
    # `exit $LASTEXITCODE` to keep the 2. The same reason also goes to stdout as a PreToolUse deny, which Claude Code
    # reads alongside exit 2. Where a shell turns the 2 into 1 anyway, valid JSON decides the call, except on Windows
    # without Git Bash, where any code but 0 or 2 is a hook failure. If something else writes to stdout (a shell
    # profile) the JSON is not read, and the non-zero exit still blocks.
    deny = {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                   "permissionDecisionReason": message}}
    try:
        sys.stdout.flush()
        sys.stdout.buffer.write(json.dumps(deny, ensure_ascii=True).encode("ascii") + b"\n")
        sys.stdout.buffer.flush()
    except (OSError, ValueError):
        pass  # the exit code below still blocks
    sys.stderr.flush()
    sys.stderr.buffer.write((message + "\n").encode("utf-8"))
    sys.stderr.buffer.flush()
    return 2


def main() -> int:
    try:
        return _main()
    except Exception as e:  # noqa: BLE001 - a hook that crashes exits 1, which lets the call through: fail closed
        return _block(f"blocked by the team harness: the hook failed ({type(e).__name__}), "
                      "so the call cannot be checked. Diagnose read-only and propose the change in a PR.")


def _main() -> int:
    event, problem = _read_event()
    if problem:
        return _block(f"blocked by the team harness: {problem}. Diagnose read-only and propose the change in a PR.")
    if not isinstance(event, dict) or event.get("tool_name") not in SHELL_TOOLS:
        return 0
    for command in _commands(str((event.get("tool_input") or {}).get("command") or "")):
        for pattern, why in BLOCKED:
            if re.search(pattern, command, re.IGNORECASE):  # Windows finds Kubectl.EXE as kubectl
                return _block(f"blocked by the team harness: {why}. Diagnose read-only and propose the change in a PR.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
