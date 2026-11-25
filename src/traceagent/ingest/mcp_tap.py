"""Transparent MCP stdio proxy (traceagent wrap -- <cmd...>).

Forwards stdin -> child stdin and child stdout -> stdout byte-for-byte,
while tapping JSON-RPC 2.0 requests/responses into the TraceAgent ledger.
NEVER writes TraceAgent logs or banners to stdout (stderr only).
NEVER uses shell=True.
"""

import asyncio
import contextlib
import json
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from traceagent.ingest.redactor import redact_secrets
from traceagent.models import StepInput, StepStatus, TraceCreate
from traceagent.storage.sqlite_ledger import SQLiteLedger


def _try_parse_jsonrpc(line: bytes) -> dict[str, Any] | None:
    """Attempt to parse a single line as a JSON-RPC 2.0 object."""
    text = line.decode("utf-8", errors="replace").strip()
    if not text or not text.startswith("{"):
        return None
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        return None
    if isinstance(obj, dict):
        return obj
    return None


def run_mcp_tap(
    cmd: list[str],
    db_path: str | Path = "traceagent.db",
    trace_id: str | None = None,
) -> int:
    """Run a child MCP server process, transparently proxying stdio and recording calls."""
    if not cmd:
        sys.stderr.write("traceagent wrap: no command specified\n")
        sys.stderr.flush()
        return 1

    resolved_trace_id = trace_id or f"mcp-{uuid.uuid4().hex[:16]}"
    ledger = SQLiteLedger(db_path)
    started_ns = time.time_ns()

    pending_requests: dict[str, tuple[str, dict[str, Any], int]] = {}
    pending_lock = threading.Lock()
    recorded_steps: list[StepInput] = []
    steps_lock = threading.Lock()

    proc = subprocess.Popen(
        cmd,
        shell=False,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    def _pump_stdin() -> None:
        assert proc.stdin is not None
        try:
            while True:
                line = sys.stdin.buffer.readline()
                if not line:
                    break
                msg = _try_parse_jsonrpc(line)
                if msg is not None and "method" in msg and "id" in msg and msg["id"] is not None:
                    req_id = str(msg["id"])
                    method = str(msg["method"])
                    params = msg.get("params")
                    params_dict = params if isinstance(params, dict) else {"value": params}
                    with pending_lock:
                        pending_requests[req_id] = (method, params_dict, time.time_ns())
                proc.stdin.write(line)
                proc.stdin.flush()
        except BrokenPipeError:
            pass
        finally:
            with contextlib.suppress(OSError):
                proc.stdin.close()

    def _pump_stdout() -> None:
        assert proc.stdout is not None
        try:
            while True:
                line = proc.stdout.readline()
                if not line:
                    break
                sys.stdout.buffer.write(line)
                sys.stdout.buffer.flush()

                msg = _try_parse_jsonrpc(line)
                if (
                    msg is not None
                    and "id" in msg
                    and msg["id"] is not None
                    and "method" not in msg
                ):
                    req_id = str(msg["id"])
                    with pending_lock:
                        req_info = pending_requests.pop(req_id, None)
                    if req_info is not None:
                        method, params_dict, req_start_ns = req_info
                        end_ns = time.time_ns()
                        duration_ms = max(0.0, (end_ns - req_start_ns) / 1_000_000.0)
                        has_error = "error" in msg and msg["error"] is not None
                        status: StepStatus = "error" if has_error else "ok"

                        tool_name = method
                        if method == "tools/call" and isinstance(params_dict.get("name"), str):
                            tool_name = str(params_dict["name"])

                        payload = redact_secrets(
                            {
                                "jsonrpc_id": msg["id"],
                                "method": method,
                                "params": params_dict,
                                "result": msg.get("result"),
                                "error": msg.get("error"),
                            }
                        )
                        step = StepInput(
                            span_id=f"mcp-{req_id}-{uuid.uuid4().hex[:8]}",
                            parent_span_id=None,
                            op_type="mcp_call",
                            name=tool_name,
                            model=None,
                            status=status,
                            timestamp_ns=req_start_ns,
                            duration_ms=duration_ms,
                            input_tokens=0,
                            output_tokens=0,
                            payload=payload,
                        )
                        with steps_lock:
                            recorded_steps.append(step)
        except BrokenPipeError:
            pass

    def _pump_stderr() -> None:
        assert proc.stderr is not None
        try:
            while True:
                line = proc.stderr.readline()
                if not line:
                    break
                sys.stderr.buffer.write(line)
                sys.stderr.buffer.flush()
        except BrokenPipeError:
            pass

    t_in = threading.Thread(target=_pump_stdin, daemon=True)
    t_out = threading.Thread(target=_pump_stdout, daemon=True)
    t_err = threading.Thread(target=_pump_stderr, daemon=True)

    t_in.start()
    t_out.start()
    t_err.start()

    return_code = proc.wait()
    t_out.join(timeout=2.0)
    t_err.join(timeout=2.0)

    async def _flush_to_ledger() -> None:
        await ledger.init_schema()
        await ledger.ensure_trace(
            TraceCreate(
                trace_id=resolved_trace_id,
                name=f"mcp:{Path(cmd[0]).name}",
                source="mcp_tap",
                status="error" if return_code != 0 else "ok",
                started_at_ns=started_ns,
                ended_at_ns=time.time_ns(),
            )
        )
        with steps_lock:
            steps_to_write = list(recorded_steps)
        for step in steps_to_write:
            await ledger.append_step(resolved_trace_id, step)

    asyncio.run(_flush_to_ledger())
    return return_code
