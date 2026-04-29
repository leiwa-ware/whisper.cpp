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
WHISPER_SERVER_PORT = int(os.environ.get("WHISPER_SERVER_PORT", "8300"))

# Kotoba-Whisper v2.2: 日本語特化蒸留モデル (GGML 形式)
# ダウンロード元: Pomni/kotoba-whisper-v2.2-ggml-allquants (公開・認証不要)
#   curl -L -o models/ggml-kotoba-v2.2-q5_k.bin \
#     https://huggingface.co/Pomni/kotoba-whisper-v2.2-ggml-allquants/resolve/main/ggml-kotoba-v2.2-q5_k.bin
_kotoba_candidates = sorted(_glob.glob(str(REPO_ROOT / "models/ggml-kotoba*.bin")))
# 最終転写用（精度優先）: q5_k → q8_0 の順
_kotoba_q8 = [p for p in _kotoba_candidates if "q8" in p]
_kotoba_q5 = [p for p in _kotoba_candidates if "q5_k" in p or "q5k" in p]
_kotoba_accurate = _kotoba_q5[-1] if _kotoba_q5 else (_kotoba_q8[-1] if _kotoba_q8 else (_kotoba_candidates[-1] if _kotoba_candidates else ""))

_medium = REPO_ROOT / "models/ggml-medium.bin"

# リアルタイム転写用（速度優先）: whisper-server に渡すモデル。
# CPU 環境では kotoba q8_0/q5_k は ~6x RTF（5秒音声に25秒）のためリアルタイム不可。
# base (148MB) は CPU でも ~0.3x RTF（5秒音声に約1.5秒）で実用的なプレビューが可能。
# GPU (CUDA/Metal) 環境なら: WHISPER_MODEL=.../ggml-kotoba-v2.2-q8_0.bin を明示指定
WHISPER_MODEL = os.environ.get(
    "WHISPER_MODEL",
    str(REPO_ROOT / "models/ggml-small.bin"),
)

# 最終転写用（精度優先）: Kotoba q5_k → q8_0 → medium → base の順でフォールバック
WHISPER_FINAL_MODEL = os.environ.get(
    "WHISPER_FINAL_MODEL",
    _kotoba_accurate if _kotoba_accurate
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
