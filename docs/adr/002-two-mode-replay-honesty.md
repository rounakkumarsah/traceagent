# ADR-002: Two-Mode Replay Honesty

## Status
Accepted

## Context
Many agent replay tools conflate deterministic stubbed re-execution with live LLM re-generation, leading to misleading "$0.00 live LLM" claims or silent network calls during offline debugging.

## Decision
Strictly separate replay into two explicit modes:
1. **Mode 1 (`stub_replay` — $0.00):** Replays cached steps and re-runs deterministic Python validators/parsers/routers from `fork_at_seq` onward with `0` tokens burned.
2. **Mode 2 (`live_fork`):** Replays steps `0..N-1` at `$0.00` from the ledger and invokes a configured real/local LLM provider only from Step `N` onward. Calling `live_fork` without a configured provider fails explicitly with HTTP `400`.

## Consequences
- Epistemic honesty in UI, CLI, and API contracts.
- 100% deterministic offline CI testing.
