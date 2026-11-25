"""Append-only SQLite WAL ledger with SHA-256 hash chain."""

import asyncio
import hashlib
import json
import logging
from pathlib import Path
from typing import Any

import aiosqlite

from traceagent.models import StepInput, StepRecord, TraceCreate, VerifyResult

logger = logging.getLogger(__name__)

GENESIS_HASH = "0" * 64

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS traces (
    trace_id         TEXT PRIMARY KEY,
    name             TEXT NOT NULL,
    source           TEXT NOT NULL,
    status           TEXT NOT NULL,
    started_at_ns    INTEGER NOT NULL,
    ended_at_ns      INTEGER,
    total_in_tokens  INTEGER NOT NULL DEFAULT 0,
    total_out_tokens INTEGER NOT NULL DEFAULT 0,
    parent_trace_id  TEXT REFERENCES traces(trace_id),
    forked_from_seq  INTEGER
);

CREATE TABLE IF NOT EXISTS steps (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    trace_id        TEXT NOT NULL REFERENCES traces(trace_id) ON DELETE CASCADE,
    seq             INTEGER NOT NULL,
    span_id         TEXT NOT NULL,
    parent_span_id  TEXT,
    op_type         TEXT NOT NULL,
    name            TEXT NOT NULL,
    model           TEXT,
    status          TEXT NOT NULL,
    timestamp_ns    INTEGER NOT NULL,
    duration_ms     REAL NOT NULL DEFAULT 0.0,
    input_tokens    INTEGER NOT NULL DEFAULT 0,
    output_tokens   INTEGER NOT NULL DEFAULT 0,
    payload_json    TEXT NOT NULL,
    prev_hash       TEXT NOT NULL,
    step_hash       TEXT NOT NULL,
    UNIQUE(trace_id, seq)
);

CREATE INDEX IF NOT EXISTS idx_steps_trace_seq ON steps(trace_id, seq);

CREATE TABLE IF NOT EXISTS forks (
    fork_id         TEXT PRIMARY KEY,
    parent_trace_id TEXT NOT NULL REFERENCES traces(trace_id) ON DELETE CASCADE,
    child_trace_id  TEXT NOT NULL REFERENCES traces(trace_id) ON DELETE CASCADE,
    forked_from_seq INTEGER NOT NULL,
    created_at_ns   INTEGER NOT NULL
);
"""


def canonical_json(payload: Any) -> str:
    """Serialize payload deterministically for cryptographic hashing."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def compute_step_hash(
    prev_hash: str,
    seq: int,
    timestamp_ns: int,
    canonical_payload: str,
) -> str:
    """Compute SHA-256 hash for a ledger step."""
    raw = f"{prev_hash}|{seq}|{timestamp_ns}|{canonical_payload}".encode()
    return hashlib.sha256(raw).hexdigest()


