"""Guard against the kotoba-whisper + long prompt output collapse bug.

Empirical finding (work/UIMock/2026-04-29-bench-results.md §2):
    Kotoba-Whisper-v2.2 GGML models truncate output to a few characters when
    given a `--prompt` of >= 30 characters. With <= 27 characters they behave
    correctly. The bug is reproducible across q4_k / q5_k / q8_0 quantizations
    and is independent of prompt content. Other GGML models (small, medium,
    base) handle long prompts without issue.

    Until the underlying whisper.cpp issue is fixed, this module truncates
    prompts at sentence/comma boundaries below a conservative 24-char limit
    when the target model is identified as kotoba.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

# Conservative limit (3 chars below the empirical 27-char OK boundary).
KOTOBA_PROMPT_SAFE_CHARS = 24

# 句読点・空白を文末候補とする（日本語＋英語）
_BOUNDARY_CHARS = "。、！？.,! \n\t"
# 切断後に残るプロンプトが意味を持つ最小長。これより短くなるなら hard-cut のほうがマシ。
_MIN_USEFUL_LENGTH = 5

_log = logging.getLogger(__name__)


def is_kotoba_model(model_path: Optional[str]) -> bool:
    """Return True if the basename contains 'kotoba' (case-insensitive)."""
    if not model_path:
        return False
    return "kotoba" in os.path.basename(model_path).lower()


def safe_prompt_for_model(prompt: str, model_path: Optional[str]) -> str:
    """Return a prompt safe to send to the given model.

    For non-kotoba models this is a no-op. For kotoba models, prompts longer
    than KOTOBA_PROMPT_SAFE_CHARS are truncated. Truncation prefers the
    nearest sentence-end punctuation within the safe window; if none is
    available within the useful range, falls back to a hard cut at the limit.
    """
    if not prompt or not is_kotoba_model(model_path):
        return prompt
    if len(prompt) <= KOTOBA_PROMPT_SAFE_CHARS:
        return prompt

    window = prompt[:KOTOBA_PROMPT_SAFE_CHARS]
    truncated = _truncate_at_boundary(window)
    _log.warning(
        "kotoba model detected: prompt truncated %d→%d chars to avoid output collapse "
        "(see work/UIMock/2026-04-29-bench-results.md §2)",
        len(prompt), len(truncated),
    )
    return truncated


def _truncate_at_boundary(window: str) -> str:
    """Cut at the latest punctuation within `window` that yields >= _MIN_USEFUL_LENGTH.

    Falls back to the full window if no suitable boundary is found.
    """
    for stop in _BOUNDARY_CHARS:
        idx = window.rfind(stop)
        if idx >= _MIN_USEFUL_LENGTH:
            # include the punctuation itself
            return window[:idx + 1]
    return window
