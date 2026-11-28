"""Export blinded filing briefs and score predictions after filing."""

import argparse
import json
from pathlib import Path


DATA = Path(__file__).with_suffix("")
LABEL = "standards-change"
OUTCOME = {(True, True): "TP", (True, False): "FN", (False, True): "FP", (False, False): "TN"}


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def score(predictions, gold):
    if not isinstance(predictions, list):
        raise ValueError("predictions must be a JSON array")
    marked = {}
    for index, item in enumerate(predictions, start=1):
        if not isinstance(item, dict) or not isinstance(ref := item.get("ref"), str) or not ref:
            raise ValueError(f"prediction {index} must have a nonempty string ref")
        if ref in marked:
            raise ValueError(f"duplicate ref: {ref}")
        labels = item.get("labels")
        if not isinstance(labels, list) or not all(isinstance(label, str) for label in labels):
            raise ValueError(f"{ref}: labels must be an array of strings")
        marked[ref] = LABEL in labels

    expected = {item["ref"]: item["target"] for item in gold}
    missing, extra = expected.keys() - marked.keys(), marked.keys() - expected.keys()
    errors = []
    if missing:
        errors.append(f"missing refs: {', '.join(sorted(missing))}")
    if extra:
        errors.append(f"extra refs: {', '.join(sorted(extra))}")
    if errors:
        raise ValueError("; ".join(errors))

    outcomes = {outcome: [] for outcome in OUTCOME.values()}
    ambiguous = {"marked": [], "unmarked": []}
    for ref, target in expected.items():
        if target == "ambiguous":
            ambiguous["marked" if marked[ref] else "unmarked"].append(ref)
        else:
            outcomes[OUTCOME[target == "mark", marked[ref]]].append(ref)
    return {
        **{outcome: len(refs) for outcome, refs in outcomes.items()},
        "false_negatives": outcomes["FN"],
        "false_positives": outcomes["FP"],
        "ambiguous": ambiguous,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="operation", required=True)
    commands.add_parser("export", help="Print only the masked references and requests.")
    scoring = commands.add_parser("score", help="Compare a frozen submission with the expected filing decisions.")
    scoring.add_argument("predictions", type=Path)
    args = parser.parse_args()
    try:
        if args.operation == "export":
            result = [{field: item[field] for field in ("ref", "request")}
                      for item in read_json(DATA / "briefs.json")]
        else:
            result = score(read_json(args.predictions), read_json(DATA / "gold.json"))
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, indent=2, ensure_ascii=True))


if __name__ == "__main__":
    main()
