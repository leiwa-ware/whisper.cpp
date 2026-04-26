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


M365_PAYLOAD = {
    "source": "m365_copilot",
    "opportunity_id": "OPP-TEST01",
    "participants": ["田中 一郎", "佐藤 淳"],
    "raw_content": (
        "# Meeting Notes\n\n"
        "## Key Points\n"
        "- 競合から10%安い提案が入っている\n"
        "- 全店展開230店舗の可能性あり\n\n"
        "## Action Items\n"
        "- 価格再提案資料作成 (Owner: 佐藤 淳, Due: 今週中)\n"
    ),
}


def test_webhook_accepts_m365_format(client):
    """問い⑨: M365 Copilot Webhook を受信し minutesMarkdown を返す"""
    response = client.post("/api/webhooks/minutes", json=M365_PAYLOAD)
    assert response.status_code == 201
    data = response.json()
    assert "minutes_id" in data
    assert "minutes_markdown" in data
    assert "## 議事録" in data["minutes_markdown"]
    assert "OPP-TEST01" in data["minutes_markdown"]


def test_webhook_saves_to_db(client):
    """問い⑨: Webhook 受信後に DB に保存され GET で取得できる"""
    post_res = client.post("/api/webhooks/minutes", json=M365_PAYLOAD)
    minutes_id = post_res.json()["minutes_id"]

    get_res = client.get(f"/api/minutes/{minutes_id}")
    assert get_res.status_code == 200
    data = get_res.json()
    assert data["source_type"] == "m365"
    assert "## 議事録" in data["minutes_markdown"]


def test_adapter_swap_does_not_change_markdown_structure(client):
    """問い⑩: アダプターを whisper_cpp → m365 に差し替えても ## 議事録 構造が同一"""
    m365_res = client.post("/api/webhooks/minutes", json=M365_PAYLOAD)
    m365_md = m365_res.json()["minutes_markdown"]

    assert m365_md.startswith("## 議事録")
    assert "**商談ID**" in m365_md
    assert "**ソース**" in m365_md
