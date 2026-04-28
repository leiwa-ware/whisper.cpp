import os
import subprocess
import json
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from config import WHISPER_CLI, WHISPER_FINAL_MODEL, WHISPER_VAD_MODEL
from services.noise_reduction import reduce_noise

# whisper の --prompt は「音声の直前に来る自然なテキスト」として設計されている。
# コンマ区切りの単語リストをそのまま渡すとデコーダーが混乱し精度が大幅に低下する。
# 固有名詞のみを自然文形式で渡す（呼び出し元から context として受け取る）。


@dataclass
class TranscriptionResult:
    text: str
    segments: list = field(default_factory=list)
    language: str = "ja"


def _to_16k_wav(audio_path: str, tmpdir: str) -> str:
    """WebM / MP4 / その他形式を 16kHz 16bit WAV に変換する。ffmpeg を使用。"""
    src = Path(audio_path)
    if not src.exists():
        raise FileNotFoundError(f"Audio file not found: {audio_path}")

    out_path = str(Path(tmpdir) / "audio.wav")
    cmd = [
        "ffmpeg", "-y", "-i", audio_path,
        "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le",
        out_path,
    ]
    proc = subprocess.run(cmd, capture_output=True, timeout=120)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg conversion failed: {proc.stderr.decode('utf-8', errors='replace')[:300]}")
    return out_path


def transcribe_audio(
    audio_path: str,
    language: str = "ja",
    initial_prompt: str = "",
) -> TranscriptionResult:
    """whisper-cli を subprocess で呼び出し転写結果を返す。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        wav_path = _to_16k_wav(audio_path, tmpdir)
        # ノイズ除去（NOISE_REDUCTION_LEVEL=none で無効化）
        clean_path = str(Path(tmpdir) / "audio_clean.wav")
        wav_path = reduce_noise(wav_path, clean_path)
        out_base = str(Path(tmpdir) / "result")

        cmd = [
            WHISPER_CLI,
            "-m", WHISPER_FINAL_MODEL,  # 最終文字起こしは精度優先モデル
            "-f", wav_path,
            "-l", language,
            "--output-json",
            "-of", out_base,
            "--no-prints",
            # 無音区間での幻覚（「ご視聴ありがとうございました」等）を抑制
            "--no-speech-thold", "0.6",
            "--entropy-thold", "2.4",
        ]
        # 固有名詞のみを自然文として渡す（コンマ区切りの単語リストは精度を低下させる）
        if initial_prompt:
            cmd += ["--prompt", initial_prompt]

        # VAD は環境変数 WHISPER_VAD_ENABLED=1 で明示有効化した場合のみ使用。
        # デフォルト無効: Silero-VAD のデフォルト閾値 (0.5) が日本語短発話を
        # 過剰にカットするため、--no-speech-thold による抑制を優先する。
        # 有効化する場合は保守的な閾値 (0.35) を使用して過剰カットを防ぐ。
        if WHISPER_VAD_MODEL and os.environ.get("WHISPER_VAD_ENABLED") == "1":
            cmd += [
                "--vad",
                "--vad-model", WHISPER_VAD_MODEL,
                "--vad-threshold", "0.35",        # default 0.5 は日本語短発話を過剰カット
                "--vad-speech-pad-ms", "400",      # 語頭子音の切り落とし防止
                "--vad-min-speech-duration-ms", "200",
            ]

        proc = subprocess.run(
            cmd, capture_output=True, text=True,
            encoding="utf-8", errors="replace",  # Windows CP932 デフォルトを上書き
            timeout=300,
        )

        if proc.returncode != 0:
            raise RuntimeError(
                f"whisper-cli failed (code {proc.returncode}): {proc.stderr[:500]}"
            )

        result_file = Path(out_base + ".json")
        if not result_file.exists():
            raise RuntimeError("whisper-cli produced no JSON output")

        data = json.loads(result_file.read_text(encoding="utf-8"))
        segments = data.get("transcription", [])
        full_text = " ".join(s.get("text", "").strip() for s in segments)

        return TranscriptionResult(
            text=full_text,
            segments=segments,
            language=language,
        )
