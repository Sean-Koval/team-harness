"""Print a Markdown worksheet for planning, building, or reviewing a standard."""
import argparse


FIELDS = (
    "Primary recommendation, evidence, and what would change the decision",
    "Source, scope, assumptions, and governing ADR or Decision",
    "Observable promise, counterexample, legitimate exception, and acceptance criteria",
    "Owning code, supported path, and affected callers",
    "Top-down decisions: code, checks, behavior, guidance (change, reuse, or skip and why)",
    "Realistic violation and supported case, with expected results and evidence",
    "Executable check and repair message, or behavioral check that rules out a false pass",
    "Ordinary verification command, CI job and run or revision",
    "Current ticket or PR, milestone impact, and linked evidence",
    "Blocked or pending work, Decision or dependency, owner, and next step",
)

EVIDENCE_PROMPTS = {
    "plan": "List planned checks and expected results. Record any open decisions.",
    "build": "Distinguish observed local results and hosted CI results from planned or pending checks.",
    "review": "Record findings with file or evidence links and the smallest repair. Flag planned or missing evidence.",
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
