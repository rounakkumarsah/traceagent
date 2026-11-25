# TraceAgent Threat Model & STRIDE Guardrails

TraceAgent is a local-first flight recorder and replay ledger for AI agents. Its security posture is designed to protect sensitive prompts, tool payloads, and API credentials on developer workstations and CI runners.

## STRIDE Summary

| Threat Category | Risk | Mitigation Implemented |
| :--- | :--- | :--- |
| **Spoofing** | Unauthorized LAN clients posting fake OTLP spans or reading local traces | `traceagent serve` and `traceagent demo` bind to `127.0.0.1` by default (`--host 0.0.0.0` requires explicit opt-in). |
| **Tampering** | Silent modification of recorded agent steps in SQLite | Every step is chained via `SHA-256(prev_hash \| seq \| timestamp_ns \| canonical_json(payload))` with genesis `prev_hash = "0"*64`. `traceagent verify` detects any single-byte edit and pinpoints the exact `corrupted_seq`. |
| **Repudiation** | Disputing which tool call or LLM output occurred in a run | Append-only SQLite WAL ledger with monotonic `seq` and cryptographic hash chain provides verifiable execution history. |
| **Information Disclosure** | API keys (`sk-...`, `AIza...`, `ghp_...`, `Bearer ...`) leaked into `ledger.db` | Ingest secret redactor (`src/traceagent/ingest/redactor.py`) masks common secret patterns with `[REDACTED]` before persistence. POSIX file permissions restrict `~/.traceagent/` (`0o700`) and `ledger.db` (`0o600`). |
| **Denial of Service** | Memory exhaustion via oversized OTLP payloads | `POST /v1/traces` enforces a `10 MB` max request body cap, returning HTTP `413` on oversized payloads. |
| **Elevation of Privilege** | Command injection via `traceagent wrap -- <cmd...>` | `mcp_tap.py` passes `argv` directly to `asyncio.create_subprocess_exec(*cmd)` without `shell=True`. |
