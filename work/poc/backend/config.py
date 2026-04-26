import os
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent.parent  # whisper.cpp root

WHISPER_CLI = os.environ.get(
    "WHISPER_CLI",
    str(REPO_ROOT / "build/bin/Release/whisper-cli.exe")
    if os.name == "nt"
    else str(REPO_ROOT / "build/bin/whisper-cli"),
)

WHISPER_MODEL = os.environ.get(
    "WHISPER_MODEL",
    str(REPO_ROOT / "models/ggml-base.bin"),
)

DB_PATH = os.environ.get("DB_PATH", "poc_meeting.db")

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

AUDIO_UPLOAD_DIR = Path(os.environ.get("AUDIO_UPLOAD_DIR", "/tmp/poc_audio"))
AUDIO_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
