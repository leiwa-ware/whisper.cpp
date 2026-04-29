"""Tests for services.prompt_safety.

Background:
    Empirically (work/UIMock/2026-04-29-bench-results.md §2), kotoba-whisper-v2.2
    GGML models collapse output when prompts are >= 30 characters. With prompts
    <= 27 chars they transcribe correctly. We pick a conservative 24-char limit.
"""
import pytest

from services.prompt_safety import is_kotoba_model, safe_prompt_for_model, KOTOBA_PROMPT_SAFE_CHARS


# --- is_kotoba_model -----------------------------------------------------


@pytest.mark.parametrize("path", [
    "C:/work/.../models/ggml-kotoba-v2.2-q5_k.bin",
    r"C:\models\ggml-kotoba-v2.2-q8_0.bin",
    "/usr/local/share/kotoba-v2.bin",
    "ggml-Kotoba-v1.0.bin",                 # case-insensitive
    "models/ggml-KOTOBA-q4_k.bin",
])
def test_is_kotoba_model_detects_kotoba_filenames(path):
    assert is_kotoba_model(path) is True


@pytest.mark.parametrize("path", [
    "models/ggml-small.bin",
    "models/ggml-medium.bin",
    "models/ggml-base.bin",
    "models/ggml-large-v3.bin",
    "models/ggml-distil-whisper.bin",
    "",
    None,
])
def test_is_kotoba_model_rejects_non_kotoba(path):
    assert is_kotoba_model(path) is False


# --- safe_prompt_for_model: non-kotoba should pass through ----------------


def test_non_kotoba_model_passes_long_prompt_unchanged():
    long = "A" * 500
    assert safe_prompt_for_model(long, "models/ggml-small.bin") == long


def test_non_kotoba_model_passes_empty_prompt_unchanged():
    assert safe_prompt_for_model("", "models/ggml-small.bin") == ""


# --- safe_prompt_for_model: kotoba with short prompt ----------------------


def test_kotoba_short_prompt_unchanged():
    p = "商談会議。"  # 5 chars - well under limit
    assert safe_prompt_for_model(p, "models/ggml-kotoba-v2.2-q5_k.bin") == p


def test_kotoba_prompt_at_exact_limit_unchanged():
    p = "あ" * KOTOBA_PROMPT_SAFE_CHARS  # exactly limit
    out = safe_prompt_for_model(p, "models/ggml-kotoba.bin")
    assert len(out) == KOTOBA_PROMPT_SAFE_CHARS
    assert out == p


def test_kotoba_empty_prompt_unchanged():
    assert safe_prompt_for_model("", "models/ggml-kotoba.bin") == ""


# --- safe_prompt_for_model: kotoba with long prompt -----------------------


def test_kotoba_long_prompt_truncated_below_limit():
    p = "あ" * 100
    out = safe_prompt_for_model(p, "models/ggml-kotoba.bin")
    assert len(out) <= KOTOBA_PROMPT_SAFE_CHARS


def test_kotoba_truncation_prefers_japanese_period_boundary():
    """When a 。 sits before the hard limit, truncate at it for natural phrasing."""
    # 「商談会議です。」(8 chars) + filler that would push past limit
    p = "商談会議です。今日のテーマは売上の確認と来週のフォローアップです。"
    out = safe_prompt_for_model(p, "models/ggml-kotoba.bin")
    assert len(out) <= KOTOBA_PROMPT_SAFE_CHARS
    # Result should END with 。 (kept the natural sentence break)
    assert out.endswith("。")


def test_kotoba_truncation_prefers_japanese_comma_when_no_period():
    """If only 、 is available within window, use it as the boundary."""
    p = "営業報告、目標達成、来週のフォローについて話します"
    out = safe_prompt_for_model(p, "models/ggml-kotoba.bin")
    assert len(out) <= KOTOBA_PROMPT_SAFE_CHARS
    assert out.endswith("、")


def test_kotoba_truncation_falls_back_to_hard_cut_when_no_punctuation():
    """No punctuation in window → just truncate at the limit (no orphaned half-token)."""
    p = "あいうえおかきくけこさしすせそたちつてとなにぬねのはひふへほまみむめも"
    out = safe_prompt_for_model(p, "models/ggml-kotoba.bin")
    assert len(out) == KOTOBA_PROMPT_SAFE_CHARS


def test_kotoba_truncation_does_not_produce_empty_when_punct_too_early():
    """If the only punctuation is way before the limit (e.g., at char 2),
    don't truncate to 2 chars - prefer the hard limit instead."""
    p = "あ。" + "い" * 100
    out = safe_prompt_for_model(p, "models/ggml-kotoba.bin")
    assert len(out) > 2  # not a meaningless 2-char truncation
    assert len(out) <= KOTOBA_PROMPT_SAFE_CHARS


def test_kotoba_truncation_logs_warning(caplog):
    import logging
    p = "あ" * 100
    with caplog.at_level(logging.WARNING):
        safe_prompt_for_model(p, "models/ggml-kotoba.bin")
    assert any("kotoba" in rec.message.lower() and "trunc" in rec.message.lower()
               for rec in caplog.records)


def test_kotoba_short_prompt_does_not_log_warning(caplog):
    import logging
    p = "短いプロンプト"  # within limit
    with caplog.at_level(logging.WARNING):
        safe_prompt_for_model(p, "models/ggml-kotoba.bin")
    assert not any("trunc" in rec.message.lower() for rec in caplog.records)
