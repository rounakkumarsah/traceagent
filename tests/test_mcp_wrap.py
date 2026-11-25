"""Subprocess tests for transparent MCP stdio proxy (traceagent wrap)."""

import asyncio
import json
import subprocess
import sys
from pathlib import Path

from traceagent.storage.sqlite_ledger import SQLiteLedger

MOCK_SERVER = Path(__file__).parent / "fixtures" / "mock_mcp_server.py"


def test_mcp_wrap_transparent_stdio_and_ledger(tmp_path: Path) -> None:
    db_path = tmp_path / "mcp_wrap.db"
    trace_id = "mcp-test-trace-001"

    requests = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "echo",
                "arguments": {"api_key": "sk-proj-secret1234567890abcdef", "text": "hello"},
            },
        },
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {"name": "fail_tool", "arguments": {}},
        },
    ]
    stdin_data = "\n".join(json.dumps(r) for r in requests) + "\n"

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "traceagent.cli",
            "wrap",
            "--db",
            str(db_path),
            "--trace-id",
            trace_id,
            "--",
            sys.executable,
            str(MOCK_SERVER),
        ],
        input=stdin_data,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )

    assert proc.returncode == 0, f"stderr: {proc.stderr}"

    # stdout MUST contain ONLY valid JSON-RPC responses from mock_mcp_server.py
    stdout_lines = [line for line in proc.stdout.strip().splitlines() if line.strip()]
    assert len(stdout_lines) == 4
    responses = [json.loads(line) for line in stdout_lines]
    assert [r["id"] for r in responses] == [1, 2, 3, 4]
    assert responses[2]["result"]["content"][0]["text"] == "echo:echo"
    assert "error" in responses[3]

    # Verify ledger recorded all 4 steps, redacted secret, and hash chain is valid
    async def _check_ledger() -> None:
        ledger = SQLiteLedger(db_path)
        verify_res = await ledger.verify_trace(trace_id)
        assert verify_res.valid is True
        assert verify_res.checked_steps == 4

        steps = await ledger.get_steps(trace_id)
        assert len(steps) == 4
        assert all(s.op_type == "mcp_call" for s in steps)
        assert steps[2].name == "echo"
        assert steps[2].status == "ok"
        assert "sk-proj-secret1234567890abcdef" not in steps[2].payload_json
        assert "[REDACTED]" in steps[2].payload_json
        assert steps[3].name == "fail_tool"
        assert steps[3].status == "error"

    asyncio.run(_check_ledger())
