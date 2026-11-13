#!/usr/bin/env python3
"""Changelog fragments: one file per PR in `changes/`, folded into CHANGELOG.md at release (KAN-481).

A PR never edits CHANGELOG.md, so two PRs can't conflict on it. It adds `changes/<KEY>.md` (KEY is its ticket key,
such as `KAN-481`, or a short slug without one), holding its entry as one or more `- ` bullets. The section is
Changed unless the name says otherwise: `changes/<KEY>.<section>.md`, where section is added, changed, deprecated,
removed, fixed or security (Keep a Changelog's). `changes/README.md` is not a fragment.

    python scripts/collect_changes.py           # check the fragments and print the entries they make
    python scripts/collect_changes.py --write   # at release: fold them into CHANGELOG.md's Unreleased section, delete them
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SECTIONS = ("added", "changed", "deprecated", "removed", "fixed", "security")
NAME = re.compile(rf"^(?P<key>[A-Za-z0-9][A-Za-z0-9-]*)(?:\.(?P<section>{'|'.join(SECTIONS)}))?\.md$")
UNRELEASED = "## Unreleased"


def fragments(root: Path) -> list[Path]:
    d = root / "changes"
    return sorted(p for p in d.iterdir() if p.is_file() and p.name not in {"README.md", ".gitkeep"}) \
        if d.is_dir() else []


def problems(root: Path) -> list[str]:
    out = []
    for p in fragments(root):
        if not NAME.match(p.name):
            out.append(f"changes/{p.name}: name it changes/<KEY>.md or changes/<KEY>.<section>.md, section one of "
                       f"{', '.join(SECTIONS)}")
            continue
        text = p.read_text(encoding="utf-8").strip()
        if not text.startswith("- "):
            out.append(f"changes/{p.name}: write the entry as one or more '- ' bullets")
        if re.search(r"^#", text, re.MULTILINE):
            out.append(f"changes/{p.name}: no headings; the section comes from the file name")
    return out


def entries(root: Path) -> dict[str, list[str]]:
    """Section title -> bullets (each a block of lines), in fragment-name order."""
    out: dict[str, list[str]] = {}
    for p in fragments(root):
        m = NAME.match(p.name)
        assert m, p
        title = (m.group("section") or "changed").capitalize()
        out.setdefault(title, []).append(p.read_text(encoding="utf-8").strip())
    return out


def fold(changelog: str, new: dict[str, list[str]]) -> str:
    """CHANGELOG.md text with `new` added at the top of each `### <Section>` under `## Unreleased` (a missing
    Unreleased section or subsection is created)."""
    lines = changelog.splitlines()
    if UNRELEASED not in lines:
        first = next((i for i, x in enumerate(lines) if x.startswith("## ")), len(lines))
        lines[first:first] = [UNRELEASED, ""]
    start = lines.index(UNRELEASED)
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    for title in sorted(new, key=lambda t: SECTIONS.index(t.lower())):
        block = "\n".join(new[title]).splitlines()
        head = next((i for i in range(start, end) if lines[i] == f"### {title}"), None)
        if head is None:
            ins = [f"### {title}", "", *block, ""]
            if lines[end - 1] != "":
                ins.insert(0, "")
            at = end
        else:
            at = head + 1
            while at < end and lines[at] == "":
                at += 1
            ins = block if at < end and lines[at].startswith("- ") else [*block, ""]  # join the list, or stand alone
        lines[at:at] = ins
        end += len(ins)
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--write", action="store_true", help="fold the fragments into CHANGELOG.md and delete them")
    ap.add_argument("--root", type=Path, default=ROOT)
    a = ap.parse_args(argv)
    bad = problems(a.root)
    for p in bad:
        print(f"error: {p}", file=sys.stderr)
    if bad:
        return 1
    new = entries(a.root)
    if not a.write:
        for title, items in new.items():
            print(f"### {title}\n\n" + "\n".join(items) + "\n")
        return 0
    changelog = a.root / "CHANGELOG.md"
    changelog.write_text(fold(changelog.read_text(encoding="utf-8"), new), encoding="utf-8")
    for p in fragments(a.root):
        p.unlink()
    print(f"folded {sum(len(v) for v in new.values())} entries into CHANGELOG.md", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
