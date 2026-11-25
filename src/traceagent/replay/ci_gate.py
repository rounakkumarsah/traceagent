"""CI Golden-Trace Regression Gate (`traceagent check`)."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class InvalidTraceFileError(Exception):
    """Raised when a golden or candidate JSONL file is missing or malformed."""


@dataclass(frozen=True)
class GateFailure:
    rule: str
    golden_value: str
    candidate_value: str
    offending_seq: str


@dataclass(frozen=True)
class GateResult:
    passed: bool
    failures: list[GateFailure]
    golden_steps: int
    candidate_steps: int
    golden_tokens: int
    candidate_tokens: int
    golden_errors: int
    candidate_errors: int


def load_jsonl_steps(path: Path) -> list[dict[str, Any]]:
    """Load and validate a JSONL trace file."""
    if not path.is_file():
        raise InvalidTraceFileError(f"File not found: {path}")

    steps: list[dict[str, Any]] = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise InvalidTraceFileError(f"Cannot read {path}: {exc}") from exc

    for line_no, raw_line in enumerate(text.splitlines(), start=1):
        stripped = raw_line.strip()
        if not stripped:
            continue
        try:
            obj = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise InvalidTraceFileError(
                f"Malformed JSON in {path} at line {line_no}: {exc}"
            ) from exc
        if not isinstance(obj, dict):
            raise InvalidTraceFileError(
                f"Expected JSON object in {path} at line {line_no}"
            )
        steps.append(obj)

    if not steps:
        raise InvalidTraceFileError(f"Trace file is empty: {path}")

    return steps


def evaluate_ci_gate(
    golden_path: Path,
    candidate_path: Path,
    max_token_increase_pct: float = 15.0,
    max_step_increase: int = 2,
) -> GateResult:
    """Evaluate candidate JSONL trace against golden baseline."""
    golden = load_jsonl_steps(golden_path)
    candidate = load_jsonl_steps(candidate_path)

    golden_errors = [s for s in golden if s.get("status") == "error"]
    candidate_errors = [s for s in candidate if s.get("status") == "error"]

    golden_tokens = sum(
        int(s.get("input_tokens", 0)) + int(s.get("output_tokens", 0)) for s in golden
    )
    candidate_tokens = sum(
        int(s.get("input_tokens", 0)) + int(s.get("output_tokens", 0)) for s in candidate
    )

    failures: list[GateFailure] = []

    # 1. Zero new error steps
    if len(candidate_errors) > len(golden_errors):
        err_seqs = ",".join(str(s.get("seq", "?")) for s in candidate_errors)
        failures.append(
            GateFailure(
                rule="Zero new error steps",
                golden_value=str(len(golden_errors)),
                candidate_value=str(len(candidate_errors)),
                offending_seq=err_seqs,
            )
        )

    # 2. Step count budget
    max_allowed_steps = len(golden) + max_step_increase
    if len(candidate) > max_allowed_steps:
        failures.append(
            GateFailure(
                rule=f"Max step increase (+{max_step_increase})",
                golden_value=str(len(golden)),
                candidate_value=str(len(candidate)),
                offending_seq=f">={max_allowed_steps}",
            )
        )

    # 3. Token budget
    max_allowed_tokens = golden_tokens * (1.0 + max_token_increase_pct / 100.0)
    if candidate_tokens > max_allowed_tokens:
        failures.append(
            GateFailure(
                rule=f"Max token increase (+{max_token_increase_pct:.1f}%)",
                golden_value=str(golden_tokens),
                candidate_value=str(candidate_tokens),
                offending_seq="all",
            )
        )

    # 4. Required tool names still invoked
    golden_tools = {
        str(s.get("name"))
        for s in golden
        if s.get("op_type") in ("execute_tool", "mcp_call") and s.get("name")
    }
    candidate_tools = {
        str(s.get("name"))
        for s in candidate
        if s.get("op_type") in ("execute_tool", "mcp_call") and s.get("name")
    }
    missing_tools = sorted(golden_tools - candidate_tools)
    if missing_tools:
        failures.append(
            GateFailure(
                rule="Required tools invoked",
                golden_value=", ".join(sorted(golden_tools)),
                candidate_value=f"missing: {', '.join(missing_tools)}",
                offending_seq="n/a",
            )
        )

    return GateResult(
        passed=len(failures) == 0,
        failures=failures,
        golden_steps=len(golden),
        candidate_steps=len(candidate),
        golden_tokens=golden_tokens,
        candidate_tokens=candidate_tokens,
        golden_errors=len(golden_errors),
        candidate_errors=len(candidate_errors),
    )
