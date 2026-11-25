"""Pydantic v2 data contracts for TraceAgent."""

from typing import Any, Literal

from pydantic import BaseModel, Field

TraceSource = Literal["otlp", "mcp_tap", "langgraph", "demo"]
TraceStatus = Literal["running", "ok", "error"]
StepOpType = Literal["invoke_agent", "chat", "execute_tool", "mcp_call"]
StepStatus = Literal["ok", "error"]


class TraceCreate(BaseModel):
    trace_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    source: TraceSource
    status: TraceStatus = "running"
    started_at_ns: int
    ended_at_ns: int | None = None
    total_in_tokens: int = 0
    total_out_tokens: int = 0
    parent_trace_id: str | None = None
    forked_from_seq: int | None = None


class StepInput(BaseModel):
    span_id: str = Field(min_length=1)
    parent_span_id: str | None = None
    op_type: StepOpType
    name: str = Field(min_length=1)
    model: str | None = None
    status: StepStatus = "ok"
    timestamp_ns: int
    duration_ms: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    payload: dict[str, Any] = Field(default_factory=dict)


class StepRecord(BaseModel):
    id: int
    trace_id: str
    seq: int
    span_id: str
    parent_span_id: str | None = None
    op_type: StepOpType
    name: str
    model: str | None = None
    status: StepStatus
    timestamp_ns: int
    duration_ms: float
    input_tokens: int
    output_tokens: int
    payload_json: str
    prev_hash: str
    step_hash: str


class VerifyResult(BaseModel):
    trace_id: str
    valid: bool
    checked_steps: int
    corrupted_seq: int | None = None
    reason: str | None = None
