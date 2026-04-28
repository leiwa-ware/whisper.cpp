import glob as _glob
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

# Kotoba-Whisper: 日本語特化蒸留モデル (GGML 形式)
# ダウンロード: huggingface_hub で kotoba-tech/kotoba-whisper-v2.2-ggml を取得
#   python -c "from huggingface_hub import hf_hub_download; \
#     hf_hub_download('kotoba-tech/kotoba-whisper-v2.2-ggml', \
#     'ggml-model-q5_k_m.bin', local_dir='models/')"
_kotoba_candidates = sorted(_glob.glob(str(REPO_ROOT / "models/ggml-kotoba*.bin")))
_kotoba_model = _kotoba_candidates[-1] if _kotoba_candidates else ""

_medium = REPO_ROOT / "models/ggml-medium.bin"

# リアルタイム転写用（速度優先）: Kotoba → base の順でフォールバック
WHISPER_MODEL = os.environ.get(
    "WHISPER_MODEL",
    _kotoba_model if _kotoba_model else str(REPO_ROOT / "models/ggml-base.bin"),
)

# 最終転写用（精度優先）: Kotoba → medium → base の順でフォールバック
WHISPER_FINAL_MODEL = os.environ.get(
    "WHISPER_FINAL_MODEL",
    _kotoba_model if _kotoba_model
    else (str(_medium) if _medium.exists() else WHISPER_MODEL),
)

DB_PATH = os.environ.get("DB_PATH", "poc_meeting.db")

# ローカル LLM 設定（Ollama）。外部 API 不要・オフライン動作。
# qwen3:1.7b (Q4_K_M, ~1.0GB RAM) を使用。<think> タグ自動除去済み。
# whisper と直列実行のため RAM ピーク: whisper(~1.2GB) + qwen3(~1.0GB) ≈ 2.2GB。
# 8.7GB RAM で 3GB 以上の余裕あり。環境変数 LOCAL_LLM_MODEL で上書き可能。
LOCAL_LLM_MODEL = os.environ.get("LOCAL_LLM_MODEL", "qwen3:1.7b")

# ノイズ除去レベル: none / mild / moderate / aggressive
# moderate がデフォルト。静音オフィスでは mild、倉庫・工場では aggressive を推奨。
NOISE_REDUCTION_LEVEL = os.environ.get("NOISE_REDUCTION_LEVEL", "moderate")
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")

# VAD モデルパス。models/ggml-silero-vad*.bin が存在する場合のみ有効化。
# ダウンロード: bash models/download-vad-model.sh silero-v6.2.0
_vad_candidates = sorted(_glob.glob(str(REPO_ROOT / "models/ggml-silero-v*.bin")))
WHISPER_VAD_MODEL = os.environ.get(
    "WHISPER_VAD_MODEL",
    _vad_candidates[-1] if _vad_candidates else "",
)

AUDIO_UPLOAD_DIR = Path(os.environ.get("AUDIO_UPLOAD_DIR", "/tmp/poc_audio"))
AUDIO_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
