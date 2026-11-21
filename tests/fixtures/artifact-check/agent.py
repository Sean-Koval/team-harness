"""A fake agent command for tests/test_artifact_check.py: reads a task on stdin and answers with its `reply` and, when
the task has one, its `usage` (no model is called). `exit` sets the exit code after the answer; `garbage` prints no
JSON."""

import json
import os
import sys

task = json.load(sys.stdin)
print(f"model={os.environ['ARTIFACT_CHECK_MODEL']} left={os.environ['ARTIFACT_CHECK_BUDGET_USD']}")
if task.get("garbage"):
    print("not json")
    sys.exit(0)
reply = {"output": task.get("reply", "")}
if "usage" in task:
    reply["usage"] = task["usage"]
print(json.dumps(reply))
sys.exit(task.get("exit") or 0)
