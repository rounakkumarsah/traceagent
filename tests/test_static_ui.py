"""Tests for bundled static UI serving in FastAPI."""

from pathlib import Path

from fastapi.testclient import TestClient

from traceagent.server.app import create_app


def test_static_ui_root_returns_html(tmp_path: Path) -> None:
    static_index = (
        Path(__file__).resolve().parent.parent / "src" / "traceagent" / "static" / "index.html"
    )
    assert static_index.is_file(), f"Missing bundled static UI at {static_index}"

    app = create_app(db_path=tmp_path / "test_static.db")
    with TestClient(app) as client:
        resp = client.get("/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")
        assert "<html" in resp.text.lower()

        # Verify API routes are not shadowed by StaticFiles
        health = client.get("/api/health")
        assert health.status_code == 200
        assert health.json() == {"status": "ok"}
