# TraceAgent — Test Matrix & Reproducible Benchmark Plan (`05_TEST_AND_BENCHMARK_PLAN.md`)

All tests MUST run **100% offline, deterministically, and without paid LLM API keys**. No superficial `assert response.status_code == 200` smoke tests without payload & invariant assertions.

---

## 1. Mandatory Pytest Suite (`tests/`)

### `tests/test_ledger_integrity.py`
1. `test_wal_pragmas_active` — Verifies `PRAGMA journal_mode` returns `"wal"` and `PRAGMA foreign_keys` returns `1`.
2. `test_hash_chain_valid_across_100_steps` — Inserts 100 steps, runs `verify_trace()`, asserts `valid is True` and `checked_steps == 100`.
3. `test_tamper_detection_catches_single_byte_edit` — Inserts 10 steps, executes raw SQL `UPDATE steps SET payload_json = ... WHERE seq = 4`, asserts `verify_trace()` returns `valid is False` and `corrupted_seq == 4`.
4. `test_canonical_json_key_order_stability` — Asserts `{"b": 1, "a": 2}` and `{"a": 2, "b": 1}` produce identical `step_hash`.

### `tests/test_otlp_ingest.py`
1. `test_otlp_genai_span_mapping` — Posts a realistic `ExportTraceServiceRequest` containing `gen_ai.operation.name`, string-encoded `intValue` token counts, and `mcp.tool.name` to `POST /v1/traces`; asserts HTTP `200`, SQLite row created, and integer token coercion is exact.
2. `test_otlp_error_span_status` — Asserts OTLP `status.code == 2` maps to `status == "error"`.
3. `test_otlp_oversized_payload_rejected` — Asserts body > 10MB returns HTTP `413`.

### `tests/test_mcp_wrap.py`
1. `test_stdio_transparent_proxy_and_logging` — Spawns a real Python echo MCP server subprocess via `traceagent wrap -- python tests/fixtures/mock_mcp_server.py`, sends newline-delimited JSON-RPC `tools/list` and `tools/call` on stdin, asserts **exact unmodified JSON-RPC bytes** arrive on stdout (zero log corruption), and asserts SQLite WAL recorded both calls with positive `duration_ms`.
2. `test_stdio_jsonrpc_error_captured` — Triggers a JSON-RPC error response from mock server and asserts `status == "error"` in ledger.

### `tests/test_replay_and_fork.py`
1. `test_demo_seed_fails_at_step_6_and_stub_fork_passes` — Seeds demo trace, asserts Step 6 is `error`, calls `POST /api/traces/demo-langgraph-mcp-001/fork` at `seq=5` with valid JSON in `stub_replay` mode, asserts `tokens_burned == 0`, `fork_status == "ok"`, `error_count_delta == -1`, and child trace SHA-256 chain is `valid is True`.
2. `test_live_fork_without_provider_returns_400` — Asserts `mode="live_fork"` without configured runner returns HTTP `400` instead of faking a response.

### `tests/test_ci_gate.py`
1. `test_check_passes_within_budget` — Asserts `traceagent check` exits `0` when tokens are within `+15%` and zero new errors.
2. `test_check_fails_on_token_regression` — Asserts exit `1` when candidate exceeds `--max-token-increase-pct`.
3. `test_check_fails_on_new_tool_error` — Asserts exit `1` when candidate introduces an `"error"` step absent in golden.

---

## 2. Reproducible Local Benchmark (`scripts/benchmark_replay.py`)

Must execute offline in `<10s` on a clean temporary SQLite file using `time.perf_counter()` and output a Markdown table ready to paste into `README.md`:

| Benchmark | Workload | Metric Reported |
| :--- | :--- | :--- |
| **SQLite WAL + SHA-256 Write** | 1,000 sequential steps (`1 KB` JSON payload each) | P50 / P95 latency (ms/step) + throughput (steps/sec) |
| **Full Audit Chain Verification** | Verify SHA-256 chain from genesis across 1,000 steps | Total verify time (ms) |
| **Mode 1 Deterministic Stub Replay** | Fork & diff 20-step trajectory from Step 14 | Total replay + diff latency (ms), `$0.00` tokens burned |

**Rule:** Never hardcode target numbers in the script output—print the real measured numbers plus Python version, OS, and CPU model for reproducibility.
