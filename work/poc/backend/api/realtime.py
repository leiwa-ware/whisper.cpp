import asyncio
import tempfile
from pathlib import Path

import httpx
from fastapi import APIRouter, File, HTTPException, UploadFile

from config import WHISPER_SERVER_PORT
from services.transcription import _to_16k_wav

router = APIRouter()


@router.post("/transcribe-chunk")
async def transcribe_chunk(
    audio: UploadFile = File(...),
    initial_prompt: str = "",
):
    """
    録音中チャンク音声を whisper-server に転送してテキストを返す。
    initial_prompt: 得意先名・担当者名などを渡すと認識精度が向上する。
    レスポンス: {"text": "...", "available": true/false}
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        src = Path(tmpdir) / (audio.filename or "chunk.webm")
        src.write_bytes(await audio.read())

        try:
            wav_path = await asyncio.to_thread(_to_16k_wav, str(src), tmpdir)
        except Exception as e:
            raise HTTPException(status_code=422, detail=f"Audio conversion failed: {e}")

        url = f"http://127.0.0.1:{WHISPER_SERVER_PORT}/inference"
        form: dict = {"language": "ja", "response_format": "json"}
        if initial_prompt:
            form["initial_prompt"] = initial_prompt

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                with open(wav_path, "rb") as f:
                    r = await client.post(
                        url,
                        files={"file": ("audio.wav", f, "audio/wav")},
                        data=form,
                    )
        except httpx.ConnectError:
            return {"text": "", "available": False}

        if r.status_code != 200:
            raise HTTPException(status_code=502, detail=f"whisper-server: {r.text[:200]}")

        text = r.json().get("text", "").strip()
        return {"text": text, "available": True}
