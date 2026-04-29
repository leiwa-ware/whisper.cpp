import os
import subprocess
import json
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from config import (
    WHISPER_CLI,
    WHISPER_FINAL_BEAM_SIZE,
    WHISPER_FINAL_MODEL,
    WHISPER_THREADS,
    WHISPER_VAD_MODEL,
)
from services.noise_reduction import reduce_noise
from services.prompt_safety import safe_prompt_for_model

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
            # whisper-cli の既定は min(4, hardware_concurrency) で頭打ち。物理コア数で明示。
            "--threads", str(WHISPER_THREADS),
            # 最終転写は精度優先で beam search を有効化（whisper 既定の 5）。
            "--beam-size", str(WHISPER_FINAL_BEAM_SIZE),
            # 無音区間での幻覚（「ご視聴ありがとうございました」等）を抑制
            "--no-speech-thold", "0.6",
            "--entropy-thold", "2.4",
        ]
        # kotoba モデルは 30文字以上のプロンプトで出力崩壊するため、必要に応じて自動で短縮。
        # 詳細は work/UIMock/2026-04-29-bench-results.md §2 / services/prompt_safety.py
        safe_prompt = safe_prompt_for_model(initial_prompt, WHISPER_FINAL_MODEL)
        if safe_prompt:
            cmd += ["--prompt", safe_prompt]

        # VAD はモデルが存在すればデフォルト ON。
        # WHISPER_VAD_ENABLED=0 で明示的に無効化できる。
        # 保守的な閾値 (0.35) + speech-pad 400ms により、日本語の短発話
        # （「はい」「いえ」「そう」）を過剰カットしない設定にしている。
        # 詳細は work/UIMock/2026-04-29-voice-recognition-improvements.md §3 P1-C
        if WHISPER_VAD_MODEL and os.environ.get("WHISPER_VAD_ENABLED", "1") != "0":
            cmd += [
                "--vad",
                "--vad-model", WHISPER_VAD_MODEL,
                "--vad-threshold", "0.35",        # default 0.5 は日本語短発話を過剰カット
                "--vad-speech-pad-ms", "400",      # 語頭子音の切り落とし防止
                "--vad-min-speech-duration-ms", "200",
            ]

        import logging as _logging
        _logging.getLogger(__name__).warning("whisper cmd: %s", " ".join(cmd))
        proc = subprocess.run(
            cmd, capture_output=True, text=True,
            encoding="utf-8", errors="replace",  # Windows CP932 デフォルトを上書き
            timeout=300,
        )

        if proc.returncode != 0:
            raise RuntimeError(
                f"whisper-cli failed (code {proc.returncode})\n"
                f"CMD: {' '.join(cmd)}\n"
                f"STDERR: {proc.stderr[:800]}\n"
                f"STDOUT: {proc.stdout[:400]}"
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
