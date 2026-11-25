# TraceAgent — Architecture & Implementation Specification (`01_SPEC_ARCHITECTURE.md`)

## 1. System Overview

`traceagent` is a local-first, zero-cloud OpenTelemetry GenAI flight recorder, tamper-evident SQLite WAL audit ledger, and two-mode time-travel replay debugger for LangGraph and MCP agents.

```
  [LangGraph Adapter]   [OTel GenAI SDKs]   [MCP Server via `traceagent wrap -- <cmd>`]
           │                    │                           │
           └─────────► POST /v1/traces (OTLP HTTP/JSON) ◄───┘
                                │
                                ▼
             ┌──────────────────────────────────────┐
             │      TraceAgent Core (FastAPI)       │
             │  • OTLP gen_ai.* & mcp.* Normalizer  │
             │  • Append-Only SQLite WAL Ledger     │
             │  • SHA-256 Genesis Hash Chain        │
             │  • Mode 1: Deterministic Stub Replay │
             │  • Mode 2: Time-Travel Fork Engine   │
             │  • CI Golden-Trace Regression Gate   │
             └──────────────────┬───────────────────┘
                                │
                                ▼
             [Bundled Next.js 15 Static Export UI]
             Served directly by FastAPI on :4318

```

## 2. Repository & Package Layout

```
traceagent/
├── pyproject.toml                  # Hatchling build; includes src/traceagent/static/**
├── README.md                       # Above-the-fold: Tagline -> 30s GIF -> Quickstart -> Benchmarks
├── 00_PHASE_TRACKER.md
├── AGENTS.md
├── 01_SPEC_ARCHITECTURE.md
├── docs/
│   └── adr/
│       ├── 001-sqlite-wal-hash-chain.md
│       ├── 002-two-mode-replay-honesty.md
│       └── 003-bundled-static-ui.md
├── src/
│   └── traceagent/
│       ├── __init__.py
│       ├── cli.py                  # Typer CLI: demo, serve, wrap, verify, check
│       ├── config.py               # Pydantic-settings (DB path, ports, limits)
│       ├── models.py               # Pydantic v2 domain & API schemas
│       ├── storage/
│       │   └── sqlite_ledger.py    # Async SQLite WAL + SHA-256 hash chain + verifier
│       ├── ingest/
│       │   ├── otlp_parser.py      # OTLP HTTP/JSON -> normalized StepRecord
│       │   └── mcp_tap.py          # Stdio JSON-RPC 2.0 transparent proxy interceptor
│       ├── adapters/
│       │   └── langgraph.py        # 1-line LangGraph callback handler
│       ├── replay/
│       │   ├── stub_replay.py      # Mode 1: $0.00 deterministic stub replay
│       │   ├── forker.py           # Mode 2: Time-travel fork from Step N + TrajectoryDiff
│       │   └── ci_gate.py          # Golden JSONL regression checker
│       ├── server/
│       │   └── app.py              # FastAPI app: /v1/traces, /api/traces/*, static UI mount
│       ├── demo/
│       │   └── seed_demo.py        # 7-step LangGraph + MCP failure trajectory fixture
│       └── static/                 # Compiled Next.js 15 static assets (next build)
├── frontend/                       # Next.js 15 (output: "export") + Tailwind + TypeScript
│   ├── next.config.ts
│   └── src/app/
├── scripts/
│   └── benchmark_replay.py         # Reproducible P50/P95 write & replay latency benchmark
├── tests/
│   ├── test_ledger_integrity.py
│   ├── test_otlp_ingest.py
│   ├── test_mcp_wrap.py
│   ├── test_replay_and_fork.py
│   └── test_ci_gate.py
└── .github/workflows/
    └── ci.yml                      # Deterministic offline CI (ruff, mypy, pytest, bandit)

```

## 3. SQLite WAL Schema & Hash-Chain Specification