class SQLiteLedger:
    """Async SQLite WAL ledger with cryptographic hash-chain verification."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self._write_lock = asyncio.Lock()

    async def _connect(self) -> aiosqlite.Connection:
        conn = await aiosqlite.connect(self.db_path)
        await conn.execute("PRAGMA journal_mode=WAL;")
        await conn.execute("PRAGMA synchronous=NORMAL;")
        await conn.execute("PRAGMA foreign_keys=ON;")
        await conn.execute("PRAGMA busy_timeout=5000;")
        conn.row_factory = aiosqlite.Row
        return conn

    async def init_schema(self) -> None:
        """Initialize database tables and indexes."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = await self._connect()
        try:
            await conn.executescript(SCHEMA_SQL)
            await conn.commit()
            logger.info("Initialized SQLite WAL schema", extra={"db_path": str(self.db_path)})
        finally:
            await conn.close()

    async def create_trace(self, trace: TraceCreate) -> None:
        """Insert a new trace record."""
        async with self._write_lock:
            conn = await self._connect()
            try:
                await conn.execute(
                    """
                    INSERT INTO traces (
                        trace_id, name, source, status, started_at_ns, ended_at_ns,
                        total_in_tokens, total_out_tokens, parent_trace_id, forked_from_seq
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        trace.trace_id,
                        trace.name,
                        trace.source,
                        trace.status,
                        trace.started_at_ns,
                        trace.ended_at_ns,
                        trace.total_in_tokens,
                        trace.total_out_tokens,
                        trace.parent_trace_id,
                        trace.forked_from_seq,
                    ),
                )
                await conn.commit()
            finally:
                await conn.close()

    async def append_step(self, trace_id: str, step: StepInput) -> StepRecord:
        """Append a step to a trace, chaining its SHA-256 hash to the previous step."""
        payload_str = canonical_json(step.payload)
        async with self._write_lock:
            conn = await self._connect()
            try:
                cursor = await conn.execute(
                    "SELECT seq, step_hash FROM steps WHERE trace_id = ? ORDER BY seq DESC LIMIT 1",
                    (trace_id,),
                )
                row = await cursor.fetchone()
                if row is None:
                    seq = 0
                    prev_hash = GENESIS_HASH
                else:
                    seq = int(row["seq"]) + 1
                    prev_hash = str(row["step_hash"])

                step_hash = compute_step_hash(prev_hash, seq, step.timestamp_ns, payload_str)

                insert_cursor = await conn.execute(
                    """
                    INSERT INTO steps (
                        trace_id, seq, span_id, parent_span_id, op_type, name, model,
                        status, timestamp_ns, duration_ms, input_tokens, output_tokens,
                        payload_json, prev_hash, step_hash
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        trace_id,
                        seq,
                        step.span_id,
                        step.parent_span_id,
                        step.op_type,
                        step.name,
                        step.model,
                        step.status,
                        step.timestamp_ns,
                        step.duration_ms,
                        step.input_tokens,
                        step.output_tokens,
                        payload_str,
                        prev_hash,
                        step_hash,
                    ),
                )
                row_id = insert_cursor.lastrowid
                assert row_id is not None

                await conn.execute(
                    """
                    UPDATE traces
                    SET total_in_tokens = total_in_tokens + ?,
                        total_out_tokens = total_out_tokens + ?
                    WHERE trace_id = ?
                    """,
                    (step.input_tokens, step.output_tokens, trace_id),
                )
                await conn.commit()

                return StepRecord(
                    id=row_id,
                    trace_id=trace_id,
                    seq=seq,
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
                    payload_json=payload_str,
                    prev_hash=prev_hash,
                    step_hash=step_hash,
                )
            finally:
                await conn.close()

    async def verify_trace(self, trace_id: str) -> VerifyResult:
        """Verify the cryptographic hash chain for a trace."""
        conn = await self._connect()
        try:
            cursor = await conn.execute(
                """
                SELECT seq, timestamp_ns, payload_json, prev_hash, step_hash
                FROM steps
                WHERE trace_id = ?
                ORDER BY seq ASC
                """,
                (trace_id,),
            )
            rows = await cursor.fetchall()
        finally:
            await conn.close()

        expected_prev_hash = GENESIS_HASH
        checked = 0

        for expected_seq, row in enumerate(rows):
            seq = int(row["seq"])
            timestamp_ns = int(row["timestamp_ns"])
            payload_json = str(row["payload_json"])
            prev_hash = str(row["prev_hash"])
            step_hash = str(row["step_hash"])

            if seq != expected_seq:
                return VerifyResult(
                    trace_id=trace_id,
                    valid=False,
                    checked_steps=checked,
                    corrupted_seq=expected_seq,
                    reason=f"Sequence mismatch: expected {expected_seq}, got {seq}",
                )

            if prev_hash != expected_prev_hash:
                return VerifyResult(
                    trace_id=trace_id,
                    valid=False,
                    checked_steps=checked,
                    corrupted_seq=seq,
                    reason="prev_hash mismatch",
                )

            expected_hash = compute_step_hash(prev_hash, seq, timestamp_ns, payload_json)
            if step_hash != expected_hash:
                return VerifyResult(
                    trace_id=trace_id,
                    valid=False,
                    checked_steps=checked,
                    corrupted_seq=seq,
                    reason="step_hash mismatch",
                )

            checked += 1
            expected_prev_hash = step_hash

        return VerifyResult(
            trace_id=trace_id,
            valid=True,
            checked_steps=checked,
        )

    async def list_trace_ids(self) -> list[str]:
        """Return all trace_ids in the ledger."""
        conn = await self._connect()
        try:
            cursor = await conn.execute("SELECT trace_id FROM traces ORDER BY started_at_ns ASC")
            rows = await cursor.fetchall()
            return [str(row["trace_id"]) for row in rows]
        finally:
            await conn.close()

    async def ensure_trace(self, trace: TraceCreate) -> None:
        """Insert a trace record if it does not already exist."""
        async with self._write_lock:
            conn = await self._connect()
            try:
                await conn.execute(
                    """
                    INSERT OR IGNORE INTO traces (
                        trace_id, name, source, status, started_at_ns, ended_at_ns,
                        total_in_tokens, total_out_tokens, parent_trace_id, forked_from_seq
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        trace.trace_id,
                        trace.name,
                        trace.source,
                        trace.status,
                        trace.started_at_ns,
                        trace.ended_at_ns,
                        trace.total_in_tokens,
                        trace.total_out_tokens,
                        trace.parent_trace_id,
                        trace.forked_from_seq,
                    ),
                )
                await conn.commit()
            finally:
                await conn.close()

    async def list_traces(self, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        """Return trace summaries ordered by most recent first."""
        conn = await self._connect()
        try:
            cursor = await conn.execute(
                """
                SELECT trace_id, name, source, status, started_at_ns, ended_at_ns,
                       total_in_tokens, total_out_tokens, parent_trace_id, forked_from_seq
                FROM traces
                ORDER BY started_at_ns DESC
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            )
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]
        finally:
            await conn.close()

    async def get_trace(self, trace_id: str) -> dict[str, Any] | None:
        """Return a single trace summary or None if not found."""
        conn = await self._connect()
        try:
            cursor = await conn.execute(
                """
                SELECT trace_id, name, source, status, started_at_ns, ended_at_ns,
                       total_in_tokens, total_out_tokens, parent_trace_id, forked_from_seq
                FROM traces
                WHERE trace_id = ?
                """,
                (trace_id,),
            )
            row = await cursor.fetchone()
            return dict(row) if row is not None else None
        finally:
            await conn.close()

    async def get_steps(self, trace_id: str) -> list[StepRecord]:
        """Return all steps for a trace ordered by seq."""
        conn = await self._connect()
        try:
            cursor = await conn.execute(
                """
                SELECT id, trace_id, seq, span_id, parent_span_id, op_type, name, model,
                       status, timestamp_ns, duration_ms, input_tokens, output_tokens,
                       payload_json, prev_hash, step_hash
                FROM steps
                WHERE trace_id = ?
                ORDER BY seq ASC
                """,
                (trace_id,),
            )
            rows = await cursor.fetchall()
            return [
                StepRecord(
                    id=int(row["id"]),
                    trace_id=str(row["trace_id"]),
                    seq=int(row["seq"]),
                    span_id=str(row["span_id"]),
                    parent_span_id=row["parent_span_id"],
                    op_type=row["op_type"],
                    name=str(row["name"]),
                    model=row["model"],
                    status=row["status"],
                    timestamp_ns=int(row["timestamp_ns"]),
                    duration_ms=float(row["duration_ms"]),
                    input_tokens=int(row["input_tokens"]),
                    output_tokens=int(row["output_tokens"]),
                    payload_json=str(row["payload_json"]),
                    prev_hash=str(row["prev_hash"]),
                    step_hash=str(row["step_hash"]),
                )
                for row in rows
            ]
        finally:
            await conn.close()
