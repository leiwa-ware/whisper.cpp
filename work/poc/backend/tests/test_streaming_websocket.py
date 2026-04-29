"""Integration tests for /api/ws/transcribe WebSocket endpoint.

whisper-server is mocked at the helper boundary (_transcribe_chunk_bytes)
so these tests don't need an actual whisper subprocess. Real audio→text
verification belongs in tests/test_transcription.py.
"""
import json

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch):
    """FastAPI TestClient with _transcribe_chunk_bytes patched.

    The patched helper returns scripted text per call, driven by the
    `script` list set on each test. This lets us simulate sentence-end
    or non-sentence-end transcripts deterministically.
    """
    from api import realtime as realtime_mod
    from main import app

    script: list[str] = []

    async def fake_transcribe(audio_bytes, filename_hint, initial_prompt):
        if not script:
            return "", True
        return script.pop(0), True

    monkeypatch.setattr(realtime_mod, "_transcribe_chunk_bytes", fake_transcribe)
    c = TestClient(app)
    c._script = script  # attach for test access
    return c


def _recv_event(ws) -> dict:
    raw = ws.receive_text()
    return json.loads(raw)


def test_websocket_emits_ready_on_connect(client):
    with client.websocket_connect("/api/ws/transcribe") as ws:
        ev = _recv_event(ws)
        assert ev == {"type": "ready"}


def test_websocket_emits_partial_for_non_sentence_end(client):
    client._script.extend(["途中の発話"])
    with client.websocket_connect("/api/ws/transcribe") as ws:
        assert _recv_event(ws)["type"] == "ready"
        ws.send_bytes(b"<fake-audio>")
        ev = _recv_event(ws)
        assert ev["type"] == "partial"
        assert ev["text"] == "途中の発話"


def test_websocket_emits_final_on_sentence_end(client):
    client._script.extend(["会議を始めます。"])
    with client.websocket_connect("/api/ws/transcribe") as ws:
        assert _recv_event(ws)["type"] == "ready"
        ws.send_bytes(b"<fake-audio>")
        ev = _recv_event(ws)
        assert ev["type"] == "final"
        assert ev["text"] == "会議を始めます。"


def test_websocket_accumulates_partials_then_final(client):
    client._script.extend(["今日のテーマは", "売上の確認です。"])
    with client.websocket_connect("/api/ws/transcribe") as ws:
        assert _recv_event(ws)["type"] == "ready"

        ws.send_bytes(b"<chunk1>")
        e1 = _recv_event(ws)
        assert e1["type"] == "partial"
        assert "今日のテーマは" in e1["text"]

        ws.send_bytes(b"<chunk2>")
        e2 = _recv_event(ws)
        assert e2["type"] == "final"
        assert "今日のテーマは" in e2["text"]
        assert "売上の確認です。" in e2["text"]


def test_websocket_close_control_finalizes_pending_partial(client):
    client._script.extend(["途中で切れた発話"])
    with client.websocket_connect("/api/ws/transcribe") as ws:
        assert _recv_event(ws)["type"] == "ready"

        ws.send_bytes(b"<chunk>")
        assert _recv_event(ws)["type"] == "partial"

        ws.send_text(json.dumps({"type": "close"}))
        ev = _recv_event(ws)
        assert ev["type"] == "final"
        assert ev["text"] == "途中で切れた発話"


def test_websocket_close_with_no_pending_emits_nothing_then_disconnects(client):
    client._script.extend(["完結しました"])
    with client.websocket_connect("/api/ws/transcribe") as ws:
        assert _recv_event(ws)["type"] == "ready"

        ws.send_bytes(b"<chunk>")
        assert _recv_event(ws)["type"] == "final"  # ですました finalizes immediately

        ws.send_text(json.dumps({"type": "close"}))
        # No pending → no final event. Connection closes.


def test_websocket_invalid_json_returns_error_and_keeps_connection(client):
    with client.websocket_connect("/api/ws/transcribe") as ws:
        assert _recv_event(ws)["type"] == "ready"

        ws.send_text("{not valid json")
        ev = _recv_event(ws)
        assert ev["type"] == "error"
        assert "invalid JSON" in ev["message"]


def test_websocket_unknown_control_returns_error(client):
    with client.websocket_connect("/api/ws/transcribe") as ws:
        assert _recv_event(ws)["type"] == "ready"

        ws.send_text(json.dumps({"type": "unknown"}))
        ev = _recv_event(ws)
        assert ev["type"] == "error"
        assert "unknown control" in ev["message"]


def test_websocket_config_updates_initial_prompt_for_next_chunk(client, monkeypatch):
    """Verify config message's initial_prompt is forwarded into transcribe call."""
    from api import realtime as realtime_mod

    captured_prompts: list[str] = []

    async def fake_transcribe(audio_bytes, filename_hint, initial_prompt):
        captured_prompts.append(initial_prompt)
        return "発話途中", True  # partial

    monkeypatch.setattr(realtime_mod, "_transcribe_chunk_bytes", fake_transcribe)

    with client.websocket_connect("/api/ws/transcribe") as ws:
        assert _recv_event(ws)["type"] == "ready"

        ws.send_text(json.dumps({"type": "config", "initial_prompt": "物流会議。ピッキング、棚卸しについて。"}))
        ws.send_bytes(b"<chunk>")
        _recv_event(ws)  # consume partial

        assert len(captured_prompts) == 1
        assert "物流会議" in captured_prompts[0]


def test_websocket_chunk_inheritance_passes_prior_text_as_prompt(client, monkeypatch):
    """Second chunk's initial_prompt must include text from the first chunk."""
    from api import realtime as realtime_mod

    captured_prompts: list[str] = []
    texts = ["昨日の在庫確認", "を完了しました。"]

    async def fake_transcribe(audio_bytes, filename_hint, initial_prompt):
        captured_prompts.append(initial_prompt)
        return texts.pop(0), True

    monkeypatch.setattr(realtime_mod, "_transcribe_chunk_bytes", fake_transcribe)

    with client.websocket_connect("/api/ws/transcribe") as ws:
        assert _recv_event(ws)["type"] == "ready"
        ws.send_bytes(b"<c1>")
        _recv_event(ws)  # partial
        ws.send_bytes(b"<c2>")
        _recv_event(ws)  # final

        assert len(captured_prompts) == 2
        assert captured_prompts[0] == ""  # first chunk: no prior context
        assert "昨日の在庫確認" in captured_prompts[1]  # second: inherits prior partial


def test_websocket_whisper_unavailable_emits_error(client, monkeypatch):
    """When whisper-server returns available=False, surface as error event."""
    from api import realtime as realtime_mod

    async def fake_transcribe(audio_bytes, filename_hint, initial_prompt):
        return "", False

    monkeypatch.setattr(realtime_mod, "_transcribe_chunk_bytes", fake_transcribe)

    with client.websocket_connect("/api/ws/transcribe") as ws:
        assert _recv_event(ws)["type"] == "ready"
        ws.send_bytes(b"<chunk>")
        ev = _recv_event(ws)
        assert ev["type"] == "error"
        assert "unavailable" in ev["message"]
