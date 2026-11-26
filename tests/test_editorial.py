"""Apply the suite's editorial limits to the first-loop guide.

The limits and prose-counting conventions follow Hangar's tests/test_editorial.py
(Sean-Koval/hangar@138c04d, Apache-2.0). This check has its own Markdown scanner
and covers only the prose constructs used in the first-loop guide.
"""

import re
from pathlib import Path


GUIDE = Path(__file__).resolve().parents[1] / "docs" / "first-loop.md"
PAGE_LIMIT = 700
PARAGRAPH_LIMIT = 60
SENTENCE_LIMIT = 25

FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
HEADING = re.compile(r"^ {0,3}#{1,6}(?:\s|$)")
LIST_ITEM = re.compile(r"^\s*(?:[-+*]|\d+[.)])\s+")
SENTENCE_END = re.compile(r"(?<!\be\.g)(?<!\bi\.e)(?<=[.!?])\s+(?=[A-Za-z\"'(])|;\s+")


def prose_blocks(markdown: str):
    # A blank line, heading, fence or new list item ends the current paragraph.
    start = 0
    lines = []
    fence = None
    for number, line in enumerate(markdown.splitlines() + [""], start=1):
        marker = FENCE.match(line)
        if fence:
            if marker and marker[1].startswith(fence) and not line[marker.end():].strip():
                fence = None
            continue
        item = LIST_ITEM.match(line)
        boundary = not line.strip() or marker or HEADING.match(line)
        if lines and (boundary or item):
            yield start, " ".join(lines)
            lines = []
        if marker:
            fence = marker[1]
        if not boundary:
            if not lines:
                start = number
            lines.append(line[item.end():].strip() if item else line.strip())


def editorial_violations(markdown: str) -> list[str]:
    problems = []
    total = 0
    for line, block in prose_blocks(markdown):
        block = re.sub(r"`[^`]+`", "code", block)
        block = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", block)
        size = len(block.split())
        total += size
        if size > PARAGRAPH_LIMIT:
            problems.append(f"line {line}: {size}-word paragraph exceeds {PARAGRAPH_LIMIT} words")
        for sentence in SENTENCE_END.split(block):
            size = len(sentence.split())
            if size > SENTENCE_LIMIT:
                problems.append(f"line {line}: {size}-word sentence exceeds {SENTENCE_LIMIT} words: {sentence[:70]}")
    if total > PAGE_LIMIT:
        problems.append(f"{total} words of prose exceeds the {PAGE_LIMIT}-word page limit")
    return problems


def test_first_loop_guide_follows_editorial_limits():
    violations = editorial_violations(GUIDE.read_text(encoding="utf-8"))
    assert not violations, "docs/first-loop.md:\n" + "\n".join(violations)
