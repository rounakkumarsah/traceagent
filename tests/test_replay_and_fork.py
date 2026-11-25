"""Tests for Two-Mode Replay & Fork Engine and offline 7-step demo fixture."""

from pathlib import Path

from fastapi.testclient import TestClient

from traceagent.demo.seed_demo import DEMO_TRACE_ID, seed_demo_trace
from traceagent.server.app import create_app
from traceagent.storage.sqlite_ledger import SQLiteLedger


async def test_demo_seed_fails_at_step_6_and_stub_fork_passes(tmp_path: Path) -> None:
    db_path = tmp_path / "demo_fork.db"
    ledger = SQLiteLedger(db_path)
    await ledger.init_schema()
    await seed_demo_trace(ledger)

    base_steps = await ledger.get_steps(DEMO_TRACE_ID)
    assert len(base_steps) == 7
    assert base_steps[5].status == "ok"
    assert base_steps[6].status == "error"

    app = create_app(db_path)
    with TestClient(app) as client:
        resp = client.post(
            f"/api/traces/{DEMO_TRACE_ID}/fork",
            json={
                "fork_at_seq": 5,
                "mode": "stub_replay",
                "override_payload": {
                    "output": {"intent_id": "pi_8821", "amount_usd": 49.0},
                },
            },
        )

    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["mode"] == "stub_replay"
    assert data["tokens_burned"] == 0
    assert data["prefix_tokens_saved"] > 0
    assert data["replay_duration_ms"] >= 0.0
    assert data["diff"]["base_status"] == "error"
    assert data["diff"]["fork_status"] == "ok"
    assert data["diff"]["error_count_delta"] == -1
    assert data["diff"]["changed_seqs"] == [5, 6]

    fork_trace_id = data["fork_trace_id"]
    verify_result = await ledger.verify_trace(fork_trace_id)
    assert verify_result.valid is True
    assert verify_result.checked_steps == 7


async def test_live_fork_without_provider_returns_400(tmp_path: Path) -> None:
    db_path = tmp_path / "live_fork.db"
    ledger = SQLiteLedger(db_path)
    await ledger.init_schema()
    await seed_demo_trace(ledger)

    app = create_app(db_path)
    with TestClient(app) as client:
        resp = client.post(
            f"/api/traces/{DEMO_TRACE_ID}/fork",
            json={
                "fork_at_seq": 5,
                "mode": "live_fork",
                "override_payload": {
                    "output": {"intent_id": "pi_8821", "amount_usd": 49.0},
                },
            },
        )

    assert resp.status_code == 400
    assert "stub_replay" in resp.json()["detail"]


async def test_fork_out_of_bounds_and_missing_trace_errors(tmp_path: Path) -> None:
    db_path = tmp_path / "bounds_fork.db"
    ledger = SQLiteLedger(db_path)
    await ledger.init_schema()
    await seed_demo_trace(ledger)

    app = create_app(db_path)
    with TestClient(app) as client:
        resp_missing = client.post(
            "/api/traces/does-not-exist/fork",
            json={"fork_at_seq": 0, "mode": "stub_replay", "override_payload": {}},
        )
        assert resp_missing.status_code == 404

        resp_neg = client.post(
            f"/api/traces/{DEMO_TRACE_ID}/fork",
            json={"fork_at_seq": -1, "mode": "stub_replay", "override_payload": {}},
        )
        assert resp_neg.status_code == 422

        resp_oob = client.post(
            f"/api/traces/{DEMO_TRACE_ID}/fork",
            json={"fork_at_seq": 7, "mode": "stub_replay", "override_payload": {}},
        )
        assert resp_oob.status_code == 400


async def test_live_fork_with_concrete_runner(tmp_path: Path) -> None:
    from typing import Any

    from traceagent.models import ForkRequest, StepInput, StepRecord
    from traceagent.replay.forker import fork_trace

    class MockLiveRunner:
        async def run_downstream(
            self,
            base_steps: list[StepRecord],
            fork_at_seq: int,
            mutated_payload: dict[str, Any],
            model: str | None = None,
            url: str | None = None,
        ) -> tuple[list[StepInput], int]:
            step = StepInput(
                trace_id=base_steps[0].trace_id,
                span_id="sp-live-006",
                op_type="execute_tool",
                name="parse_and_issue_refund",
                status="ok",
                timestamp_ns=1_000_000,
                duration_ms=1.0,
                input_tokens=10,
                output_tokens=20,
                payload={"output": {"refunded": True}},
            )
            return [step], 30

    db_path = tmp_path / "mock_live.db"
    ledger = SQLiteLedger(db_path)
    await ledger.init_schema()
    await seed_demo_trace(ledger)

    result = await fork_trace(
        ledger,
        DEMO_TRACE_ID,
        ForkRequest(
            fork_at_seq=5,
            mode="live_fork",
            override_payload={"output": {"intent_id": "pi_8821", "amount_usd": 49.0}},
        ),
        live_runner=MockLiveRunner(),
    )
    assert result.mode == "live_fork"
    assert result.tokens_burned == 30
    assert result.diff.fork_status == "ok"
    verify = await ledger.verify_trace(result.fork_trace_id)
    assert verify.valid is True
