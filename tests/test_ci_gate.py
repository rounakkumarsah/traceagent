"""Tests for CI Golden-Trace Regression Gate (`traceagent check`)."""

import json
from pathlib import Path
from typing import Any

from typer.testing import CliRunner

from traceagent.cli import app

runner = CliRunner()


def _write_jsonl(path: Path, steps: list[dict[str, Any]]) -> None:
    lines = [json.dumps(s) for s in steps]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _golden_steps() -> list[dict[str, Any]]:
    return [
        {
            "seq": 0,
            "op_type": "invoke_agent",
            "name": "supervisor",
            "status": "ok",
            "input_tokens": 400,
            "output_tokens": 100,
            "duration_ms": 120.0,
        },
        {
            "seq": 1,
            "op_type": "mcp_call",
            "name": "mcp:get_order_status",
            "status": "ok",
            "input_tokens": 0,
            "output_tokens": 0,
            "duration_ms": 40.0,
        },
        {
            "seq": 2,
            "op_type": "execute_tool",
            "name": "issue_refund",
            "status": "ok",
            "input_tokens": 300,
            "output_tokens": 200,
            "duration_ms": 15.0,
        },
    ]


def test_check_passes_within_budget(tmp_path: Path) -> None:
    golden = tmp_path / "golden.jsonl"
    candidate = tmp_path / "candidate.jsonl"
    _write_jsonl(golden, _golden_steps())

    cand_steps = _golden_steps()
    cand_steps[0]["input_tokens"] = 450  # +50 tokens = +5% (within +15%)
    _write_jsonl(candidate, cand_steps)

    result = runner.invoke(
        app,
        [
            "check",
            "--golden",
            str(golden),
            "--candidate",
            str(candidate),
            "--max-token-increase-pct",
            "15",
            "--max-step-increase",
            "2",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "PASS" in result.output


def test_check_fails_on_token_regression(tmp_path: Path) -> None:
    golden = tmp_path / "golden.jsonl"
    candidate = tmp_path / "candidate.jsonl"
    _write_jsonl(golden, _golden_steps())

    cand_steps = _golden_steps()
    cand_steps[0]["input_tokens"] = 900  # +500 tokens = +50% (exceeds +15%)
    _write_jsonl(candidate, cand_steps)

    result = runner.invoke(
        app,
        [
            "check",
            "--golden",
            str(golden),
            "--candidate",
            str(candidate),
            "--max-token-increase-pct",
            "15",
        ],
    )
    assert result.exit_code == 1
    assert "Max token increase" in result.output


def test_check_fails_on_new_tool_error(tmp_path: Path) -> None:
    golden = tmp_path / "golden.jsonl"
    candidate = tmp_path / "candidate.jsonl"
    _write_jsonl(golden, _golden_steps())

    cand_steps = _golden_steps()
    cand_steps[2]["status"] = "error"
    _write_jsonl(candidate, cand_steps)

    result = runner.invoke(
        app,
        [
            "check",
            "--golden",
            str(golden),
            "--candidate",
            str(candidate),
        ],
    )
    assert result.exit_code == 1
    assert "Zero new error steps" in result.output


def test_check_invalid_input_returns_2(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "check",
            "--golden",
            str(tmp_path / "missing.jsonl"),
            "--candidate",
            str(tmp_path / "also_missing.jsonl"),
        ],
    )
    assert result.exit_code == 2


def test_check_fails_on_missing_required_tool(tmp_path: Path) -> None:
    golden = tmp_path / "golden.jsonl"
    candidate = tmp_path / "candidate.jsonl"
    _write_jsonl(golden, _golden_steps())

    cand_steps = [s for s in _golden_steps() if s["name"] != "issue_refund"]
    _write_jsonl(candidate, cand_steps)

    result = runner.invoke(
        app,
        [
            "check",
            "--golden",
            str(golden),
            "--candidate",
            str(candidate),
        ],
    )
    assert result.exit_code == 1
    assert "Required tool" in result.output
