"""FastAPI application for OTLP ingestion and TraceAgent API."""

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from traceagent.ingest.otlp_parser import parse_otlp_traces
from traceagent.models import ForkRequest
from traceagent.replay.forker import (
    InvalidForkSeqError,
    LiveRunnerNotConfiguredError,
    TraceNotFoundError,
    fork_trace,
)
from traceagent.storage.sqlite_ledger import SQLiteLedger

MAX_OTLP_PAYLOAD_BYTES = 10 * 1024 * 1024  # 10 MB


def create_app(db_path: str | Path = "traceagent.db") -> FastAPI:
    """Create and configure the TraceAgent FastAPI application."""
    ledger = SQLiteLedger(db_path)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        await ledger.init_schema()
        yield

    app = FastAPI(title="TraceAgent", version="0.1.0", lifespan=lifespan)
    app.state.ledger = ledger

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/v1/traces")
    async def ingest_otlp_traces(request: Request) -> JSONResponse:
        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                if int(content_length) > MAX_OTLP_PAYLOAD_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail=f"Payload exceeds {MAX_OTLP_PAYLOAD_BYTES} bytes limit",
                    )
            except ValueError:
                pass

        body = await request.body()
        if len(body) > MAX_OTLP_PAYLOAD_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"Payload exceeds {MAX_OTLP_PAYLOAD_BYTES} bytes limit",
            )

        try:
            payload: Any = json.loads(body)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail=f"Invalid JSON: {exc}") from exc

        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="OTLP payload must be a JSON object")

        items = parse_otlp_traces(payload)
        for trace_create, step_input in items:
            await ledger.ensure_trace(trace_create)
            await ledger.append_step(trace_create.trace_id, step_input)

        return JSONResponse(
            status_code=200,
            content={"status": "ok", "accepted_spans": len(items)},
        )

    @app.get("/api/traces")
    async def list_traces(limit: int = 100, offset: int = 0) -> dict[str, Any]:
        traces = await ledger.list_traces(limit=limit, offset=offset)
        return {"traces": traces}

    @app.get("/api/traces/{trace_id}")
    async def get_trace(trace_id: str) -> dict[str, Any]:
        trace = await ledger.get_trace(trace_id)
        if trace is None:
            raise HTTPException(status_code=404, detail=f"Trace not found: {trace_id}")
        steps = await ledger.get_steps(trace_id)
        return {
            "trace": trace,
            "steps": [step.model_dump() for step in steps],
        }

    @app.post("/api/traces/{trace_id}/fork", status_code=201)
    async def fork_trace_endpoint(trace_id: str, request: ForkRequest) -> dict[str, Any]:
        try:
            result = await fork_trace(ledger, trace_id, request)
        except TraceNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (InvalidForkSeqError, LiveRunnerNotConfiguredError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return result.model_dump()

    return app
