"""Pydantic v2 data contracts for TraceAgent."""

from typing import Any, Literal

from pydantic import BaseModel, Field

TraceSource = Literal["otlp", "mcp_tap", "langgraph", "demo", "stub_replay", "live_fork"]
TraceStatus = Literal["running", "ok", "error"]
StepOpType = Literal["invoke_agent", "chat", "execute_tool", "mcp_call"]
StepStatus = Literal["ok", "error"]
ReplayMode = Literal["stub_replay", "live_fork"]


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


class ForkRequest(BaseModel):
    fork_at_seq: int = Field(ge=0)
    override_payload: dict[str, Any]
    mode: ReplayMode = "stub_replay"
    live_runner_url: str | None = None
    live_runner_model: str | None = None


class TrajectoryDiff(BaseModel):
    base_trace_id: str
    fork_trace_id: str
    base_status: StepStatus
    fork_status: StepStatus
    step_count_delta: int
    error_count_delta: int
    latency_delta_ms: float
    token_delta: int
    changed_seqs: list[int]


class ForkResult(BaseModel):
    fork_id: str
    parent_trace_id: str
    fork_trace_id: str
    fork_at_seq: int
    mode: ReplayMode
    replay_mode_label: str
    tokens_burned: int
    prefix_tokens_saved: int
    replay_duration_ms: float = 0.0
    diff: TrajectoryDiff
