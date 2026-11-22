"""Prepare one synthetic field ticket or verify a delivery in its disposable checkout."""

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys


def load_cases():
    cases = {}
    for name in ("a.json", "b.json", "c.json", "d.json"):
        for case in json.loads(Path(__file__).with_name(name).read_text()):
            identifier = case["id"]
            if identifier in cases:
                raise ValueError(f"Duplicate case ID: {identifier}")
            cases[identifier] = case
    return cases


def prepare(case, destination):
    destination.mkdir(parents=True, exist_ok=False)
    try:
        files = {**case["files"], "TICKET.md": case["ticket"] + "\n"}
        for name, content in files.items():
            relative = Path(name)
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError(f"Invalid case path: {relative}")
            path = destination / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
    except Exception:
        shutil.rmtree(destination)
        raise
    print(f"Give the engineer only {destination} and its TICKET.md.")


def verify(case, destination):
    if case["mode"] != "edit":
        print("Use the case rubric and command trace to review this read-only ticket.")
        return 2
    ticket = destination / "TICKET.md"
    if not ticket.is_file() or ticket.read_text(encoding="utf-8") != case["ticket"] + "\n":
        raise ValueError("Use the case ID and the matching prepared checkout.")
    ordinary_args = {"A": ["test_smoke.py"], "B": ["-m", "unittest", "discover"], "C": ["check.py"], "D": ["check.py"]}
    commands = [
        ("ordinary repo check", ordinary_args[case["id"][0]]),
        ("private behavior check", ["-c", case["check"]]),
    ]
    passed = True
    for label, args in commands:
        process = subprocess.run([sys.executable, *args], cwd=destination, check=False)
        print(f"{label}: exit {process.returncode}", flush=True)
        passed = passed and process.returncode == 0
    return 0 if passed else 1


def main():
    cases = load_cases()
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="operation", required=True)
    commands.add_parser("list", help="Show case IDs and domains to the study operator.")
    for operation in ("prepare", "verify"):
        command = commands.add_parser(operation)
        command.add_argument("case", choices=cases)
        command.add_argument("checkout", type=Path)
    args = parser.parse_args()
    if args.operation == "list":
        for case in cases.values():
            print(case["id"], case["family"], sep="\t")
        return 0
    if args.operation == "prepare":
        prepare(cases[args.case], args.checkout)
        return 0
    return verify(cases[args.case], args.checkout)


if __name__ == "__main__":
    sys.exit(main())
