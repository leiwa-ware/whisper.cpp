import pytest
from pathlib import Path
from services.transcription import transcribe_audio, TranscriptionResult

SAMPLE_WAV = Path(__file__).parent.parent.parent.parent.parent / "samples/jfk.wav"


def test_transcription_result_has_text():
    if not SAMPLE_WAV.exists():
        pytest.skip("samples/jfk.wav not found")
    result = transcribe_audio(str(SAMPLE_WAV), language="en")
    assert isinstance(result, TranscriptionResult)
    assert len(result.text) > 0
    assert "american" in result.text.lower()


def test_transcription_returns_segments():
    if not SAMPLE_WAV.exists():
        pytest.skip("samples/jfk.wav not found")
    result = transcribe_audio(str(SAMPLE_WAV), language="en")
    assert len(result.segments) > 0
    assert result.segments[0].get("text")


def test_invalid_audio_raises_error():
    with pytest.raises(FileNotFoundError):
        transcribe_audio("/nonexistent/file.wav", language="ja")
