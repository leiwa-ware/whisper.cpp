import os
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent.parent  # whisper.cpp root

WHISPER_CLI = os.environ.get(
    "WHISPER_CLI",
    str(REPO_ROOT / "build/bin/Release/whisper-cli.exe")
    if os.name == "nt"
    else str(REPO_ROOT / "build/bin/whisper-cli"),
)

WHISPER_SERVER_BIN = os.environ.get(
    "WHISPER_SERVER_BIN",
    str(REPO_ROOT / "build/bin/Release/whisper-server.exe")
    if os.name == "nt"
    else str(REPO_ROOT / "build/bin/whisper-server"),
)
WHISPER_SERVER_PORT = int(os.environ.get("WHISPER_SERVER_PORT", "8178"))

WHISPER_MODEL = os.environ.get(
    "WHISPER_MODEL",
    str(REPO_ROOT / "models/ggml-base.bin"),
)

# 録音停止後の最終文字起こし用モデル（精度優先・速度不問）
# medium が未ダウンロードの場合は WHISPER_MODEL にフォールバック
_medium = REPO_ROOT / "models/ggml-medium.bin"
WHISPER_FINAL_MODEL = os.environ.get(
    "WHISPER_FINAL_MODEL",
    str(_medium) if _medium.exists() else WHISPER_MODEL,
)

DB_PATH = os.environ.get("DB_PATH", "poc_meeting.db")

# ローカル LLM 設定（Ollama）。外部 API 不要・オフライン動作。
LOCAL_LLM_MODEL = os.environ.get("LOCAL_LLM_MODEL", "qwen2.5-coder:7b")
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")

AUDIO_UPLOAD_DIR = Path(os.environ.get("AUDIO_UPLOAD_DIR", "/tmp/poc_audio"))
AUDIO_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
