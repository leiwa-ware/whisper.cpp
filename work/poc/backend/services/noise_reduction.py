import logging
import os
import subprocess

_log = logging.getLogger(__name__)

NOISE_REDUCTION_LEVEL = os.environ.get("NOISE_REDUCTION_LEVEL", "moderate")

# レベル別フィルター候補（先頭から順に試す。失敗したら次へ）
# arnndn が利用できない ffmpeg ビルドのためにバンドパスフィルターをフォールバックとして用意。
_FILTER_CANDIDATES: dict[str, list[str]] = {
    "mild": [
        "highpass=f=80,lowpass=f=8000",
    ],
    "moderate": [
        "arnndn",
        "highpass=f=80,lowpass=f=7500",
    ],
    "aggressive": [
        "arnndn,highpass=f=100,lowpass=f=7000",
        "arnndn",
        "highpass=f=100,lowpass=f=7000",
    ],
}


def reduce_noise(wav_path: str, output_path: str) -> str:
    """RNNoise (ffmpeg arnndn) でノイズ除去した WAV を output_path に書き出して返す。

    フィルターが利用できない場合は次の候補へフォールバックする。
    すべて失敗した場合は元の wav_path をそのまま返す（転写処理は継続する）。
    """
    if NOISE_REDUCTION_LEVEL == "none":
        return wav_path

    candidates = _FILTER_CANDIDATES.get(NOISE_REDUCTION_LEVEL, _FILTER_CANDIDATES["moderate"])

    for af_filter in candidates:
        cmd = [
            "ffmpeg", "-y", "-i", wav_path,
            "-af", af_filter,
            "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le",
            output_path,
        ]
        proc = subprocess.run(cmd, capture_output=True, timeout=120)
        if proc.returncode == 0:
            _log.debug("Noise reduction (%s) applied: %s → %s", af_filter, wav_path, output_path)
            return output_path
        _log.debug(
            "Filter '%s' failed (code %s), trying next fallback",
            af_filter, proc.returncode,
        )

    _log.warning(
        "All noise reduction filters failed for level='%s', using original audio",
        NOISE_REDUCTION_LEVEL,
    )
    return wav_path
