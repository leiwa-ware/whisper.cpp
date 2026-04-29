"""Realtime transcription endpoints.

Two paths share the whisper-server /inference call via _transcribe_chunk_bytes:
- POST /api/transcribe-chunk  (legacy, stateless): returns interim text per chunk.
- WS   /api/ws/transcribe     (new):              streams partial/final events.

The WebSocket session maintains StreamingSession state across chunks for
context inheritance (initial_prompt) and partial→final commit transitions.
See work/UIMock/2026-04-29-revised-plan.md §7 for the UI contract.
"""
import asyncio
import json
import logging
import tempfile
from pathlib import Path
from typing import Optional

import httpx
from fastapi import APIRouter, File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect

from config import WHISPER_MODEL, WHISPER_SERVER_PORT
from services.prompt_safety import safe_prompt_for_model
from services.streaming_session import StreamingSession
from services.transcription import _to_16k_wav

router = APIRouter()
_log = logging.getLogger("uvicorn.error")


async def _transcribe_chunk_bytes(
    audio_bytes: bytes,
    filename_hint: str,
    initial_prompt: str,
) -> tuple[str, bool]:
    """Convert chunk bytes → 16kHz WAV → whisper-server /inference.

    Returns (text, available). available=False when whisper-server is
    unreachable or slow (caller should treat as transient).
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        src = Path(tmpdir) / (filename_hint or "chunk.webm")
        src.write_bytes(audio_bytes)

        try:
            wav_path = await asyncio.to_thread(_to_16k_wav, str(src), tmpdir)
        except Exception as e:
            raise HTTPException(status_code=422, detail=f"Audio conversion failed: {e}")

        url = f"http://127.0.0.1:{WHISPER_SERVER_PORT}/inference"
        form: dict = {"language": "ja", "response_format": "json"}
        if initial_prompt:
            form["initial_prompt"] = initial_prompt

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                with open(wav_path, "rb") as f:
                    r = await client.post(
                        url,
                        files={"file": ("audio.wav", f, "audio/wav")},
                        data=form,
                    )
        except (httpx.ConnectError, httpx.TimeoutException):
            return "", False

        if r.status_code != 200:
            raise HTTPException(status_code=502, detail=f"whisper-server: {r.text[:200]}")

        return r.json().get("text", "").strip(), True


@router.post("/transcribe-chunk")
async def transcribe_chunk(
    audio: UploadFile = File(...),
    initial_prompt: str = "",
):
    """Legacy stateless chunk endpoint. Kept for backward compatibility with
    meeting.html's existing chunked POST flow. New clients should use the
    /ws/transcribe WebSocket for partial/final events."""
    try:
        text, available = await _transcribe_chunk_bytes(
            await audio.read(),
            audio.filename or "chunk.webm",
            initial_prompt,
        )
    except HTTPException:
        raise
    if not available:
        return {"text": "", "available": False}
    return {"text": text, "available": True}


@router.websocket("/ws/transcribe")
async def ws_transcribe(websocket: WebSocket):
    """Streaming endpoint with partial/final two-stage output.

    Protocol:
      Client → Server
        - text JSON {"type":"config","initial_prompt":"<base prompt>"}
        - binary audio chunk (webm/ogg/wav, any ffmpeg-decodable)
        - text JSON {"type":"close"} for graceful close

      Server → Client
        - {"type":"ready"} on accept
        - {"type":"partial","text":"<accumulated>"}
        - {"type":"final","text":"<sentence>"}
        - {"type":"error","message":"..."} for transient errors
    """
    await websocket.accept()
    session = StreamingSession()
    base_prompt: str = ""
    chunk_index = 0

    async def emit(event: dict) -> None:
        await websocket.send_text(json.dumps(event, ensure_ascii=False))

    await emit({"type": "ready"})

    try:
        while True:
            msg = await websocket.receive()
            kind = msg.get("type")
            if kind == "websocket.disconnect":
                break

            if "text" in msg and msg["text"] is not None:
                try:
                    ctrl = json.loads(msg["text"])
                except json.JSONDecodeError:
                    await emit({"type": "error", "message": "invalid JSON control message"})
                    continue
                ctype = ctrl.get("type")
                if ctype == "config":
                    base_prompt = (ctrl.get("initial_prompt") or "").strip()
                elif ctype == "close":
                    final_ev = session.force_finalize()
                    if final_ev:
                        await emit(final_ev)
                    break
                else:
                    await emit({"type": "error", "message": f"unknown control: {ctype}"})
                continue

            audio_bytes = msg.get("bytes")
            if not audio_bytes:
                continue

            chunk_index += 1
            prompt = session.get_initial_prompt(base_prompt)
            try:
                text, available = await _transcribe_chunk_bytes(
                    audio_bytes,
                    f"chunk_{chunk_index}.webm",
                    prompt,
                )
            except HTTPException as e:
                await emit({"type": "error", "message": str(e.detail)})
                continue
            except Exception as e:
                _log.exception("ws_transcribe chunk failed")
                await emit({"type": "error", "message": f"transcribe failed: {e}"})
                continue

            if not available:
                await emit({"type": "error", "message": "whisper-server unavailable"})
                continue

            event = session.add_chunk_text(text)
            await emit(event)

    except WebSocketDisconnect:
        pass
    except Exception:
        _log.exception("ws_transcribe loop failed")
    finally:
        # Best-effort flush of any pending partial on abrupt disconnect.
        # If the socket is already closed this raises; ignore.
        try:
            final_ev = session.force_finalize()
            if final_ev:
                await emit(final_ev)
        except Exception:
            pass
