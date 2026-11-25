"""Reproducible offline benchmark for TraceAgent SQLite WAL + SHA-256 + Stub Replay."""

from __future__ import annotations

import asyncio
import platform
import tempfile
import time
from pathlib import Path

from traceagent.models import ForkRequest, StepInput, TraceCreate
from traceagent.replay.forker import fork_trace
from traceagent.storage.sqlite_ledger import SQLiteLedger


def _percentile(sorted_values: list[float], pct: float) -> float:
    if not sorted_values:
        return 0.0
    idx = min(len(sorted_values) - 1, max(0, int(round((pct / 100.0) * (len(sorted_values) - 1)))))
    return sorted_values[idx]


async def run_benchmarks() -> None:
    with tempfile.TemporaryDirectory(prefix="traceagent-bench-") as tmpdir:
        db_path = Path(tmpdir) / "bench.db"
        ledger = SQLiteLedger(db_path)
        await ledger.init_schema()

        # 1. 1,000-step SQLite WAL + SHA-256 write (~1 KB JSON payload each)
        trace_1k = "bench-1000-steps"
        await ledger.create_trace(
            TraceCreate(
                trace_id=trace_1k,
                name="benchmark-1k",
                source="demo",
                status="ok",
                started_at_ns=1_700_000_000_000_000_000,
            )
        )
        pad = "x" * 900
        step_latencies_ms: list[float] = []

        t_write_start = time.perf_counter()
        for seq in range(1000):
            payload = {
                "input": {"seq": seq, "blob": pad},
                "output": {"ok": True, "seq": seq},
                "error": None,
            }
            t0 = time.perf_counter()
            await ledger.append_step(
                trace_1k,
                StepInput(
                    span_id=f"span-{seq}",
                    op_type="execute_tool",
                    name="bench_step",
                    status="ok",
                    timestamp_ns=1_700_000_000_000_000_000 + seq * 1_000_000,
                    duration_ms=1.0,
                    input_tokens=10,
                    output_tokens=5,
                    payload=payload,
                ),
            )
            step_latencies_ms.append((time.perf_counter() - t0) * 1000.0)
        total_write_s = time.perf_counter() - t_write_start

        sorted_lat = sorted(step_latencies_ms)
        p50_ms = _percentile(sorted_lat, 50.0)
        p95_ms = _percentile(sorted_lat, 95.0)
        steps_per_sec = 1000.0 / total_write_s if total_write_s > 0 else 0.0

        # 2. Full 1,000-step SHA-256 chain verification from genesis
        t_verify_start = time.perf_counter()
        verify_res = await ledger.verify_trace(trace_1k)
        verify_ms = (time.perf_counter() - t_verify_start) * 1000.0
        if not verify_res.valid or verify_res.checked_steps != 1000:
            raise RuntimeError(f"Chain verification failed: {verify_res}")

        # 3. 20-step Mode-1 deterministic stub replay + diff from Step 14
        trace_20 = "bench-20-steps"
        await ledger.create_trace(
            TraceCreate(
                trace_id=trace_20,
                name="benchmark-20",
                source="demo",
                status="ok",
                started_at_ns=1_700_000_000_000_000_000,
            )
        )
        for seq in range(20):
            name = "parse_and_issue_refund" if seq == 15 else "bench_step"
            payload = (
                {"input": {"step": seq}, "output": '{"intent_id":"pi_1","amount_usd":10}'}
                if seq == 14
                else {"input": {"step": seq}, "output": {"ok": True}, "error": None}
            )
            await ledger.append_step(
                trace_20,
                StepInput(
                    span_id=f"span20-{seq}",
                    op_type="execute_tool",
                    name=name,
                    status="ok",
                    timestamp_ns=1_700_000_000_000_000_000 + seq * 1_000_000,
                    duration_ms=1.0,
                    input_tokens=20,
                    output_tokens=10,
                    payload=payload,
                ),
            )

        t_fork_start = time.perf_counter()
        fork_res = await fork_trace(
            ledger,
            trace_20,
            ForkRequest(
                fork_at_seq=14,
                mode="stub_replay",
                override_payload={"output": '{"intent_id":"pi_1","amount_usd":25}'},
            ),
        )
        fork_ms = (time.perf_counter() - t_fork_start) * 1000.0
        if fork_res.tokens_burned != 0:
            raise RuntimeError(
                f"Expected 0 tokens burned in stub_replay, got {fork_res.tokens_burned}"
            )

    cpu_info = platform.processor() or platform.machine() or "unknown"
    print(
        f"**Environment:** Python {platform.python_version()} | "
        f"{platform.system()} {platform.release()} | CPU: `{cpu_info}`\n"
    )
    print("| Benchmark | Workload | Measured Result |")
    print("| :--- | :--- | :--- |")
    print(
        f"| **SQLite WAL + SHA-256 Write** | 1,000 sequential steps (`~1 KB` JSON each) | "
        f"P50: `{p50_ms:.2f} ms/step`, P95: `{p95_ms:.2f} ms/step`, `{steps_per_sec:.0f} steps/sec` |"
    )
    print(
        f"| **Full Audit Chain Verification** | Verify SHA-256 chain from genesis (1,000 steps) | "
        f"`{verify_ms:.2f} ms` |"
    )
    print(
        f"| **Mode 1 Deterministic Stub Replay** | Fork & diff 20-step trajectory from Step 14 | "
        f"`{fork_ms:.2f} ms` (`$0.00` / `0` tokens burned) |"
    )


if __name__ == "__main__":
    asyncio.run(run_benchmarks())
