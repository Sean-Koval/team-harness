#!/usr/bin/env python3
"""Render a scaffold-artifact template into a new directory (standard library only).

    python scaffold.py mcp-server <destination> --name weather-tools --ticket PROJ-12 --description "Weather lookups"

Copies templates/<kind>/ into <destination> (which must be missing or empty), replacing `@@project@@`,
`@@package@@`, `@@ticket@@` and `@@description@@` in file and directory names and in text files. Fails, and leaves
nothing behind, when an argument is malformed or a token is left over.
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
KINDS = sorted(p.name for p in (HERE / "templates").iterdir() if p.is_dir())
TOKEN = re.compile(r"@@[a-z_]+@@")
NAME = re.compile(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*")
TICKET = re.compile(r"[A-Z][A-Z0-9]{1,9}-[0-9]+")


def values(name: str, ticket: str, description: str) -> dict[str, str]:
    if not NAME.fullmatch(name):
        raise ValueError(f"--name {name!r} must be lowercase words joined by hyphens, like 'weather-tools'")
    if not TICKET.fullmatch(ticket):
        raise ValueError(f"--ticket {ticket!r} must be a ticket key, like 'PROJ-12'")
    description = " ".join(description.split())
    if not description or '"' in description or "\\" in description or "@@" in description:
        raise ValueError("--description must be one non-empty line without quotes, backslashes or '@@'")
    return {"@@project@@": name, "@@package@@": name.replace("-", "_"), "@@ticket@@": ticket,
            "@@description@@": description}


def fill(text: str, vals: dict[str, str]) -> str:
    for token, value in vals.items():
        text = text.replace(token, value)
    return text


def render(kind: str, dest: Path, vals: dict[str, str]) -> list[Path]:
    src = HERE / "templates" / kind
    if not src.is_dir():
        raise ValueError(f"no template {kind!r} (have: {', '.join(KINDS)})")
    if dest.exists() and (not dest.is_dir() or any(dest.iterdir())):
        raise ValueError(f"{dest} is not an empty directory; scaffold into a new one")
    created = not dest.exists()
    written: list[Path] = []
    try:
        for f in sorted(p for p in src.rglob("*") if p.is_file() and "__pycache__" not in p.parts):
            out = dest / fill(f.relative_to(src).as_posix(), vals)
            out.parent.mkdir(parents=True, exist_ok=True)
            data = f.read_bytes()
            try:
                text = fill(data.decode("utf-8"), vals)
            except UnicodeDecodeError:
                out.write_bytes(data)
            else:
                out.write_bytes(text.encode("utf-8"))
            written.append(out)
        left = [f"{p.relative_to(dest)}: {m}" for p in written
                for m in TOKEN.findall(p.relative_to(dest).as_posix() + p.read_text("utf-8", errors="ignore"))]
        if left:
            raise ValueError("tokens left unfilled: " + "; ".join(left[:5]))
    except BaseException:
        if created:
            shutil.rmtree(dest, ignore_errors=True)
        else:
            for p in written:
                p.unlink(missing_ok=True)
        raise
    return written


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("kind", choices=KINDS)
    ap.add_argument("dest", type=Path)
    ap.add_argument("--name", required=True)
    ap.add_argument("--ticket", required=True)
    ap.add_argument("--description", required=True)
    a = ap.parse_args(argv)
    try:
        written = render(a.kind, a.dest, values(a.name, a.ticket, a.description))
    except (ValueError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(f"rendered {len(written)} files into {a.dest}; next, run its verify command (AGENTS.md)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
