# TraceAgent Phase Tracker

## Phase 0 — Repository Scaffold & Packaging Skeleton
- [x] Initialize repo layout (`src/traceagent/`, `frontend/`, `tests/`, `scripts/`, `docs/adr/`, `.github/workflows/`).
- [x] Configure `pyproject.toml` with Hatchling build, CLI entrypoint (`traceagent = "traceagent.cli:app"`), `ruff`, `mypy`, and `pytest` config.

## Phase 1 — Append-Only SQLite WAL Ledger & SHA-256 Hash Chain
- [x] Implement `src/traceagent/storage/sqlite_ledger.py` with `PRAGMA journal_mode=WAL`, `PRAGMA synchronous=NORMAL`, `PRAGMA foreign_keys=ON`, `PRAGMA busy_timeout=5000`.
- [x] Implement tables: `traces`, `steps`, `forks`.
- [x] Implement deterministic canonical JSON serialization (`sort_keys=True, separators=(",", ":")`) and SHA-256 hash chain.
- [x] Implement `traceagent verify <trace_id>` (and `--all`) in `src/traceagent/cli.py` returning exit code `0` on valid chain and exit code `1` with exact tampered `seq` on modification.
