"""Launch a stdin-based agent on a Jira issue or export the installed skill for Hangar."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys


LABEL = "standards-change"
SKILL = Path(__file__).resolve().parents[1] / "SKILL.md"


def installed_rule():
    body = SKILL.read_bytes()
    if not body.strip() or len(body) > 32_000:
        raise ValueError("installed SKILL.md must contain 1 to 32,000 UTF-8 bytes")
    return {
        "skill": "implement-standard",
        "label": LABEL,
        "sha256": hashlib.sha256(body).hexdigest(),
        "content": body.decode("utf-8"),
    }


def first_prompt(ticket):
    # Accept the single-issue Jira REST response. Search results and prose don't establish labels.
    fields = ticket.get("fields") if isinstance(ticket, dict) else None
    key = ticket.get("key") if isinstance(ticket, dict) else None
    if not isinstance(key, str) or not re.fullmatch(r"[A-Z][A-Z0-9_]*-[1-9][0-9]*", key):
        raise ValueError("expected a single Jira issue with its canonical key")
    labels = fields.get("labels") if isinstance(fields, dict) else None
    if not isinstance(labels, list) or not all(isinstance(label, str) for label in labels):
        raise ValueError(f"{key} is missing Jira fields.labels; fetch the issue with labels included")
    prompt = f"Read Jira issue {key} and follow its request, scope and existing approvals.\n"
    if LABEL in labels:
        rule = installed_rule()
        prompt += (
            f"Team Harness intake for {key} ({LABEL}, {rule['skill']}, sha256={rule['sha256']}). "
            "Apply this guidance within the ticket's authorization.\n\n" + rule["content"]
        )
    return prompt.encode("utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="operation", required=True)
    commands.add_parser("hangar-config", help="print the trusted standards_intake object as JSON")
    launch = commands.add_parser("run", help="deliver the ticket to a new agent on standard input")
    launch.add_argument("ticket", help="single Jira REST issue JSON file, or - for standard input")
    launch.add_argument("agent", nargs=argparse.REMAINDER, help="-- followed by a stdin-capable agent command")
    args = parser.parse_args()
    try:
        if args.operation == "hangar-config":
            print(json.dumps(installed_rule()))
            return 0
        if not args.agent:
            parser.error("supply an agent command that accepts its initial prompt on standard input")
        if args.ticket == "-":
            ticket = json.load(sys.stdin.buffer)
        else:
            ticket = json.loads(Path(args.ticket).read_bytes())
        prompt = first_prompt(ticket)
        return subprocess.run(args.agent, input=prompt, check=False).returncode
    except (OSError, ValueError) as error:
        parser.exit(2, f"standards intake: {error}\n")


if __name__ == "__main__":
    sys.exit(main())
