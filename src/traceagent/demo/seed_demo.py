"""Offline 7-step demo fixture: order-refund-agent crashing at Seq 6."""

from traceagent.models import StepInput, TraceCreate
from traceagent.storage.sqlite_ledger import SQLiteLedger

DEMO_TRACE_ID = "demo-langgraph-mcp-001"
BASE_TS_NS = 1_732_492_800_000_000_000


def build_demo_steps() -> list[StepInput]:
    """Build the deterministic 7-step demo trajectory."""
    malformed_json = '{"intent_id": "pi_8821", "amount_usd": "49.00'
    return [
        StepInput(
            span_id="sp-000",
            parent_span_id=None,
            op_type="invoke_agent",
            name="refund_supervisor",
            model="gemini-2.5-flash",
            status="ok",
            timestamp_ns=BASE_TS_NS,
            duration_ms=120.0,
            input_tokens=380,
            output_tokens=75,
            payload={
                "input": {"message": "Refund order ORD-9042, arrived damaged"},
                "output": {"route": "planner_node"},
                "error": None,
            },
        ),
        StepInput(
            span_id="sp-001",
            parent_span_id="sp-000",
            op_type="chat",
            name="planner_node",
            model="gemini-2.5-flash",
            status="ok",
            timestamp_ns=BASE_TS_NS + 120_000_000,
            duration_ms=185.0,
            input_tokens=490,
            output_tokens=110,
            payload={
                "input": {"order_id": "ORD-9042"},
                "output": {"next_tool": "mcp:get_order_status"},
                "error": None,
            },
        ),
        StepInput(
            span_id="sp-002",
            parent_span_id="sp-001",
            op_type="mcp_call",
            name="mcp:get_order_status",
            model=None,
            status="ok",
            timestamp_ns=BASE_TS_NS + 305_000_000,
            duration_ms=42.0,
            input_tokens=0,
            output_tokens=0,
            payload={
                "input": {"order_id": "ORD-9042"},
                "output": {
                    "order_id": "ORD-9042",
                    "status": "delivered",
                    "days_since_delivery": 5,
                },
                "error": None,
            },
        ),
        StepInput(
            span_id="sp-003",
            parent_span_id="sp-000",
            op_type="chat",
            name="policy_evaluator",
            model="gemini-2.5-flash",
            status="ok",
            timestamp_ns=BASE_TS_NS + 347_000_000,
            duration_ms=210.0,
            input_tokens=620,
            output_tokens=130,
            payload={
                "input": {"days_since_delivery": 5},
                "output": {"next_tool": "mcp:check_refund_eligibility"},
                "error": None,
            },
        ),
        StepInput(
            span_id="sp-004",
            parent_span_id="sp-003",
            op_type="mcp_call",
            name="mcp:check_refund_eligibility",
            model=None,
            status="ok",
            timestamp_ns=BASE_TS_NS + 557_000_000,
            duration_ms=38.0,
            input_tokens=0,
            output_tokens=0,
            payload={
                "input": {"order_id": "ORD-9042", "days_since_delivery": 5},
                "output": {"eligible": True, "reason": "within_30_day_window"},
                "error": None,
            },
        ),
        StepInput(
            span_id="sp-005",
            parent_span_id="sp-000",
            op_type="mcp_call",
            name="mcp:fetch_payment_intent",
            model=None,
            status="ok",
            timestamp_ns=BASE_TS_NS + 595_000_000,
            duration_ms=45.0,
            input_tokens=0,
            output_tokens=0,
            payload={
                "input": {"order_id": "ORD-9042"},
                "output": malformed_json,
                "error": None,
            },
        ),
        StepInput(
            span_id="sp-006",
            parent_span_id="sp-000",
            op_type="execute_tool",
            name="parse_and_issue_refund",
            model=None,
            status="error",
            timestamp_ns=BASE_TS_NS + 640_000_000,
            duration_ms=3.0,
            input_tokens=0,
            output_tokens=0,
            payload={
                "input": {"payment_intent_raw": malformed_json},
                "output": None,
                "error": (
                    "JSONDecodeError: Unterminated string starting at: "
                    "line 1 column 36 (char 35)"
                ),
            },
        ),
    ]


async def seed_demo_trace(ledger: SQLiteLedger, force: bool = False) -> str:
    """Seed the 7-step offline demo trace into the ledger if not already present."""
    existing = await ledger.get_trace(DEMO_TRACE_ID)
    if existing is not None and not force:
        return DEMO_TRACE_ID

    if existing is None:
        await ledger.ensure_trace(
            TraceCreate(
                trace_id=DEMO_TRACE_ID,
                name="order-refund-agent",
                source="demo",
                status="error",
                started_at_ns=BASE_TS_NS,
            )
        )
        for step in build_demo_steps():
            await ledger.append_step(DEMO_TRACE_ID, step)

    return DEMO_TRACE_ID
