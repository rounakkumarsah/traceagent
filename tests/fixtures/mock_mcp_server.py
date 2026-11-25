"""Mock MCP stdio server for testing traceagent wrap."""

import json
import sys


def main() -> int:
    for line in sys.stdin:
        text = line.strip()
        if not text:
            continue
        try:
            req = json.loads(text)
        except json.JSONDecodeError:
            continue

        req_id = req.get("id")
        method = req.get("method", "")
        params = req.get("params") or {}

        if method == "initialize":
            resp = {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "serverInfo": {"name": "mock-mcp", "version": "0.1.0"},
                },
            }
        elif method == "tools/list":
            resp = {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"tools": [{"name": "echo"}, {"name": "fail_tool"}]},
            }
        elif method == "tools/call":
            tool_name = params.get("name")
            if tool_name == "fail_tool":
                resp = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32000, "message": "Tool execution failed"},
                }
            else:
                resp = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {"content": [{"type": "text", "text": f"echo:{tool_name}"}]},
                }
        else:
            resp = {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {},
            }

        sys.stdout.write(json.dumps(resp) + "\n")
        sys.stdout.flush()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
