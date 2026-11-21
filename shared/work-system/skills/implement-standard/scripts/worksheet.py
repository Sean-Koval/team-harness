"""Print a Markdown worksheet for planning, building, or reviewing a standard."""
import argparse


FIELDS = (
    "Primary recommendation, evidence, and what would change the decision",
    "Source, scope, and assumptions",
    "Observable promise and counterexample",
    "Owning code, supported path, and affected callers",
    "Top-down decisions: code, checks, behavior, guidance (change, reuse, or skip and why)",
    "Executable check, failing case, and repair message",
    "Behavioral evidence and plausible false pass",
    "Guidance, exceptions, and who decides",
    "Verification command, CI job, and evidence",
)

EVIDENCE_PROMPTS = {
    "plan": "List planned checks and expected results. Record any open decisions.",
    "build": "Record observed local results and hosted CI results. Mark checks still pending.",
    "review": "Record findings with file or evidence links and the smallest repair. Flag missing evidence.",
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=EVIDENCE_PROMPTS)
    args = parser.parse_args()

    print(f"# Standard worksheet · {args.mode.capitalize()}\n")
    print(f"{EVIDENCE_PROMPTS[args.mode]}\n")
    for field in FIELDS:
        print(f"- **{field}** —")


if __name__ == "__main__":
    main()
