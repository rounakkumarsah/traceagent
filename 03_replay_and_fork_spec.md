# TraceAgent — Two-Mode Replay, Forking & CI Gate Spec (`03_REPLAY_AND_FORK_SPEC.md`)

This document defines the exact semantics of TraceAgent's two replay modes, trajectory diffing, CI golden-trace gate, and the offline 7-step demo fixture.

---

## 1. Strict Two-Mode Replay Semantics (Zero Misrepresentation)

### Mode 1: Deterministic Stub Replay (`mode = "stub_replay"`)
- **Purpose:** Verify fixes to Python tool parsers, JSON schema validators, LangGraph conditional routers, and post-processing logic at **$0.00 token cost** and **<15 ms**.
- **Execution:**
  1. Copy Steps `0 .. fork_at_seq - 1` verbatim from `parent_trace_id` into the new child trace (recomputing a fresh valid SHA-256 hash chain for the child trace).
  2. At `seq == fork_at_seq`, replace `payload["output"]` (or `payload["input"]`) with `override_payload`.
  3. For Steps `fork_at_seq + 1 .. end`, run registered deterministic Python validators/handlers (e.g., JSON schema check, router invariant check, tool output parser) against the mutated state **without calling any external LLM API**.
  4. Record `tokens_burned = 0`, `prefix_tokens_saved = sum(tokens of steps 0..fork_at_seq-1)`, and `replay_mode = "deterministic_stub"`.

### Mode 2: Time-Travel Live Fork (`mode = "live_fork"`)
- **Purpose:** Test how a live LLM (or local Ollama model) reacts downstream after mutating Step `N`, without re-paying for Steps `0 .. N-1`.
- **Execution:**
  1. Replay Steps `0 .. fork_at_seq - 1` from SQLite WAL (`tokens_burned = 0` for prefix).
  2. Apply `override_payload` at `seq == fork_at_seq`.
  3. Dispatch Step `fork_at_seq + 1` onward to a configured pluggable runner (`LiveRunner` interface supporting OpenAI-compatible / Gemini / Ollama endpoints).
  4. Record **actual new tokens consumed** by live downstream calls in `tokens_burned`, and explicitly display `prefix_tokens_saved` vs. `tokens_burned`.
  5. If no live provider key/URL is configured, return HTTP `400 Bad Request` with a clear message instructing the user to either use `stub_replay` or configure a live runner — **NEVER silently fake a live LLM response**.

---

## 2. Trajectory Diff Specification (`TrajectoryDiff`)

Computed deterministically by comparing `base_steps` and `fork_steps`:
- `base_status` / `fork_status`: `"ok"` if zero steps have `status == "error"`, else `"error"`.
- `step_count_delta`: `len(fork_steps) - len(base_steps)`.
- `error_count_delta`: `fork_errors - base_errors` (negative = improvement).
- `latency_delta_ms`: `sum(fork.duration_ms) - sum(base.duration_ms)`.
- `token_delta`: `(fork_in + fork_out) - (base_in + base_out)`.
- `changed_seqs`: sorted list of `seq` indices where `canonical_json(base.payload) != canonical_json(fork.payload)` or `base.status != fork.status`.

---

## 3. CI Golden-Trace Regression Gate (`traceagent check`)

### Command Signature
```bash
traceagent check \
  --golden tests/fixtures/golden_trace.jsonl \
  --candidate out/latest_run.jsonl \
  --max-token-increase-pct 15 \
  --max-step-increase 2
```

### JSONL Line Schema (One Step per Line)
```json
{"seq": 0, "op_type": "invoke_agent", "name": "supervisor", "status": "ok", "input_tokens": 410, "output_tokens": 95, "duration_ms": 142.5}
```

### Exit Codes & Failure Conditions
- **Exit `0` (PASS):**
  - Zero new `"error"` steps compared to golden baseline.
  - Candidate step count `<= golden_steps + max_step_increase`.
  - Candidate total tokens `<= golden_tokens * (1 + max_token_increase_pct / 100)`.
  - Required tool names from golden sequence are still invoked (no silent tool drop).
- **Exit `1` (REGRESSION DETECTED):** Prints a clean Rich table showing exact failing rule(s), golden vs. candidate values, and offending `seq`.
- **Exit `2` (INVALID INPUT):** Missing file or malformed JSONL.

---

## 4. Offline 7-Step Demo Fixture (`src/traceagent/demo/seed_demo.py`)

`traceagent demo` seeds `trace_id = "demo-langgraph-mcp-001"` (`name = "order-refund-agent"`):
- **Seq 0 (`invoke_agent`):** `refund_supervisor` — receives `"Refund order ORD-9042, arrived damaged"` (`status: ok`, 380 in / 75 out).
- **Seq 1 (`chat`):** `planner_node` — plans lookup via MCP tool `mcp:get_order_status` (`status: ok`, 490 in / 110 out).
- **Seq 2 (`mcp_call`):** `mcp:get_order_status` — returns valid order metadata (`status: ok`, 42ms).
- **Seq 3 (`chat`):** `policy_evaluator` — checks 30-day return window (`status: ok`, 620 in / 130 out).
- **Seq 4 (`mcp_call`):** `mcp:check_refund_eligibility` — returns `eligible: true` (`status: ok`, 38ms).
- **Seq 5 (`mcp_call`):** `mcp:fetch_payment_intent` — returns **malformed truncated JSON** `{"intent_id": "pi_8821", "amount_usd": "49.00` (`status: ok` from flaky upstream MCP tool, bad payload!).
- **Seq 6 (`execute_tool`):** `parse_and_issue_refund` — **CRASHES** with `JSONDecodeError: Unterminated string` (`status: error`, 3ms).

**Demo "Aha!" Flow:** User clicks Seq 5 in the UI, fixes the JSON to `{"intent_id": "pi_8821", "amount_usd": 49.0}`, clicks **Run Stub Replay ($0.00)**, and watches Seq 6 turn **GREEN (`ok`)** in `<15 ms` with `SHA-256 Chain: VALID` and `0 Tokens Burned`.
