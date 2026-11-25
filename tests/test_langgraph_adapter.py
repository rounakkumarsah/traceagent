import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from traceagent.adapters.langgraph import TraceAgentCallbackHandler
from traceagent.storage.sqlite_ledger import SQLiteLedger


def test_langgraph_callback_handler_records_steps(tmp_path: Path) -> None:
    db_path = tmp_path / "lg.db"
    handler = TraceAgentCallbackHandler(
        db_path=db_path, trace_id="lg-test-1", trace_name="my-graph"
    )

    # Chain with empty serialized id
    handler.on_chain_start(
        {"id": []},
        {"api_key": "sk-secret123456789012345"},
        run_id="run-chain-1",
    )
    handler.on_llm_start(
        {"name": "ChatOpenAI"},
        ["hello"],
        run_id="run-llm-1",
        parent_run_id="run-chain-1",
        invocation_params={"model_name": "gpt-4o-mini"},
    )
    handler.on_llm_end(
        SimpleNamespace(
            generations=[[{"text": "hi"}]],
            llm_output={"token_usage": {"prompt_tokens": 5, "completion_tokens": 2}},
        ),
        run_id="run-llm-1",
        parent_run_id="run-chain-1",
    )
    handler.on_tool_start(
        {"name": "search"},
        "query",
        run_id="run-tool-1",
        parent_run_id="run-chain-1",
    )
    handler.on_tool_end("result", run_id="run-tool-1", parent_run_id="run-chain-1")
    handler.on_chain_end({"answer": "done"}, run_id="run-chain-1")

    async def _check() -> tuple[list[Any], bool]:
        ledger = SQLiteLedger(db_path)
        steps = await ledger.get_steps("lg-test-1")
        result = await ledger.verify_trace("lg-test-1")
        return steps, result.valid

    steps, ok = asyncio.run(_check())
    assert ok is True
    assert len(steps) == 3
    names = [s.name for s in steps]
    assert names == ["ChatOpenAI", "search", "chain"]
    assert steps[0].input_tokens == 5
    assert steps[0].output_tokens == 2
    payload = json.loads(steps[2].payload_json)
    assert payload["inputs"]["api_key"] == "[REDACTED]"
