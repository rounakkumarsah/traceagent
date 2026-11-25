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

## Phase 4 — Bundled Next.js 15 Static Flamegraph & Fork UI
- [x] Create Next.js 15 + React 19 + TypeScript + Tailwind CSS app under `frontend/` with `output: "export"`, `trailingSlash: true`, `images: { unoptimized: true }`, and `/?trace=<trace_id>` wrapped in `<Suspense>`.
- [x] Implement 3-panel dark DevTool workspace (`TraceExplorer`, `WaterfallFlamegraph` + SHA-256 Chain Status badge, `StepInspector` + live-validated JSON editor + 2-mode Fork selector + Base vs. Fork Diff summary).
- [x] Build `frontend/out/`, copy to `src/traceagent/static/`, and mount in `src/traceagent/server/app.py` via `StaticFiles(html=True)` after all `/v1/*` and `/api/*` routes.
- [x] Add `tests/test_static_ui.py` verifying `GET /` returns HTTP 200 HTML and `/api/health` is not shadowed.

## Phase 5 — Final Production Hardening & Launch Readiness
- [x] Create `scripts/benchmark_replay.py` measuring real local timings via `time.perf_counter()` on a clean temp SQLite WAL DB (1,000-step write, 1,000-step SHA-256 verify, 20-step Mode-1 stub replay + diff).
- [x] Create `.github/workflows/ci.yml` matching `06_SECURITY_PACKAGING_CI.md` (100% deterministic offline CI: `ruff`, `mypy`, `bandit -r src -ll`, `pytest --cov=traceagent`, frontend `typecheck`/`lint`/`build`, wheel build + clean venv smoke test).
- [x] Create MIT `LICENSE`, `docs/security/STRIDE.md`, and 3 ADRs under `docs/adr/` (`001-sqlite-wal-hash-chain.md`, `002-two-mode-replay-honesty.md`, `003-bundled-static-ui.md`).
- [x] Verify `pyproject.toml` Hatchling wheel config includes `artifacts = ["src/traceagent/static/**"]`.
- [x] Write `README.md` with above-the-fold hierarchy, `docs/demo.gif` placeholder, 1-command offline quickstart, Mode 1 vs Mode 2 explanation, real measured benchmark table, architecture diagram, CLI reference, and Enterprise Integration contact.
