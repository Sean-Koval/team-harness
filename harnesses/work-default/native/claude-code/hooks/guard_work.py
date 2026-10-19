#!/usr/bin/env python3
"""PreToolUse hook for the work harness: shared systems stay read-only, and the deploy checkout stays untouched.

Claude Code passes the tool call as JSON on stdin. This exits 2 with the reason on stderr (Claude Code shows it to the
agent and skips the call) for:

- Terraform that changes real infrastructure or state (`apply`, `destroy`, `import`, state edits, an `init` that
  isn't `-backend=false`, and `plan`, which reads real state);
- a database client or URL aimed at anything but the sandbox's own database service (localhost, 127.0.0.1, `db`);
- cluster changes (`kubectl`, `helm`) and credential dumps, as the team-default guard does;
- any edit under /workspace/deploy, the trigger-deployment checkout hangar's deploy step owns.

Everything else is allowed with exit 0. It reads only the tool call, runs nothing and writes nothing.
"""

from __future__ import annotations

import json
import re
import sys

DEPLOY = "/workspace/deploy"
LOCAL_DB = r"(?:localhost|127\.0\.0\.1|db)(?![\w.-])"

BASH = [
    (r"\bterraform\b(?:\s+-\S+)*\s+(apply|destroy|import|taint|untaint|force-unlock|refresh)\b",
     "terraform may only fmt, init -backend=false and validate here; SRE applies after the PR merges"),
    (r"\bterraform\b(?:\s+-\S+)*\s+state\s+(rm|mv|push|replace-provider)\b", "terraform state is never edited here"),
    (r"\bterraform\b(?:\s+-\S+)*\s+init\b(?![^;&|]*-backend=false)", "terraform init needs -backend=false here"),
    (r"\bterraform\b(?:\s+-\S+)*\s+plan\b",
     "terraform plan reads real state: validate here, and leave plan to the infra repo's CI"),
    (rf"\b(psql|pg_dump|pg_restore|mysql|mysqldump|sqlcmd)\b[^;&|]*\s(?:-h\s*|--host[= ])(?!{LOCAL_DB})\S+",
     "database clients may only reach the sandbox's own database (localhost or the service name)"),
    (rf"\b(postgres(?:ql)?|mysql|sqlserver)://[^\s/@]*@(?!{LOCAL_DB})[^\s/:]+",
     "connection URLs may only point at the sandbox's own database"),
    (r"\bkubectl\b(?:\s+-\S+(?:\s+\S+)?)*\s+(apply|create|replace|patch|edit|delete|scale|autoscale|annotate|label|"
     r"taint|cordon|uncordon|drain|set|rollout\s+(restart|undo|pause|resume)|exec|cp|port-forward|debug)\b",
     "kubectl may only read"),
    (r"\bhelm\s+(install|upgrade|uninstall|delete|rollback)\b", "helm may only read"),
    (r"\bgcloud\s+auth\s+(print-access-token|print-identity-token)\b", "never print a credential"),
    (r"(^|[;&|]\s*)(printenv|env)\s*($|[;&|])", "don't dump the environment: it holds credentials"),
    (r"\bcat\b.*(\.kube/config|kubeconfig|credentials\.json|\.git-credentials|\.pgpass)", "never print a credential file"),
    (rf"(>>?\s*|\btee\s+(-a\s+)?|\bsed\s+-i\S*\s+.*|\b(mv|cp|rm|touch|mkdir|ln)\b[^;&|]*\s){re.escape(DEPLOY)}(/|\s|$)",
     "the deploy checkout is read-only: hangar's deploy step bumps it after the other PRs merge"),
    (rf"\bgit\s+-C\s+{re.escape(DEPLOY)}\b\s+(add|commit|push|rm|mv|checkout|reset|stash|apply|am)\b",
     "the deploy checkout is read-only"),
    (rf"\bcd\s+{re.escape(DEPLOY)}\b[^;]*[;&|]+\s*.*\b(git\s+(add|commit|push)|sed\s+-i|>\s*\S)",
     "the deploy checkout is read-only"),
]
EDIT_TOOLS = {"Edit", "MultiEdit", "Write", "NotebookEdit"}


def why(event: dict) -> str | None:
    tool = event.get("tool_name")
    args = event.get("tool_input") or {}
    if tool in EDIT_TOOLS:
        path = str(args.get("file_path") or args.get("notebook_path") or "")
        if path == DEPLOY or path.startswith(DEPLOY + "/"):
            return "the deploy checkout is read-only: hangar's deploy step bumps it after the other PRs merge"
        return None
    if tool == "Bash":
        command = str(args.get("command") or "")
        for pattern, reason in BASH:
            if re.search(pattern, command):
                return reason
    return None


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except (ValueError, OSError):
        return 0  # not ours to judge; never wedge a session on a malformed event
    reason = why(event) if isinstance(event, dict) else None
    if reason:
        print(f"blocked by the work harness: {reason}. Propose the change in the PR instead.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
