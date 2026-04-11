"""API server integration tests using FastAPI TestClient."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    """Create a test client with the FastAPI app."""
    import os
    for key in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GOOGLE_API_KEY"):
        os.environ.pop(key, None)

    from agent_platform.api.server import app
    with TestClient(app) as c:
        yield c


def test_health_endpoint(client: TestClient):
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"


def test_list_models(client: TestClient):
    resp = client.get("/models")
    assert resp.status_code == 200
    models = resp.json()
    assert len(models) > 0
    assert all("model_id" in m for m in models)


def test_list_harnesses(client: TestClient):
    resp = client.get("/harnesses")
    assert resp.status_code == 200
    harnesses = resp.json()
    assert len(harnesses) >= 2
    ids = {h["harness_id"] for h in harnesses}
    assert "react" in ids
    assert "plan_execute" in ids


def test_list_tools(client: TestClient):
    resp = client.get("/tools")
    assert resp.status_code == 200
    tools = resp.json()
    assert len(tools) > 0
    names = {t["name"] for t in tools}
    assert "read_file" in names
    assert "execute_command" in names


def test_create_and_get_session(client: TestClient):
    # Create
    resp = client.post("/sessions", json={"harness_id": "react"})
    assert resp.status_code == 200
    data = resp.json()
    session_id = data["session_id"]
    assert data["harness_id"] == "react"
    assert data["status"] == "idle"

    # Get
    resp = client.get(f"/sessions/{session_id}")
    assert resp.status_code == 200
    assert resp.json()["session_id"] == session_id

    # List
    resp = client.get("/sessions")
    assert resp.status_code == 200
    assert session_id in resp.json()

    # Delete
    resp = client.delete(f"/sessions/{session_id}")
    assert resp.status_code == 200


def test_get_nonexistent_session(client: TestClient):
    resp = client.get("/sessions/nonexistent123")
    assert resp.status_code == 404


def test_create_session_invalid_harness(client: TestClient):
    resp = client.post("/sessions", json={"harness_id": "nonexistent"})
    assert resp.status_code == 400
