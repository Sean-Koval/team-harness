"""A stdio MCP server for tests/test_artifact_check.py: one `search` tool. --broken gives it an invalid input schema,
--undocumented drops its description, --wrong makes it answer the golden call wrongly."""

import json
import sys

ITEMS = [{"id": "1", "title": "First example item"}, {"id": "2", "title": "Second example item"}]
SCHEMA = {"type": "object", "properties": {"query": {"type": "string"}, "limit": {"type": "integer", "minimum": 1}},
          "required": ["query"]}


def tool() -> dict:
    t = {"name": "search", "description": "Search the items.", "inputSchema": dict(SCHEMA)}
    if "--broken" in sys.argv:
        t["inputSchema"] = {**SCHEMA, "properties": {"query": {"type": "text"}}}
    if "--undocumented" in sys.argv:
        del t["description"]
    return t


def call(args: dict) -> dict:
    query = str(args.get("query", "")).strip()
    if not query:
        return {"content": [{"type": "text", "text": "query is empty"}], "isError": True}
    hits = ITEMS[: int(args.get("limit", 10))]
    if "--wrong" in sys.argv:
        hits = hits[:1]
    return {"content": [{"type": "text", "text": json.dumps(hits)}], "structuredContent": {"result": hits}}


def main() -> None:
    print("fixture server starting", flush=True)  # a stray log line the client must skip
    for line in sys.stdin:
        msg = json.loads(line)
        if "id" not in msg:
            continue
        method, params = msg.get("method"), msg.get("params") or {}
        if method == "initialize":
            result = {"protocolVersion": params.get("protocolVersion"), "capabilities": {"tools": {}},
                      "serverInfo": {"name": "fixture", "version": "1"}}
        elif method == "tools/list":
            result = {"tools": [tool()]}
        elif method == "tools/call" and params.get("name") == "search":
            result = call(params.get("arguments") or {})
        else:
            print(json.dumps({"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -32601, "message": method}}),
                  flush=True)
            continue
        print(json.dumps({"jsonrpc": "2.0", "id": msg["id"], "result": result}), flush=True)


if __name__ == "__main__":
    main()
