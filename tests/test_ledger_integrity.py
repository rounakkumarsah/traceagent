"""Ledger integrity and SHA-256 hash-chain tests."""

import asyncio
import sqlite3
from pathlib import Path

from typer.testing import CliRunner

from traceagent.cli import app
from traceagent.models import StepInput, TraceCreate
from traceagent.storage.sqlite_ledger import SQLiteLedger


def _make_trace(trace_id: str = "trace-001") -> TraceCreate:
    return TraceCreate(
        trace_id=trace_id,
        name="test-agent",
        source="demo",
        status="running",
        started_at_ns=1_700_000_000_000_000_000,
    )


def _make_step(seq_hint: int, payload: dict[str, object] | None = None) -> StepInput:
    return StepInput(
        span_id=f"span-{seq_hint:04d}",
        op_type="chat",
        name=f"step-{seq_hint}",
        model="gpt-4o-mini",
        status="ok",
        timestamp_ns=1_700_000_000_000_000_000 + seq_hint * 1_000_000,
        duration_ms=12.5,
        input_tokens=10,
        output_tokens=5,
        payload=payload if payload is not None else {"input": f"prompt-{seq_hint}", "output": "ok"},
    )


async def test_wal_pragmas_active(tmp_path: Path) -> None:
    db_path = tmp_path / "ledger.db"
    ledger = SQLiteLedger(db_path)
    await ledger.init_schema()

    conn = await ledger._connect()
    try:
        cur_wal = await conn.execute("PRAGMA journal_mode;")
        wal_row = await cur_wal.fetchone()
        assert wal_row is not None
        assert str(wal_row[0]).lower() == "wal"

        cur_fk = await conn.execute("PRAGMA foreign_keys;")
        fk_row = await cur_fk.fetchone()
        assert fk_row is not None
        assert int(fk_row[0]) == 1
    finally:
        await conn.close()


async def test_hash_chain_valid_across_100_steps(tmp_path: Path) -> None:
    db_path = tmp_path / "ledger.db"
    ledger = SQLiteLedger(db_path)
    await ledger.init_schema()
    await ledger.create_trace(_make_trace("trace-100"))

    for i in range(100):
        await ledger.append_step("trace-100", _make_step(i))

    result = await ledger.verify_trace("trace-100")
    assert result.valid is True
    assert result.checked_steps == 100
    assert result.corrupted_seq is None


async def test_tamper_detection_catches_single_byte_edit(tmp_path: Path) -> None:
    db_path = tmp_path / "ledger.db"
    ledger = SQLiteLedger(db_path)
    await ledger.init_schema()
    await ledger.create_trace(_make_trace("trace-tamper"))

    for i in range(10):
        await ledger.append_step("trace-tamper", _make_step(i))

    # Directly tamper with seq = 4 in SQLite
    with sqlite3.connect(db_path) as raw_conn:
        raw_conn.execute(
            "UPDATE steps SET payload_json = ? WHERE trace_id = ? AND seq = ?",
            ('{"input":"prompt-4","output":"TAMPERED"}', "trace-tamper", 4),
        )
        raw_conn.commit()

    result = await ledger.verify_trace("trace-tamper")
    assert result.valid is False
    assert result.corrupted_seq == 4


async def test_canonical_json_key_order_stability(tmp_path: Path) -> None:
    db_path = tmp_path / "ledger.db"
    ledger = SQLiteLedger(db_path)
    await ledger.init_schema()
    await ledger.create_trace(_make_trace("trace-a"))
    await ledger.create_trace(_make_trace("trace-b"))

    step_a = await ledger.append_step("trace-a", _make_step(0, payload={"b": 1, "a": 2}))
    step_b = await ledger.append_step("trace-b", _make_step(0, payload={"a": 2, "b": 1}))

    assert step_a.payload_json == step_b.payload_json
    assert step_a.step_hash == step_b.step_hash


def test_cli_verify_exit_codes(tmp_path: Path) -> None:
    db_path = tmp_path / "ledger.db"

    async def _setup() -> None:
        ledger = SQLiteLedger(db_path)
        await ledger.init_schema()
        await ledger.create_trace(_make_trace("trace-cli"))
        for i in range(6):
            await ledger.append_step("trace-cli", _make_step(i))

    asyncio.run(_setup())

    runner = CliRunner()
    ok_res = runner.invoke(app, ["verify", "trace-cli", "--db", str(db_path)])
    assert ok_res.exit_code == 0
    assert "VALID" in ok_res.output

    with sqlite3.connect(db_path) as raw_conn:
        raw_conn.execute(
            "UPDATE steps SET payload_json = ? WHERE trace_id = ? AND seq = ?",
            ('{"tampered":true}', "trace-cli", 3),
        )
        raw_conn.commit()

    bad_res = runner.invoke(app, ["verify", "trace-cli", "--db", str(db_path)])
    assert bad_res.exit_code == 1
    assert "corrupted_seq=3" in bad_res.output
