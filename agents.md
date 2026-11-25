# TraceAgent — Engineering Constitution & AI IDE Rules (`AGENTS.md`)

All code contributions (human or AI-assisted in Antigravity IDE) MUST obey these hard invariants. Any PR or generated module violating these rules must be rejected and rewritten before proceeding.

---

## 1. Zero-Slop & Epistemic Honesty Rules
- **No Fake "$0.00 Live LLM" Claims:** Strictly separate **Mode 1 (Deterministic Stub Replay — $0.00 token cost, re-runs Python parsing/routing/validation against cached outputs)** from **Mode 2 (Time-Travel Live Fork from Step N — replays Steps `1..N-1` at $0.00 and calls a real/local LLM only from Step `N` onward)**. Never blur these two modes in UI labels, CLI output, or docs.
- **No Fabricated Benchmarks:** Never hardcode latency or token numbers in README or tests. All published numbers MUST come directly from running `scripts/benchmark_replay.py` on disk.
- **No Unimplemented Stubs in Main:** Do not leave `TODO`, `pass`, or fake `return {"status": "ok"}` endpoints. Every route and CLI subcommand must execute real logic backed by tests.

## 2. Backend & Concurrency Invariants (Python 3.12+ / FastAPI)
- **No Blocking I/O on the Async Event Loop:** Never run blocking `sqlite3` writes or synchronous HTTP calls directly inside `async def` FastAPI route handlers. Use `aiosqlite` (or `asyncio.to_thread` with a bounded lock/writer queue) for SQLite WAL access.
- **SQLite WAL Discipline:** Every connection MUST execute:
  - `PRAGMA journal_mode=WAL;`
  - `PRAGMA synchronous=NORMAL;`
  - `PRAGMA foreign_keys=ON;`
  - `PRAGMA busy_timeout=5000;`
- **Strict Pydantic v2 Contracts:** Validate all OTLP payloads, fork requests, and diff responses via Pydantic v2 models (`ConfigDict(extra="ignore")` on OTLP ingest for forward compatibility; strict validation on internal APIs).
- **Structured Logging Only:** Zero `print()` debugging in `src/traceagent/` (CLI user output must use `rich` / `typer.echo`; internal logs must use `logging` with structured fields).

## 3. Cryptographic Audit Chain Invariant
- **Canonical Serialization:** Hash inputs MUST serialize payloads via `json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)` so key ordering never breaks verification across Python versions or OSes.
- **Genesis Hash:** Step `seq = 0` uses `prev_hash = "0" * 64`.
- **Tamper Detection Test Mandatory:** Every change to `sqlite_ledger.py` must pass a test that directly runs `UPDATE steps SET payload_json = ...` in SQLite and asserts `verify_trace()` returns `valid=False` with the exact corrupted `seq`.

## 4. Packaging & Zero-Friction UX Invariant
- **Single-Command Offline Demo:** `traceagent demo` MUST work with **zero environment variables, zero API keys, zero Docker, and zero Node.js installed** on the user's machine.
- **Bundled Static Frontend:** Next.js 15 is built with `output: "export"` into `src/traceagent/static/` and mounted via FastAPI `StaticFiles(html=True)`. No separate frontend server is required at runtime.

## 5. Mandatory Verification Before Finishing Any Task
Run and confirm exit code `0` before marking any milestone complete:
```bash
ruff check src tests
mypy src
pytest -v
```
- All tests in `tests/` MUST be 100% deterministic and offline (no live OpenAI/Gemini/Anthropic network calls in CI).
- Never weaken or delete an existing test to make CI pass.
