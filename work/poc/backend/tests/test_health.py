import pytest
from fastapi.testclient import TestClient


def test_health_returns_ok():
    from main import app
    client = TestClient(app)
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
