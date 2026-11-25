# TraceAgent — Security, Packaging, CI & IDE Context Protocol (`06_SECURITY_PACKAGING_CI.md`)

## 1. Local-First Security & STRIDE Guardrails (`docs/security/STRIDE.md`)
1. **Localhost-Only Default Bind:** `traceagent serve` and `traceagent demo` MUST bind to `127.0.0.1` by default (never `0.0.0.0` unless user explicitly passes `--host 0.0.0.0`), preventing accidental LAN exposure of local agent traces.
2. **Ingest Secret Redaction Filter:** Before writing OTLP or MCP payloads to SQLite, run a lightweight regex scrubber (`src/traceagent/ingest/redactor.py`) that masks common API key patterns (`sk-...`, `AIza...`, `ghp_...`, `Bearer ...`) with `[REDACTED]` (configurable via `--no-redact` for local debugging).
3. **Database File Permissions:** Create `~/.traceagent/` with `0o700` and `ledger.db` with `0o600` on POSIX systems so other local OS users cannot read trace payloads.
4. **No Shell Injection in `traceagent wrap`:** Always pass argv list directly to `asyncio.create_subprocess_exec(*cmd)` — never join strings with `shell=True`.
5. **Request Size Cap:** Enforce a `10 MB` max payload middleware on `POST /v1/traces` (returns HTTP `413`).

---

## 2. Python Wheel Packaging (`pyproject.toml` — Zero-Node End-User Install)

Use **Hatchling** so `frontend/out` (copied to `src/traceagent/static/`) is cleanly included in the built wheel:

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "traceagent"
version = "0.1.0"
description = "Zero-cloud OTel GenAI flight recorder, SHA-256 audit ledger, and time-travel replay debugger for LangGraph & MCP agents."
readme = "README.md"
requires-python = ">=3.12"
license = { text = "MIT" }
dependencies = [
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.32.0",
    "aiosqlite>=0.20.0",
    "pydantic>=2.10.0",
    "pydantic-settings>=2.7.0",
    "typer>=0.15.0",
    "rich>=13.9.0",
]

[project.scripts]
traceagent = "traceagent.cli:app"

[tool.hatch.build.targets.wheel]
packages = ["src/traceagent"]
artifacts = ["src/traceagent/static/**"]
```

---

## 3. Deterministic GitHub Actions CI (`.github/workflows/ci.yml`)

Runs on every `push` and `pull_request` (Ubuntu + Python 3.12 + Node 20, **$0 cost, zero live LLM calls**):
1. **Lint & Typecheck:** `ruff check src tests` + `mypy src`
2. **Security Scan:** `bandit -r src -ll`
3. **Backend Tests:** `pytest -v --cov=traceagent --cov-report=term-missing`
4. **Frontend Build Check:** `cd frontend && npm ci && npm run typecheck && npm run lint && npm run build`
5. **End-to-End Packaging Smoke Test:** Build wheel (`python -m build`), install into a clean venv, run `traceagent --help`, seed demo DB, run `traceagent verify --all`, and run `traceagent check` against fixture JSONL.

---

## 4. Antigravity IDE Context Injection Protocol (Prevent Drift)

Attach **ONLY** the files needed for your active phase—never dump all 8 specs into every prompt:

| Active Build Phase | Attach ONLY These Spec Files in Antigravity IDE |
| :--- | :--- |
| **Phase 0 & Phase 1 (Scaffold + SQLite WAL Ledger)** | `AGENTS.md`, `00_PHASE_TRACKER.md`, `01_SPEC_ARCHITECTURE.md`, `05_TEST_AND_BENCHMARK_PLAN.md` |
| **Phase 2 (OTLP Ingest + MCP Stdio Tap)** | `AGENTS.md`, `02_PROTOCOL_CONTRACTS.md`, `05_TEST_AND_BENCHMARK_PLAN.md` |
| **Phase 3 (Two-Mode Replay + Fork + CI Gate)** | `AGENTS.md`, `02_PROTOCOL_CONTRACTS.md`, `03_REPLAY_AND_FORK_SPEC.md`, `05_TEST_AND_BENCHMARK_PLAN.md` |
| **Phase 4 (Next.js 15 Static UI)** | `AGENTS.md`, `02_PROTOCOL_CONTRACTS.md`, `04_FRONTEND_STATIC_UI_SPEC.md` |
| **Phase 5 (Demo, Benchmark, Wheel & CI)** | `AGENTS.md`, `03_REPLAY_AND_FORK_SPEC.md`, `05_TEST_AND_BENCHMARK_PLAN.md`, `06_SECURITY_PACKAGING_CI.md` |
