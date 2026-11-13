#!/usr/bin/env python3
"""SessionEnd hook: remind the user to run extract-records when the session produced decisions.

Claude Code passes the event as JSON on stdin, with `transcript_path`. This reads the end of the transcript and, when
the conversation's text states a decision ("we decided", "Decision:", "let's go with" and the like) and the session
did not already run `extract-records`, prints a reminder on stderr and exits 2: on SessionEnd that shows stderr to
the user and blocks nothing. Any other case, an unreadable transcript included, exits 0 silently.

It is a convenience, not a gate: a reminder that does not fire loses nothing, because a decision is settled only when
its record merges. Standard library only, so it runs natively on Windows too. SessionEnd hooks get a short budget, so
it reads at most the last TAIL_BYTES of the transcript.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

TAIL_BYTES = 2_000_000
DECIDED = re.compile(
    r"\b(?:we|i)(?:'ve| have)? decided\b|\bdecision:|\bdecided to\b|\blet'?s go with\b|\bwe'?ll go with\b"
    r"|\bgoing with option\b|\bagreed (?:to|that|on)\b|\bwe chose\b|\bthe choice is\b",
    re.IGNORECASE,
)
# Injected guidance (CLAUDE.md, skill listings) arrives inside these tags; it is not the conversation.
INJECTED = re.compile(r"<system-reminder>.*?</system-reminder>", re.DOTALL)
SKILL = "extract-records"
REMINDER = (
    "This session stated decisions. A decision is settled only when its record merges: capture the session as a "
    "Source in the knowledge repository's inbox and run the extract-records skill, which proposes the records by "
    "pull request."
)


def _items(content: object) -> list:
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    return [x for x in content if isinstance(x, dict)] if isinstance(content, list) else []


def _ran_skill(item: dict) -> bool:
    """A tool call that runs the extract-records skill (the Skill tool, or a slash command naming it)."""
    if item.get("type") != "tool_use":
        return False
    inp = item.get("input") if isinstance(item.get("input"), dict) else {}
    return str(inp.get("skill") or inp.get("command") or "").lstrip("/").split(":")[-1].strip() == SKILL


def scan(lines: list[str]) -> tuple[bool, bool]:
    """(the conversation states a decision, the session ran extract-records)."""
    decided = extracted = False
    for line in lines:
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if not isinstance(entry, dict) or entry.get("type") not in ("user", "assistant"):
            continue
        message = entry.get("message")
        content = message.get("content") if isinstance(message, dict) else message
        for item in _items(content):
            extracted = extracted or _ran_skill(item)
            if item.get("type") == "text" and isinstance(item.get("text"), str):
                text = INJECTED.sub("", item["text"])
                decided = decided or bool(DECIDED.search(text))
    return decided, extracted


def tail(path: Path) -> list[str]:
    with path.open("rb") as f:
        f.seek(0, 2)
        size = f.tell()
        f.seek(max(0, size - TAIL_BYTES))
        data = f.read()
    lines = data.decode("utf-8", errors="replace").splitlines()
    return lines[1:] if size > TAIL_BYTES else lines  # the first line may be cut


def main() -> int:
    try:
        event = json.load(sys.stdin)
        path = Path(str(event.get("transcript_path") or ""))
        if not path.is_file():
            return 0
        decided, extracted = scan(tail(path))
    except Exception:  # a reminder is never worth failing the session's end
        return 0
    if decided and not extracted:
        print(REMINDER, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
