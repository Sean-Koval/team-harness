"""A fake eval runner for tests/test_artifact_check.py. A task names its cost and whether it passes; the runner
stops itself at the budget it is given (ARTIFACT_CHECK_BUDGET_USD), as a real runner should."""

import json
import os
import sys

import yaml

with open(sys.argv[-1], encoding="utf-8") as fh:
    task = yaml.safe_load(fh)
left = float(os.environ["ARTIFACT_CHECK_BUDGET_USD"])
assert os.environ["ARTIFACT_CHECK_MODEL"]
cost = float(task["cost"])
stopped = cost > left
print("working on", task["prompt"])
print(json.dumps({"passed": bool(task["passes"]) and not stopped, "tokens": int(task.get("tokens", 100)),
                  "cost_usd": min(cost, left), "detail": "stopped at the budget" if stopped else ""}))
