"""Deterministic stub replay engine ($0.00 token cost) and trajectory diffing."""

import json
from collections.abc import Callable
from typing import Any

from traceagent.models import StepRecord, StepStatus, TrajectoryDiff
from traceagent.storage.sqlite_ledger import canonical_json

ValidatorFn = Callable[[StepRecord, dict[str, Any]], tuple[StepStatus, dict[str, Any]]]

_VALIDATORS: dict[str, ValidatorFn] = {}


def register_validator(step_name: str, fn: ValidatorFn) -> None:
    """Register a deterministic Python validator/handler for a step name."""
    _VALIDATORS[step_name] = fn


def _validate_parse_and_issue_refund(
    step: StepRecord,
    prev_payload: dict[str, Any],
) -> tuple[StepStatus, dict[str, Any]]:
    """Deterministic validator for `parse_and_issue_refund`."""
    raw_output = prev_payload.get("output")
    parsed: dict[str, Any]
    if isinstance(raw_output, str):
        try:
            loaded = json.loads(raw_output)
        except json.JSONDecodeError as exc:
            return (
                "error",
                {
                    "input": {"payment_intent_raw": raw_output},
                    "output": None,
                    "error": f"JSONDecodeError: {exc}",
                },
            )
        if not isinstance(loaded, dict):
            return (
                "error",
                {
                    "input": {"payment_intent_raw": raw_output},
                    "output": None,
                    "error": "TypeError: Expected JSON object for payment intent",
                },
            )
        parsed = loaded
    elif isinstance(raw_output, dict):
        parsed = raw_output
    else:
        return (
            "error",
            {
                "input": {"payment_intent_raw": raw_output},
                "output": None,
                "error": "ValueError: Missing payment intent output from previous step",
            },
        )

    return (
        "ok",
        {
            "input": {"payment_intent_raw": raw_output},
            "output": {
                "refund_issued": True,
                "intent_id": parsed.get("intent_id"),
                "amount_usd": parsed.get("amount_usd"),
            },
            "error": None,
        },
    )


register_validator("parse_and_issue_refund", _validate_parse_and_issue_refund)


def run_deterministic_step(
    step: StepRecord,
    prev_payload: dict[str, Any],
) -> tuple[StepStatus, dict[str, Any]]:
    """Run deterministic validator for a downstream step without calling any LLM."""
    validator = _VALIDATORS.get(step.name)
    if validator is not None:
        return validator(step, prev_payload)

    payload = json.loads(step.payload_json)
    if not isinstance(payload, dict):
        payload = {"value": payload}
    return step.status, payload


def compute_trajectory_diff(
    base_trace_id: str,
    fork_trace_id: str,
    base_steps: list[StepRecord],
    fork_steps: list[StepRecord],
) -> TrajectoryDiff:
    """Compute deterministic TrajectoryDiff between base and forked steps."""
    base_errors = sum(1 for s in base_steps if s.status == "error")
    fork_errors = sum(1 for s in fork_steps if s.status == "error")

    base_status: StepStatus = "ok" if base_errors == 0 else "error"
    fork_status: StepStatus = "ok" if fork_errors == 0 else "error"

    base_latency = sum(s.duration_ms for s in base_steps)
    fork_latency = sum(s.duration_ms for s in fork_steps)

    base_tokens = sum(s.input_tokens + s.output_tokens for s in base_steps)
    fork_tokens = sum(s.input_tokens + s.output_tokens for s in fork_steps)

    changed_seqs: list[int] = []
    max_len = max(len(base_steps), len(fork_steps))
    for idx in range(max_len):
        if idx >= len(base_steps) or idx >= len(fork_steps):
            changed_seqs.append(idx)
            continue
        b = base_steps[idx]
        f = fork_steps[idx]
        b_payload = canonical_json(json.loads(b.payload_json))
        f_payload = canonical_json(json.loads(f.payload_json))
        if b.status != f.status or b_payload != f_payload:
            changed_seqs.append(idx)

    return TrajectoryDiff(
        base_trace_id=base_trace_id,
        fork_trace_id=fork_trace_id,
        base_status=base_status,
        fork_status=fork_status,
        step_count_delta=len(fork_steps) - len(base_steps),
        error_count_delta=fork_errors - base_errors,
        latency_delta_ms=round(fork_latency - base_latency, 3),
        token_delta=fork_tokens - base_tokens,
        changed_seqs=changed_seqs,
    )
