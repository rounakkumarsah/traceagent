"""Two-mode trace forking engine (Mode 1: stub_replay, Mode 2: live_fork)."""

import json
import time
import uuid
from typing import Any, Protocol

from traceagent.models import (
    ForkRequest,
    ForkResult,
    StepInput,
    StepRecord,
    StepStatus,
    TraceCreate,
)
from traceagent.replay.stub_replay import compute_trajectory_diff, run_deterministic_step
from traceagent.storage.sqlite_ledger import SQLiteLedger


class TraceNotFoundError(Exception):
    """Raised when the base trace does not exist."""


class InvalidForkSeqError(Exception):
    """Raised when fork_at_seq is out of bounds."""


class LiveRunnerNotConfiguredError(Exception):
    """Raised when mode='live_fork' is requested without a configured live runner."""


class LiveRunner(Protocol):
    """Pluggable interface for Mode 2 live LLM downstream execution."""

    async def run_downstream(
        self,
        base_steps: list[StepRecord],
        fork_at_seq: int,
        mutated_payload: dict[str, Any],
        model: str | None = None,
        url: str | None = None,
    ) -> tuple[list[StepInput], int]:
        """Execute steps after fork_at_seq and return (new_steps, tokens_burned)."""
        ...


def _apply_override(
    original_payload: dict[str, Any],
    override_payload: dict[str, Any],
) -> dict[str, Any]:
    """Apply override_payload to a step's payload."""
    merged = dict(original_payload)
    if any(k in override_payload for k in ("input", "output", "error")):
        for key in ("input", "output", "error"):
            if key in override_payload:
                merged[key] = override_payload[key]
    else:
        merged["output"] = override_payload
    return merged


async def fork_trace(
    ledger: SQLiteLedger,
    trace_id: str,
    request: ForkRequest,
    live_runner: LiveRunner | None = None,
) -> ForkResult:
    """Fork a trace at `fork_at_seq` in either `stub_replay` or `live_fork` mode."""
    t0 = time.perf_counter()

    base_trace = await ledger.get_trace(trace_id)
    if base_trace is None:
        raise TraceNotFoundError(f"Trace not found: {trace_id}")

    base_steps = await ledger.get_steps(trace_id)
    if request.fork_at_seq < 0 or request.fork_at_seq >= len(base_steps):
        raise InvalidForkSeqError(
            f"fork_at_seq={request.fork_at_seq} out of range [0, {len(base_steps) - 1}]"
        )

    if request.mode == "live_fork" and live_runner is None:
        raise LiveRunnerNotConfiguredError(
            "No live LLM runner is configured. Use mode='stub_replay' for $0.00 "
            "deterministic replay, or configure a LiveRunner."
        )

    fork_id = uuid.uuid4().hex[:12]
    fork_trace_id = f"{trace_id}-fork-{fork_id[:6]}"
    prefix_tokens_saved = sum(
        s.input_tokens + s.output_tokens for s in base_steps[: request.fork_at_seq]
    )

    await ledger.ensure_trace(
        TraceCreate(
            trace_id=fork_trace_id,
            name=f"{base_trace['name']} (fork@{request.fork_at_seq})",
            source=request.mode,
            status="running",
            started_at_ns=int(time.time_ns()),
            parent_trace_id=trace_id,
            forked_from_seq=request.fork_at_seq,
        )
    )

    # 1. Copy prefix steps 0 .. fork_at_seq - 1 verbatim (fresh SHA-256 chain)
    for step in base_steps[: request.fork_at_seq]:
        await ledger.append_step(
            fork_trace_id,
            StepInput(
                span_id=step.span_id,
                parent_span_id=step.parent_span_id,
                op_type=step.op_type,
                name=step.name,
                model=step.model,
                status=step.status,
                timestamp_ns=step.timestamp_ns,
                duration_ms=step.duration_ms,
                input_tokens=step.input_tokens,
                output_tokens=step.output_tokens,
                payload=json.loads(step.payload_json),
            ),
        )

    # 2. Apply override at fork_at_seq
    fork_step_base = base_steps[request.fork_at_seq]
    orig_payload = json.loads(fork_step_base.payload_json)
    mutated_payload = _apply_override(orig_payload, request.override_payload)
    fork_step_status: StepStatus = "error" if mutated_payload.get("error") else "ok"

    await ledger.append_step(
        fork_trace_id,
        StepInput(
            span_id=fork_step_base.span_id,
            parent_span_id=fork_step_base.parent_span_id,
            op_type=fork_step_base.op_type,
            name=fork_step_base.name,
            model=fork_step_base.model,
            status=fork_step_status,
            timestamp_ns=fork_step_base.timestamp_ns,
            duration_ms=fork_step_base.duration_ms,
            input_tokens=fork_step_base.input_tokens,
            output_tokens=fork_step_base.output_tokens,
            payload=mutated_payload,
        ),
    )

    # 3. Execute downstream steps
    tokens_burned = 0
    if request.mode == "stub_replay":
        prev_payload = mutated_payload
        for step in base_steps[request.fork_at_seq + 1 :]:
            new_status, new_payload = run_deterministic_step(step, prev_payload)
            await ledger.append_step(
                fork_trace_id,
                StepInput(
                    span_id=step.span_id,
                    parent_span_id=step.parent_span_id,
                    op_type=step.op_type,
                    name=step.name,
                    model=step.model,
                    status=new_status,
                    timestamp_ns=step.timestamp_ns,
                    duration_ms=step.duration_ms,
                    input_tokens=0,
                    output_tokens=0,
                    payload=new_payload,
                ),
            )
            prev_payload = new_payload
        replay_mode_label = "deterministic_stub"
    else:
        assert live_runner is not None
        downstream_steps, tokens_burned = await live_runner.run_downstream(
            base_steps=base_steps,
            fork_at_seq=request.fork_at_seq,
            mutated_payload=mutated_payload,
            model=request.live_runner_model,
            url=request.live_runner_url,
        )
        for ds in downstream_steps:
            await ledger.append_step(fork_trace_id, ds)
        replay_mode_label = "live_fork"

    fork_steps = await ledger.get_steps(fork_trace_id)
    diff = compute_trajectory_diff(
        base_trace_id=trace_id,
        fork_trace_id=fork_trace_id,
        base_steps=base_steps,
        fork_steps=fork_steps,
    )

    replay_duration_ms = round((time.perf_counter() - t0) * 1000.0, 3)

    return ForkResult(
        fork_id=fork_id,
        parent_trace_id=trace_id,
        fork_trace_id=fork_trace_id,
        fork_at_seq=request.fork_at_seq,
        mode=request.mode,
        replay_mode_label=replay_mode_label,
        tokens_burned=tokens_burned,
        prefix_tokens_saved=prefix_tokens_saved,
        replay_duration_ms=replay_duration_ms,
        diff=diff,
    )
