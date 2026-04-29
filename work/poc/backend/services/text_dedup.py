"""Text-level overlap dedup for sliding-window chunked transcription.

Used by the realtime POST path (api/realtime.py) and is intended to be
reusable by the WebSocket session path (services/streaming_session.py)
once P3-A is implemented.

The sliding window in meeting.html sends overlapping audio (e.g. 4s
chunks with 0.8s overlap) so whisper has enough context to transcribe
the chunk boundary without dropping word endings. The cost is that the
overlapping segment gets transcribed twice — once at the tail of chunk N
and once at the head of chunk N+1. This module strips the duplicate.
"""
from __future__ import annotations

# 一致を許容する最大文字数（あまり長いと別の偶然一致を拾うリスク）
DEFAULT_MAX_OVERLAP = 30
# 最低一致文字数（短すぎると「は」「が」など 1 文字一致で誤除去される）
DEFAULT_MIN_OVERLAP = 4


def strip_overlap_prefix(
    previous: str,
    current: str,
    max_overlap: int = DEFAULT_MAX_OVERLAP,
    min_overlap: int = DEFAULT_MIN_OVERLAP,
) -> str:
    """Strip the longest suffix of `previous` that matches a prefix of `current`.

    Returns the de-duplicated `current`. If no suffix/prefix match is found
    (or inputs are empty), returns `current` unchanged.

    Matching is exact-character. Whisper output for the same audio segment
    may differ slightly between calls due to context, so this is best-effort:
    when it matches we strip; when it doesn't we accept some duplicate text
    rather than risk losing genuinely new content.
    """
    if not previous or not current:
        return current

    upper = min(len(previous), len(current), max_overlap)
    for length in range(upper, min_overlap - 1, -1):
        if current.startswith(previous[-length:]):
            return current[length:]
    return current
