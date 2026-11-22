import json
from pathlib import Path
import subprocess
import sys

import pytest


FIELD = Path(__file__).resolve().parents[1] / "evals/implement-standard/field"
FILING = FIELD / "filing.py"


def test_export_only_discloses_masked_refs_and_briefs():
    result = subprocess.run([sys.executable, FILING, "export"], capture_output=True, text=True, check=True)
    briefs = json.loads(result.stdout)
    assert len(briefs) == len({item["ref"] for item in briefs}) == 24
    assert all(set(item) == {"ref", "request"} for item in briefs)


@pytest.fixture
def predictions():
    gold = json.loads((FIELD / "filing/gold.json").read_text(encoding="utf-8"))
    return [{"ref": item["ref"], "labels": ["standards-change"] if item["target"] == "mark" else []}
            for item in gold]


def score(tmp_path, predictions):
    candidate = tmp_path / "predictions.json"
    candidate.write_text(json.dumps(predictions), encoding="utf-8")
    return subprocess.run([sys.executable, FILING, "score", candidate], capture_output=True, text=True)


def test_score_reports_miss_false_alarm_and_ambiguous_separately(tmp_path, predictions):
    by_ref = {item["ref"]: item for item in predictions}
    by_ref["HX-746"]["labels"] = ["standards-change-preview"]
    by_ref["HX-731"]["labels"] = ["standards-change"]
    by_ref["HX-718"]["labels"] = ["standards-change"]
    result = score(tmp_path, predictions)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["FN"] == report["FP"] == 1
    assert report["TP"] + report["TN"] + report["FN"] + report["FP"] + len(report["ambiguous"]["marked"]) + (
        len(report["ambiguous"]["unmarked"])) == 24
    assert report["false_negatives"] == ["HX-746"]
    assert report["false_positives"] == ["HX-731"]
    assert report["ambiguous"]["marked"] == ["HX-718"]


@pytest.mark.parametrize(("fault", "message"), [
    ("missing", "missing refs"), ("extra", "extra refs"),
    ("duplicate", "duplicate ref"), ("labels", "labels must be an array of strings"),
])
def test_score_rejects_invalid_submissions(tmp_path, predictions, fault, message):
    if fault == "missing":
        predictions.pop()
    elif fault == "extra":
        predictions.append({"ref": "HX-999", "labels": []})
    elif fault == "duplicate":
        predictions.append(predictions[0])
    else:
        predictions[0]["labels"] = "standards-change"
    result = score(tmp_path, predictions)
    assert result.returncode == 2
    assert message in result.stderr
    assert not result.stdout
