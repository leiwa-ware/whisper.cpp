import pytest
from fastapi.testclient import TestClient
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


@pytest.fixture()
def client():
    from main import app
    with TestClient(app) as c:
        yield c


def test_post_minutes_saves_and_returns_id(client):
    payload = {
        "meeting_id": "OPP-0001",
        "source_type": "manual",
        "minutes_markdown": "## 議事録\n\nテスト内容",
        "raw_transcript": "テスト文字起こし",
        "summary_topics": ["テスト議題"],
        "summary_actions": [],
        "summary_risks": [],
    }
    response = client.post("/api/minutes", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert "id" in data
    assert data["meeting_id"] == "OPP-0001"


def test_get_minutes_by_id(client):
    payload = {
        "meeting_id": "OPP-0002",
        "source_type": "manual",
        "minutes_markdown": "## 議事録\n\nGET テスト",
        "raw_transcript": "",
        "summary_topics": [],
        "summary_actions": [],
        "summary_risks": [],
    }
    post_res = client.post("/api/minutes", json=payload)
    created_id = post_res.json()["id"]

    get_res = client.get(f"/api/minutes/{created_id}")
    assert get_res.status_code == 200
    assert get_res.json()["minutes_markdown"] == "## 議事録\n\nGET テスト"


def test_get_minutes_not_found(client):
    response = client.get("/api/minutes/9999")
    assert response.status_code == 404
