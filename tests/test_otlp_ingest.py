"""Tests for OTLP HTTP/JSON receiver, normalization, secret redaction, and API endpoints."""

from pathlib import Path

from fastapi.testclient import TestClient

from traceagent.server.app import MAX_OTLP_PAYLOAD_BYTES, create_app


def test_health_endpoint(tmp_path: Path) -> None:
    app = create_app(tmp_path / "ledger.db")
    with TestClient(app) as client:
        resp = client.get("/api/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


def test_otlp_ingest_gen_ai_and_int_coercion(tmp_path: Path) -> None:
    db_path = tmp_path / "ledger.db"
    app = create_app(db_path)

    otlp_payload = {
        "resourceSpans": [
            {
                "resource": {
                    "attributes": [
                        {"key": "service.name", "value": {"stringValue": "my-agent"}}
                    ]
                },
                "scopeSpans": [
                    {
                        "scope": {"name": "opentelemetry.instrumentation.openai"},
                        "spans": [
                            {
                                "traceId": "trace-otlp-001",
                                "spanId": "span-001",
                                "name": "chat gpt-4o",
                                "startTimeUnixNano": "1700000000000000000",
                                "endTimeUnixNano": "1700000000500000000",
                                "status": {"code": 1},
                                "attributes": [
                                    {
                                        "key": "gen_ai.operation.name",
                                        "value": {"stringValue": "chat"},
                                    },
                                    {
                                        "key": "gen_ai.request.model",
                                        "value": {"stringValue": "gpt-4o"},
                                    },
                                    {
                                        "key": "gen_ai.usage.input_tokens",
                                        "value": {"intValue": "120"},
                                    },
                                    {
                                        "key": "gen_ai.usage.output_tokens",
                                        "value": {"intValue": "45"},
                                    },
                                ],
                            }
                        ],
                    }
                ],
            }
        ]
    }

    with TestClient(app) as client:
        ingest_resp = client.post("/v1/traces", json=otlp_payload)
        assert ingest_resp.status_code == 200
        assert ingest_resp.json() == {"status": "ok", "accepted_spans": 1}

        list_resp = client.get("/api/traces")
        assert list_resp.status_code == 200
        traces = list_resp.json()["traces"]
        assert len(traces) == 1
        assert traces[0]["trace_id"] == "trace-otlp-001"
        assert traces[0]["total_in_tokens"] == 120
        assert traces[0]["total_out_tokens"] == 45

        detail_resp = client.get("/api/traces/trace-otlp-001")
        assert detail_resp.status_code == 200
        steps = detail_resp.json()["steps"]
        assert len(steps) == 1
        step = steps[0]
        assert step["op_type"] == "chat"
        assert step["model"] == "gpt-4o"
        assert step["input_tokens"] == 120
        assert step["output_tokens"] == 45
        assert step["duration_ms"] == 500.0
        assert step["status"] == "ok"


def test_otlp_ingest_mcp_normalization_and_redaction(tmp_path: Path) -> None:
    db_path = tmp_path / "ledger.db"
    app = create_app(db_path)

    otlp_payload = {
        "resourceSpans": [
            {
                "resource": {"attributes": []},
                "scopeSpans": [
                    {
                        "scope": {"name": "mcp"},
                        "spans": [
                            {
                                "traceId": "trace-mcp-001",
                                "spanId": "span-mcp-1",
                                "name": "tools/call",
                                "startTimeUnixNano": "1700000001000000000",
                                "endTimeUnixNano": "1700000001100000000",
                                "attributes": [
                                    {
                                        "key": "mcp.tool.name",
                                        "value": {"stringValue": "github_search"},
                                    },
                                    {
                                        "key": "api_key",
                                        "value": {"stringValue": "super-secret-value"},
                                    },
                                    {
                                        "key": "prompt",
                                        "value": {
                                            "stringValue": (
                                                "Use key sk-proj-abcdefghijklmnopqrstuvwxyz1234 "
                                                "and Bearer my-secret-jwt-token"
                                            )
                                        },
                                    },
                                ],
                            }
                        ],
                    }
                ],
            }
        ]
    }

    with TestClient(app) as client:
        resp = client.post("/v1/traces", json=otlp_payload)
        assert resp.status_code == 200

        detail = client.get("/api/traces/trace-mcp-001").json()
        step = detail["steps"][0]
        assert step["op_type"] == "mcp_call"
        payload_json = step["payload_json"]
        assert "super-secret-value" not in payload_json
        assert "sk-proj-abcdefghijklmnopqrstuvwxyz1234" not in payload_json
        assert "my-secret-jwt-token" not in payload_json
        assert "[REDACTED]" in payload_json


def test_otlp_payload_cap_returns_413(tmp_path: Path) -> None:
    app = create_app(tmp_path / "ledger.db")
    oversized = b"{" + b" " * (MAX_OTLP_PAYLOAD_BYTES + 1) + b"}"
    with TestClient(app) as client:
        resp = client.post(
            "/v1/traces",
            content=oversized,
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 413


def test_get_missing_trace_returns_404(tmp_path: Path) -> None:
    app = create_app(tmp_path / "ledger.db")
    with TestClient(app) as client:
        resp = client.get("/api/traces/does-not-exist")
        assert resp.status_code == 404
