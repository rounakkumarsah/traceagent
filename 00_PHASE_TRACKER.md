# TraceAgent Phase Tracker

## Phase 0 — Repository Scaffold & Packaging Skeleton
- [x] Initialize repo layout (`src/traceagent/`, `frontend/`, `tests/`, `scripts/`, `docs/adr/`, `.github/workflows/`).
- [x] Configure `pyproject.toml` with Hatchling build, CLI entrypoint (`traceagent = "traceagent.cli:app"`), `ruff`, `mypy`, and `pytest` config.

## Phase 1 — Append-Only SQLite WAL Ledger & SHA-256 Hash Chain
- [x] Implement `src/traceagent/storage/sqlite_ledger.py` with `PRAGMA journal_mode=WAL`, `PRAGMA synchronous=NORMAL`, `PRAGMA foreign_keys=ON`, `PRAGMA busy_timeout=5000`.
- [x] Implement tables: `traces`, `steps`, `forks`.
- [x] Implement deterministic canonical JSON serialization (`sort_keys=True, separators=(",", ":")`) and SHA-256 hash chain.
- [x] Implement `traceagent verify <trace_id>` (and `--all`) in `src/traceagent/cli.py` returning exit code `0` on valid chain and exit code `1` with exact tampered `seq` on modification.

## Phase 2 — OTLP Receiver, MCP Stdio Tap & LangGraph Adapter
- [x] Implement OTLP HTTP/JSON receiver (`POST /v1/traces`) + `GET /api/health`, `GET /api/traces`, `GET /api/traces/{trace_id}` in `src/traceagent/server/app.py` and `src/traceagent/ingest/otlp_parser.py` (with `10 MB` payload cap returning HTTP 413, `gen_ai.*` + `mcp.*` normalization, string-to-int coercion for OTLP `intValue`, and ingest secret redactor in `src/traceagent/ingest/redactor.py`).
- [x] Implement transparent MCP stdio proxy (`traceagent wrap -- <cmd...>`) in `src/traceagent/ingest/mcp_tap.py` + wired into `cli.py` (`traceagent serve` bound to `127.0.0.1` by default and `traceagent wrap`).
- [x] Implement 1-line LangGraph callback adapter in `src/traceagent/adapters/langgraph.py`.
- [x] Add mandatory tests in `tests/test_otlp_ingest.py`, `tests/test_mcp_wrap.py`, and `tests/fixtures/mock_mcp_server.py`.

## Phase 3 — Two-Mode Replay & Fork Engine, Offline Demo Fixture & CI Gate
- [x] Implement offline 7-step demo fixture in `src/traceagent/demo/seed_demo.py` (`demo-langgraph-mcp-001`, crashing at Seq 6 due to malformed truncated JSON returned at Seq 5).
- [x] Implement Two-Mode Replay & Fork Engine in `src/traceagent/replay/stub_replay.py` and `src/traceagent/replay/forker.py`, wired to `POST /api/traces/{trace_id}/fork` in `src/traceagent/server/app.py`.
- [x] Implement CI Golden-Trace Regression Gate in `src/traceagent/replay/ci_gate.py` + `traceagent check` and `traceagent demo` in `src/traceagent/cli.py`.
- [x] Add mandatory tests in `tests/test_replay_and_fork.py` and `tests/test_ci_gate.py`.
