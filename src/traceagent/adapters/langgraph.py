"""1-line LangGraph callback adapter for TraceAgent.

Usage:
    from traceagent.adapters.langgraph import TraceAgentCallbackHandler
    graph.invoke(inputs, config={"callbacks": [TraceAgentCallbackHandler()]})
"""

import asyncio
import time
import uuid
from pathlib import Path
from typing import Any

from traceagent.ingest.redactor import redact_secrets
from traceagent.models import StepInput, StepOpType, StepStatus, TraceCreate
from traceagent.storage.sqlite_ledger import SQLiteLedger


class TraceAgentCallbackHandler:
    """Drop-in LangGraph / LangChain callback handler that records steps to SQLiteLedger."""

    def __init__(
        self,
        db_path: str | Path = "traceagent.db",
        trace_id: str | None = None,
        trace_name: str = "langgraph",
    ) -> None:
        self.ledger = SQLiteLedger(db_path)
        self.trace_id = trace_id or f"lg-{uuid.uuid4().hex[:16]}"
        self.trace_name = trace_name
        self._initialized = False
        self._active_runs: dict[str, tuple[int, str, StepOpType, str | None, dict[str, Any]]] = {}

    def _run_async(self, coro: Any) -> None:
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(coro)
        except RuntimeError:
            asyncio.run(coro)

    async def _record_step(self, step: StepInput) -> None:
        if not self._initialized:
            await self.ledger.init_schema()
            await self.ledger.ensure_trace(
                TraceCreate(
                    trace_id=self.trace_id,
                    name=self.trace_name,
                    source="langgraph",
                    status="ok",
                    started_at_ns=step.timestamp_ns,
                )
            )
            self._initialized = True
        await self.ledger.append_step(self.trace_id, step)

    def _start_run(
        self,
        run_id: Any,
        name: str,
        op_type: StepOpType,
        model: str | None = None,
        inputs: Any = None,
    ) -> None:
        rid = str(run_id)
        self._active_runs[rid] = (
            time.time_ns(),
            name,
            op_type,
            model,
            {"inputs": redact_secrets(inputs)},
        )

    def _end_run(
        self,
        run_id: Any,
        parent_run_id: Any = None,
        status: StepStatus = "ok",
        outputs: Any = None,
        input_tokens: int = 0,
        output_tokens: int = 0,
    ) -> None:
        rid = str(run_id)
        entry = self._active_runs.pop(rid, None)
        end_ns = time.time_ns()
        if entry is None:
            start_ns = end_ns
            name = "unknown"
            op_type: StepOpType = "invoke_agent"
            model = None
            payload: dict[str, Any] = {}
        else:
            start_ns, name, op_type, model, payload = entry

        payload["outputs"] = redact_secrets(outputs)
        duration_ms = max(0.0, (end_ns - start_ns) / 1_000_000.0)
        step = StepInput(
            span_id=rid,
            parent_span_id=str(parent_run_id) if parent_run_id is not None else None,
            op_type=op_type,
            name=name,
            model=model,
            status=status,
            timestamp_ns=start_ns,
            duration_ms=duration_ms,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            payload=payload,
        )
        self._run_async(self._record_step(step))

    def on_chain_start(
        self,
        serialized: dict[str, Any],
        inputs: dict[str, Any],
        *,
        run_id: Any,
        parent_run_id: Any = None,
        **kwargs: Any,
    ) -> None:
        raw_id = serialized.get("id") if isinstance(serialized, dict) else None
        fallback_name = raw_id[-1] if isinstance(raw_id, list) and raw_id else "chain"
        explicit_name = serialized.get("name") if isinstance(serialized, dict) else None
        name = str(explicit_name or fallback_name)
        self._start_run(run_id, name, "invoke_agent", inputs=inputs)

    def on_chain_end(
        self,
        outputs: dict[str, Any],
        *,
        run_id: Any,
        parent_run_id: Any = None,
        **kwargs: Any,
    ) -> None:
        self._end_run(run_id, parent_run_id=parent_run_id, status="ok", outputs=outputs)

    def on_llm_start(
        self,
        serialized: dict[str, Any],
        prompts: list[str],
        *,
        run_id: Any,
        parent_run_id: Any = None,
        **kwargs: Any,
    ) -> None:
        model = serialized.get("kwargs", {}).get("model_name") or serialized.get("name")
        self._start_run(
            run_id,
            str(model or "llm"),
            "chat",
            model=str(model) if model else None,
            inputs={"prompts": prompts},
        )

    def on_llm_end(
        self,
        response: Any,
        *,
        run_id: Any,
        parent_run_id: Any = None,
        **kwargs: Any,
    ) -> None:
        llm_output = getattr(response, "llm_output", None)
        if not isinstance(llm_output, dict) and isinstance(response, dict):
            llm_output = response.get("llm_output")
        token_usage = llm_output.get("token_usage") if isinstance(llm_output, dict) else None
        in_tok = token_usage.get("prompt_tokens", 0) if isinstance(token_usage, dict) else 0
        out_tok = token_usage.get("completion_tokens", 0) if isinstance(token_usage, dict) else 0
        input_tokens = int(in_tok)
        output_tokens = int(out_tok)
        self._end_run(
            run_id,
            parent_run_id=parent_run_id,
            status="ok",
            outputs=str(response),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

    def on_llm_error(
        self,
        error: BaseException,
        *,
        run_id: Any,
        parent_run_id: Any = None,
        **kwargs: Any,
    ) -> None:
        self._end_run(run_id, parent_run_id=parent_run_id, status="error", outputs=str(error))

    def on_tool_start(
        self,
        serialized: dict[str, Any],
        input_str: str,
        *,
        run_id: Any,
        parent_run_id: Any = None,
        **kwargs: Any,
    ) -> None:
        name = str(serialized.get("name") or "tool")
        self._start_run(run_id, name, "execute_tool", inputs={"input": input_str})

    def on_tool_end(
        self,
        output: Any,
        *,
        run_id: Any,
        parent_run_id: Any = None,
        **kwargs: Any,
    ) -> None:
        self._end_run(run_id, parent_run_id=parent_run_id, status="ok", outputs=str(output))

    def on_tool_error(
        self,
        error: BaseException,
        *,
        run_id: Any,
        parent_run_id: Any = None,
        **kwargs: Any,
    ) -> None:
        self._end_run(run_id, parent_run_id=parent_run_id, status="error", outputs=str(error))
