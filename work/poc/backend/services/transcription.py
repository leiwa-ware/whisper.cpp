import subprocess
import json
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from config import WHISPER_CLI, WHISPER_MODEL


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
        raise RuntimeError(f"ffmpeg conversion failed: {proc.stderr.decode()[:300]}")
    return out_path


def transcribe_audio(audio_path: str, language: str = "ja") -> TranscriptionResult:
    """whisper-cli を subprocess で呼び出し転写結果を返す。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        wav_path = _to_16k_wav(audio_path, tmpdir)
        out_base = str(Path(tmpdir) / "result")

        cmd = [
            WHISPER_CLI,
            "-m", WHISPER_MODEL,
            "-f", wav_path,
            "-l", language,
            "--output-json",
            "-of", out_base,
            "--no-prints",
        ]

        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

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
