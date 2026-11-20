"""Integration tests for FastAPI endpoints: chat, reset, health, rate limiting, and limits."""

from unittest.mock import AsyncMock
import pytest
from starlette.testclient import TestClient

from app.main import app, rate_limiter, agent


@pytest.fixture
def client():
    # Reset rate limiter before tests
    rate_limiter.reset()
    return TestClient(app)


def test_health_endpoint(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "model" in data
    assert "configured" in data


def test_serve_index(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Company Researcher Chat" in response.text


def test_chat_message_length_limit(client):
    # Over 2000 characters
    long_msg = "x" * 2001
    response = client.post(
        "/api/chat",
        json={"session_id": "test_len", "message": long_msg},
    )
    assert response.status_code == 400
    assert "2000 characters" in response.json()["detail"]


def test_chat_rate_limiting(client):
    # Set limit to 2 for this test
    original_limit = rate_limiter.limit
    rate_limiter.limit = 2
    rate_limiter.reset("testclient")

    try:
        # Request 1 & 2 pass rate limit
        res1 = client.post("/api/chat", json={"session_id": "s1", "message": "hello"})
        assert res1.status_code in (200, 400)

        res2 = client.post("/api/chat", json={"session_id": "s1", "message": "hello again"})
        assert res2.status_code in (200, 400)

        # Request 3 must trigger 429
        res3 = client.post("/api/chat", json={"session_id": "s1", "message": "third message"})
        assert res3.status_code == 429
        assert "Rate limit exceeded" in res3.json()["detail"]
    finally:
        rate_limiter.limit = original_limit
        rate_limiter.reset()


def test_chat_endpoint_successful_routing(client, monkeypatch):
    mock_process = AsyncMock(return_value=("**Company:** Systems Limited\nTest report", "Systems Limited"))
    monkeypatch.setattr(agent, "process_message", mock_process)

    response = client.post(
        "/api/chat",
        json={"session_id": "s_api", "message": "systemsltd.com"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["company"] == "Systems Limited"
    assert "Systems Limited" in data["reply"]


def test_reset_endpoint(client):
    # Populate a session
    agent.get_or_create_session("s_reset").company_name = "Stripe"

    response = client.post(
        "/api/reset",
        json={"session_id": "s_reset"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "reset"

    session = agent.sessions.get("s_reset")
    assert session is not None
    assert session.company_name is None
    assert session.website_text is None
