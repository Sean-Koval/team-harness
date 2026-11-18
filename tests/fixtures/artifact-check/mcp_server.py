"""A stdlib MCP server over stdio for tests/test_artifact_check.py. argv[1] picks its behaviour:
ok, broken-schema, no-description, duplicate, same-cursor, protocol-error, crash-on-call, hang-on-call (blocks until
its input closes) and stuck-on-call (ignores its input closing, and leaves a child running whose pid it writes to
$ARTIFACT_FIXTURE_PIDFILE)."""

import json
import os
import subprocess
import sys
import time

MODE = sys.argv[1] if len(sys.argv) > 1 else "ok"
ECHO = {"name": "echo", "description": "Echo the text back.",
        "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}}
BROKEN = {"name": "broken", "description": "Its schema's type is not a JSON Schema type.",
          "inputSchema": {"type": "object", "properties": {"n": {"type": "integr"}}}}


def tools():
    if MODE == "broken-schema":
        return [ECHO, BROKEN]
    if MODE == "no-description":
        return [{**ECHO, "description": ""}]
    if MODE == "duplicate":
        return [ECHO, ECHO]
    return [ECHO]


def answer(req):
    method, params = req["method"], req.get("params") or {}
    if method == "initialize":
        return {"protocolVersion": params["protocolVersion"], "capabilities": {"tools": {}},
                "serverInfo": {"name": "fixture", "version": "1"}}
    if method == "tools/list":
        return {"tools": tools(), **({"nextCursor": "same"} if MODE == "same-cursor" else {})}
    if method == "tools/call":
        if MODE == "crash-on-call":
            sys.exit(3)
        if MODE == "hang-on-call":
            sys.stdin.read()
        if MODE == "stuck-on-call":
            time.sleep(1e6)
        if MODE == "protocol-error":
            raise KeyError("tools/call")
        text = params["arguments"].get("text", "")
        if not text:
            return {"content": [{"type": "text", "text": "text must not be empty"}], "isError": True}
        return {"content": [{"type": "text", "text": text}], "structuredContent": {"result": text}}
    raise KeyError(method)


if MODE == "stuck-on-call":
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(1e6)"])
    with open(os.environ["ARTIFACT_FIXTURE_PIDFILE"], "w") as f:
        f.write(str(child.pid))

for line in sys.stdin:
    req = json.loads(line)
    if "id" not in req:
        continue  # a notification
    try:
        msg = {"jsonrpc": "2.0", "id": req["id"], "result": answer(req)}
    except KeyError as e:
        msg = {"jsonrpc": "2.0", "id": req["id"], "error": {"code": -32601, "message": f"no method {e}"}}
    print("log line on stdout, not JSON")
    print(json.dumps(msg), flush=True)
