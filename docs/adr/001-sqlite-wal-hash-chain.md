# ADR-001: SQLite WAL + SHA-256 Hash Chain

## Status
Accepted

## Context
AI agent debugging and compliance require a durable, zero-ops local store that supports concurrent reads/writes (e.g., live OTLP ingest alongside UI queries) and detects post-hoc tampering of recorded tool calls or LLM outputs.

## Decision
Use **SQLite in WAL mode** (`PRAGMA journal_mode=WAL`, `PRAGMA synchronous=NORMAL`, `PRAGMA foreign_keys=ON`, `PRAGMA busy_timeout=5000`) accessed asynchronously via `aiosqlite` with a bounded write lock. Chain every step with `SHA-256` over canonical JSON (`sort_keys=True, separators=(",", ":"), ensure_ascii=False`) starting from genesis `prev_hash = "0" * 64`.

## Consequences
- Zero external database dependencies (no Postgres/Docker required).
- `traceagent verify` can deterministically prove ledger integrity and pinpoint any tampered `seq`.