```
CREATE TABLE IF NOT EXISTS traces (
    trace_id        TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    source          TEXT NOT NULL,          -- 'otlp' | 'mcp_tap' | 'langgraph' | 'demo'
    status          TEXT NOT NULL,          -- 'running' | 'ok' | 'error'
    started_at_ns   INTEGER NOT NULL,
    ended_at_ns     INTEGER,
    total_in_tokens INTEGER NOT NULL DEFAULT 0,
    total_out_tokens INTEGER NOT NULL DEFAULT 0,
    parent_trace_id TEXT REFERENCES traces(trace_id),
    forked_from_seq INTEGER
);

CREATE TABLE IF NOT EXISTS steps (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    trace_id        TEXT NOT NULL REFERENCES traces(trace_id) ON DELETE CASCADE,
    seq             INTEGER NOT NULL,
    span_id         TEXT NOT NULL,
    parent_span_id  TEXT,
    op_type         TEXT NOT NULL,          -- 'invoke_agent' | 'chat' | 'execute_tool' | 'mcp_call'
    name            TEXT NOT NULL,          -- e.g. 'plan_node' or 'mcp:read_file'
    model           TEXT,
    status          TEXT NOT NULL,          -- 'ok' | 'error'
    timestamp_ns    INTEGER NOT NULL,
    duration_ms     REAL NOT NULL DEFAULT 0.0,
    input_tokens    INTEGER NOT NULL DEFAULT 0,
    output_tokens   INTEGER NOT NULL DEFAULT 0,
    payload_json    TEXT NOT NULL,          -- Canonical JSON: {"input": ..., "output": ..., "error": ...}
    prev_hash       TEXT NOT NULL,          -- 64 hex chars ('0'*64 for seq=0)
    step_hash       TEXT NOT NULL,          -- sha256(prev_hash|seq|timestamp_ns|payload_json)
    UNIQUE(trace_id, seq)
);

CREATE INDEX IF NOT EXISTS idx_steps_trace_seq ON steps(trace_id, seq);

```

### Hash-Chain Formula

```
canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
digest_input = f"{prev_hash}|{seq}|{timestamp_ns}|{canonical}".encode("utf-8")
step_hash = hashlib.sha256(digest_input).hexdigest()

```

## 4. API & CLI Contracts

### FastAPI Endpoints (`src/traceagent/server/app.py`)

* `POST /v1/traces` — Standard OTLP HTTP/JSON trace ingest (extracts `gen_ai.operation.name`, `gen_ai.request.model`, `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`, `gen_ai.tool.call.id`, `mcp.tool.name`).

* `GET /api/health` — Returns `{ "status": "ok", "db": "sqlite_wal", "version": "..." }`.

* `GET /api/traces` — Lists recorded traces with step counts, status, token totals, and fork metadata.

* `GET /api/traces/{trace_id}` — Returns ordered steps + live SHA-256 verification status (`chain_valid: bool`, `corrupted_seq: int | null`).

* `POST /api/traces/{trace_id}/fork` — Accepts `{ "fork_at_seq": int, "mode": "stub_replay" | "live_fork", "override_payload": dict }`, executes replay/fork, persists new child trace, and returns `TrajectoryDiff`.

* `GET /` — Serves bundled Next.js 15 static export from `src/traceagent/static/`.

### CLI Commands (`src/traceagent/cli.py`)

1. `traceagent demo` — Seeds 7-step LangGraph + MCP failure trace (Step 6 crashes on malformed tool JSON), starts FastAPI + bundled UI at `http://127.0.0.1:4318`, and prints one-click instructions.

2. `traceagent serve --port 4318 --db ~/.traceagent/ledger.db` — Runs OTLP receiver + local UI.

3. `traceagent wrap -- <mcp_server_cmd...>` — Spawns child MCP server, proxies JSON-RPC 2.0 over stdio transparently, and writes every tool call/response into SQLite WAL.

4. `traceagent verify [trace_id | --all]` — Recomputes SHA-256 chain from genesis and exits `0` (valid) or `1` (tampered).

5. `traceagent check --golden baseline.jsonl --candidate current.jsonl [--max-token-increase-pct 15]` — CI regression gate failing on step-count drift, new tool errors, or token budget spikes.

## 5. Two-Mode Replay & Fork Semantics (Strict Contract)

1. **Mode 1 — `stub_replay` (`$0.00` token cost, `<15ms`):**

   * Loads recorded Steps `0..K` from SQLite WAL.

   * Applies user's overridden tool JSON at `fork_at_seq` and runs registered Python validators / post-processors / routing assertions without invoking any external LLM API.

   * Emits `tokens_burned = 0` and `replay_mode = "deterministic_stub"`.

2. **Mode 2 — `live_fork` (Saves Steps `0..N-1` tokens):**

   * Replays Steps `0..N-1` from SQLite cache (`tokens_burned = 0` for prefix).

   * Injects mutated Step `N` payload and dispatches Step `N+1..` to a configured live/local LLM callable (e.g., Ollama / Gemini / OpenAI), recording actual new tokens burned and computing exact savings vs. full re-run.

## 6. Reproducible Benchmark & CI Requirements

* `scripts/benchmark_replay.py` MUST run offline in `<10s` and print:

  * SQLite WAL + SHA-256 1,000-step write P50 / P95 latency (ms/step).

  * Full chain verification time for 1,000 steps (ms).

  * Mode 1 stub replay + diff latency for a 20-step trajectory (ms).

* `.github/workflows/ci.yml` MUST run on Ubuntu + Python 3.12: `ruff check`, `mypy src`, `bandit -r src`, `pytest --cov=traceagent`, and a live CLI smoke test (`traceagent verify` + `traceagent check`).