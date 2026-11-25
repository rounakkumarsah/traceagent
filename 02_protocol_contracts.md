# TraceAgent — Protocol & API Wire Contracts (`02_PROTOCOL_CONTRACTS.md`)

This file is the **single source of truth** for wire formats across OTLP ingest, MCP stdio proxying, and FastAPI REST endpoints. Do not deviate from these field names in backend or frontend code.

---

## 1. OTLP HTTP/JSON Ingest Contract (`POST /v1/traces`)

Standard OpenTelemetry `ExportTraceServiceRequest` JSON payload (Content-Type: `application/json`, max body size `10 MB`):

```json
{
  "resourceSpans": [
    {
      "resource": {
        "attributes": [
          { "key": "service.name", "value": { "stringValue": "my-langgraph-agent" } }
        ]
      },
      "scopeSpans": [
        {
          "spans": [
            {
              "traceId": "4bf92f3577b34da6a3ce929d0e0e4736",
              "spanId": "00f067aa0ba902b7",
              "parentSpanId": "",
              "name": "execute_tool read_customer_orders",
              "startTimeUnixNano": "1732492800000000000",
              "endTimeUnixNano": "1732492800125000000",
              "status": { "code": 1, "message": "" },
              "attributes": [
                { "key": "gen_ai.operation.name", "value": { "stringValue": "execute_tool" } },
                { "key": "gen_ai.request.model", "value": { "stringValue": "gemini-2.5-flash" } },
                { "key": "gen_ai.usage.input_tokens", "value": { "intValue": "412" } },
                { "key": "gen_ai.usage.output_tokens", "value": { "intValue": "89" } },
                { "key": "mcp.tool.name", "value": { "stringValue": "read_customer_orders" } }
              ]
            }
          ]
        }
      ]
    }
  ]
}
```

### Mandatory OTLP Parsing Rules
1. **AnyValue Unwrapper:** Handle `stringValue`, `intValue` (note: OTLP JSON encodes 64-bit ints as strings like `"412"` — always coerce via `int()`), `doubleValue`, `boolValue`, and `arrayValue`.
2. **Attribute Normalization Priority:**
   - `op_type`: `gen_ai.operation.name` → fallback `openinference.span.kind` → default `"span"`.
   - `model`: `gen_ai.request.model` → fallback `llm.model_name` → `null`.
   - `input_tokens`: `gen_ai.usage.input_tokens` → fallback `llm.token_count.prompt` → `0`.
   - `output_tokens`: `gen_ai.usage.output_tokens` → fallback `llm.token_count.completion` → `0`.
   - `tool_name`: `mcp.tool.name` → fallback `gen_ai.tool.name` → `span.name`.
   - `status`: `"error"` if `span.status.code == 2` else `"ok"`.
3. **Response:** Return HTTP `200 OK` with `{"partialSuccess": {}}` (standard OTLP HTTP/JSON acknowledgement).

---

## 2. MCP Stdio Proxy Contract (`traceagent wrap -- <cmd...>`)

The wrapper sits transparently between an MCP Client (e.g., Claude Desktop, Cursor, Antigravity, LangGraph) and an MCP Server subprocess.

### Hard Framing & Isolation Invariants
1. **NEVER write logs or banners to `stdout`:** MCP stdio uses `stdout` exclusively for newline-delimited JSON-RPC 2.0 messages. Any TraceAgent log message MUST go to `stderr` (or a log file) so the MCP client parser is never corrupted.
2. **Subprocess Launch:** Always spawn via `asyncio.create_subprocess_exec(*cmd, stdin=PIPE, stdout=PIPE, stderr=PIPE)` — **NEVER `shell=True`**.
3. **Request/Response Correlation:**
   - Parse each `\n`-delimited JSON line from client `stdin`. If `method` is present and `id` is not None, store `pending[id] = (method, params, start_ns)`.
   - Forward raw bytes unmodified to child `stdin` immediately (zero buffering delay).
   - Parse each `\n`-delimited JSON line from child `stdout`. Forward raw bytes unmodified to client `stdout` immediately.
   - If `id in pending`, compute `duration_ms = (now_ns - start_ns) / 1e6`, detect JSON-RPC `"error"` key, and enqueue an async write to SQLite WAL (`op_type="mcp_call"`).
   - Notifications (messages without `id`) are forwarded unmodified and logged with `duration_ms=0.0`.
4. **Graceful Shutdown:** Propagate `EOF` on client `stdin` to child `stdin`, wait up to 3s for child exit, flush SQLite WAL queue, then exit with child's return code.

---

## 3. Internal FastAPI REST Contracts (Used by Bundled UI & CLI)

### `GET /api/traces`
```json
{
  "traces": [
    {
      "trace_id": "demo-langgraph-mcp-001",
      "name": "order-refund-agent",
      "source": "demo",
      "status": "error",
      "step_count": 7,
      "total_in_tokens": 2840,
      "total_out_tokens": 615,
      "parent_trace_id": null,
      "forked_from_seq": null,
      "started_at_ns": 1732492800000000000
    }
  ]
}
```

### `GET /api/traces/{trace_id}`
```json
{
  "trace": { "...same fields as above..." },
  "chain_verification": {
    "valid": true,
    "checked_steps": 7,
    "corrupted_seq": null
  },
  "steps": [
    {
      "seq": 0,
      "span_id": "sp-000",
      "parent_span_id": null,
      "op_type": "invoke_agent",
      "name": "order_refund_supervisor",
      "model": "gemini-2.5-flash",
      "status": "ok",
      "duration_ms": 142.5,
      "input_tokens": 410,
      "output_tokens": 95,
      "payload": { "input": {}, "output": {}, "error": null },
      "prev_hash": "0000...0000",
      "step_hash": "a9f3..."
    }
  ]
}
```

### `POST /api/traces/{trace_id}/fork`
**Request:**
```json
{
  "fork_at_seq": 5,
  "mode": "stub_replay",
  "override_payload": {
    "output": { "order_id": "ORD-9042", "eligible": true, "amount_usd": 49.0 }
  }
}
```
**Response (`201 Created`):**
```json
{
  "fork_trace_id": "demo-langgraph-mcp-001-fork-1",
  "mode": "stub_replay",
  "tokens_burned": 0,
  "prefix_tokens_saved": 2310,
  "replay_duration_ms": 4.8,
  "diff": {
    "base_status": "error",
    "fork_status": "ok",
    "step_count_delta": 0,
    "error_count_delta": -1,
    "changed_seqs": [5, 6]
  }
}
```
