# TraceAgent

**Zero-cloud OpenTelemetry GenAI flight recorder, SHA-256 tamper-evident ledger, and time-travel replay debugger for LangGraph & MCP agents.**

[![CI](https://github.com/rounakkumarsah/traceagent/actions/workflows/ci.yml/badge.svg)](https://github.com/rounakkumarsah/traceagent/actions/workflows/ci.yml)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

<!-- Demo GIF placeholder: record 30s walkthrough and save to docs/demo.gif -->
<!-- ![TraceAgent 30s Demo](docs/demo.gif) -->

---

## 1-Command Offline Quickstart

Zero API keys, zero Docker, zero Node.js required:

```bash
pip install traceagent && traceagent demo
```

This seeds a realistic 7-step LangGraph + MCP refund-agent trace (`demo-langgraph-mcp-001`) that crashes at Step 6 due to truncated JSON from Step 5, starts the local FastAPI + bundled Next.js 15 Flamegraph UI on `http://127.0.0.1:8765`, and lets you fork & fix Step 5 in-place at `$0.00` token cost.

---

## Two-Mode Replay & Fork (Epistemic Honesty)

TraceAgent strictly separates deterministic offline replay from live LLM re-execution:

- **Mode 1 — Deterministic Stub Replay (`stub_replay`, `$0.00`):** Replays cached steps `0..N-1`, applies your edited payload at Step `N`, and re-runs deterministic Python validators/parsers/routers from Step `N+1` onward. **0 tokens burned.**
- **Mode 2 — Time-Travel Live Fork (`live_fork`):** Replays cached steps `0..N-1` at `$0.00` from the SQLite ledger and invokes a configured real or local LLM provider only from Step `N` onward. Calling `live_fork` without a configured provider fails explicitly with HTTP `400`.

---

## Measured Local Benchmarks

Measured directly via `python scripts/benchmark_replay.py` on a clean temporary SQLite WAL database:

**Environment:** Python 3.12.10 | Windows 11 | CPU: `Intel64 Family 6 Model 141 Stepping 1, GenuineIntel`

| Benchmark | Workload | Measured Result |
| :--- | :--- | :--- |
| **SQLite WAL + SHA-256 Write** | 1,000 sequential steps (`~1 KB` JSON each) | P50: `5.15 ms/step`, P95: `6.07 ms/step`, `190 steps/sec` |
| **Full Audit Chain Verification** | Verify SHA-256 chain from genesis (1,000 steps) | `9.84 ms` |
| **Mode 1 Deterministic Stub Replay** | Fork & diff 20-step trajectory from Step 14 | `120.63 ms` (`$0.00` / `0` tokens burned) |

---

## Architecture

```
LangGraph Callback / OTLP HTTP (POST /v1/traces) / MCP Stdio Tap (traceagent wrap)
        │
        ▼  (Ingest Secret Redactor + 10 MB Cap)
SQLite WAL Ledger (~/.traceagent/ledger.db)
  ├── traces
  ├── steps  ──► SHA-256(prev_hash | seq | timestamp_ns | canonical_json(payload))
  └── forks
        │
        ├──► Mode 1: Deterministic Stub Replay ($0.00) & CI Golden-Trace Gate
        ├──► Mode 2: Time-Travel Live Fork (Steps N..end)
        └──► Bundled Next.js 15 Static Flamegraph & Fork UI (127.0.0.1:8765)
```

---

## CLI Command Reference

| Command | Description |
| :--- | :--- |
| `traceagent demo` | Seed offline demo trace and launch the local UI on `127.0.0.1:8765` |
| `traceagent serve` | Start OTLP receiver + API + static UI (`--host 127.0.0.1 --port 8765`) |
| `traceagent wrap -- <cmd...>` | Transparent MCP stdio proxy logging JSON-RPC calls to SQLite WAL |
| `traceagent verify <trace_id>` | Verify SHA-256 hash chain integrity (`--all` for all traces) |
| `traceagent check <candidate> --golden <golden>` | CI regression gate on token budget and new tool errors |

---

## Enterprise Integration

For custom OTLP collectors, air-gapped compliance deployments, or CI/CD integration support, contact **rounakkrsah429@gmail.com**.
