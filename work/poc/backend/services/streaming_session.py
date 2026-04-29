"""Per-WebSocket streaming session: partial/final two-stage transcription state.

Holds rolling text across chunks and decides when to finalize based on:
- Sentence-end punctuation or polite Japanese verb endings
- Maximum partial duration (forced finalize after N seconds without sentence-end)

The session is stateful (one instance per WebSocket connection). Pure logic only —
no I/O, no whisper invocation. The WebSocket handler is responsible for calling
get_initial_prompt() before each chunk transcription and add_chunk_text() after.

See work/UIMock/2026-04-29-revised-plan.md §7 for the UI contract this implements.
"""
from __future__ import annotations

import time
from typing import Callable, Optional

# 句読点による文末（日本語＋英語混在を想定）
_SENTENCE_END_PUNCT = "。？！.?!"

# 文末敬語ヒューリスティクス。
# Whisper の出力は句読点を欠くことが多いため、語尾でも確定判定する。
# 検証: tests/test_streaming_session.py の polite_endings ケース
_POLITE_ENDINGS = (
    "ですね",
    "ですよ",
    "でしょう",
    "ました",
    "ません",
    "なります",
    "になります",
    "と思います",
    "ください",
    "お願いします",
    "申し上げます",
    "いたします",
)


def is_sentence_end(text: str) -> bool:
    """文末判定: 句読点 OR 敬語語尾で True を返す。"""
    stripped = text.rstrip()
    if not stripped:
        return False
    if stripped[-1] in _SENTENCE_END_PUNCT:
        return True
    return stripped.endswith(_POLITE_ENDINGS)


class StreamingSession:
    """Stateful partial/final accumulator for a single streaming connection.

    Args:
        now: Clock function (defaults to time.monotonic). Injectable for tests.
        max_partial_duration_s: Force finalize if a partial accumulates for
            this long without hitting a sentence-end (default 6s).
        context_chars: How many trailing chars of confirmed text to feed
            back as initial_prompt context (default 200, per
            work/UIMock/2026-04-27-improvement-plan.md P5).
    """

    def __init__(
        self,
        now: Callable[[], float] = time.monotonic,
        max_partial_duration_s: float = 6.0,
        context_chars: int = 200,
    ) -> None:
        self._now = now
        self.max_partial_duration_s = max_partial_duration_s
        self.context_chars = context_chars
        self.partial_text: str = ""
        self.confirmed_text: str = ""
        self._partial_started_at: Optional[float] = None

    def get_initial_prompt(self, base_prompt: str = "") -> str:
        """Build initial_prompt for the next chunk.

        Combines base_prompt (industry vocabulary) with the most recent
        context_chars of (confirmed + pending partial) text. Empty parts
        are dropped so we never emit leading/trailing whitespace.
        """
        recent = (self.confirmed_text + " " + self.partial_text).strip()
        if recent:
            recent = recent[-self.context_chars:]
        parts = [p for p in (base_prompt.strip(), recent) if p]
        return " ".join(parts)

    def add_chunk_text(self, text: str) -> dict:
        """Add a transcribed chunk and return either a partial or final event.

        Event shape:
            {"type": "partial"|"final", "text": <full>, "delta": <added by this chunk>}

        delta is the just-added portion (after stripping). For empty/whitespace
        chunks, delta is "" and text is unchanged. UI clients can append delta
        as a new line for chunk-level visual feedback.

        Empty / whitespace-only text is silently ignored (returns the
        current partial state without modification).
        """
        delta = text.strip()
        if delta:
            now = self._now()
            if self._partial_started_at is None:
                self._partial_started_at = now
            self.partial_text = (self.partial_text + " " + delta).strip() if self.partial_text else delta

            elapsed = now - self._partial_started_at
            if is_sentence_end(self.partial_text) or elapsed >= self.max_partial_duration_s:
                return self._do_finalize(delta)

        return {"type": "partial", "text": self.partial_text, "delta": delta}

    def force_finalize(self) -> Optional[dict]:
        """Finalize whatever is pending (called on session close).

        Returns the final event with delta="" (no new chunk was added),
        or None if there was nothing pending.
        """
        if not self.partial_text:
            return None
        return self._do_finalize(delta="")

    def _do_finalize(self, delta: str) -> dict:
        text = self.partial_text
        merged = (self.confirmed_text + " " + text).strip() if self.confirmed_text else text
        self.confirmed_text = merged[-self.context_chars:]
        self.partial_text = ""
        self._partial_started_at = None
        return {"type": "final", "text": text, "delta": delta}
