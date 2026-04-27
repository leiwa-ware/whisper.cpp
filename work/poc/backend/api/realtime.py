import asyncio
import tempfile
from pathlib import Path

import httpx
from fastapi import APIRouter, File, HTTPException, UploadFile

from config import WHISPER_SERVER_PORT
from services.transcription import _to_16k_wav

router = APIRouter()


@router.post("/transcribe-chunk")
async def transcribe_chunk(audio: UploadFile = File(...)):
    """
    録音中チャンク音声を whisper-server に転送してテキストを返す。
    レスポンス: {"text": "...", "available": true/false}
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        # アップロードされた音声をファイルに保存
        src = Path(tmpdir) / (audio.filename or "chunk.webm")
        src.write_bytes(await audio.read())

        # 16kHz WAV に変換（blocking → スレッドで実行）
        try:
            wav_path = await asyncio.to_thread(_to_16k_wav, str(src), tmpdir)
        except Exception as e:
            raise HTTPException(status_code=422, detail=f"Audio conversion failed: {e}")

        # whisper-server に推論リクエスト
        url = f"http://127.0.0.1:{WHISPER_SERVER_PORT}/inference"
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                with open(wav_path, "rb") as f:
                    r = await client.post(
                        url,
                        files={"file": ("audio.wav", f, "audio/wav")},
                        data={"language": "ja", "response_format": "json"},
                    )
        except httpx.ConnectError:
            # whisper-server が未起動の場合は graceful degradation
            return {"text": "", "available": False}

        if r.status_code != 200:
            raise HTTPException(status_code=502, detail=f"whisper-server: {r.text[:200]}")

        data = r.json()
        # whisper-server は {"text": "..."} を返す
        text = data.get("text", "").strip()
        return {"text": text, "available": True}
