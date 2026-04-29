"""Unit tests for services.streaming_session.StreamingSession.

Tests cover:
- Sentence-end detection (Japanese punctuation + polite endings).
- 6-second forced finalization when no sentence-end appears.
- Context inheritance across chunks via initial_prompt.
- Buffer truncation to context_chars.
- Force-finalize on session close.
"""
import pytest

from services.streaming_session import StreamingSession, is_sentence_end


# --- is_sentence_end -------------------------------------------------------


@pytest.mark.parametrize("text", [
    "今日は会議です。",
    "そうですね。",
    "本当ですか？",
    "ありがとう！",
    "I think so.",
    "Hello?",
    "Wow!",
])
def test_sentence_end_punctuation_returns_true(text):
    assert is_sentence_end(text) is True


@pytest.mark.parametrize("text", [
    "次の議題に移ります",            # bare verb stem - not finalized
    "今日のテーマは",                  # incomplete clause
    "  ",                              # whitespace only
    "",                                 # empty
])
def test_sentence_end_incomplete_returns_false(text):
    assert is_sentence_end(text) is False


@pytest.mark.parametrize("text", [
    "そうですね",
    "確認しました",
    "対応すると思います",
    "次回までにお願いします",
    "問題ないでしょう",
    "ご確認ください",
    "来週になります",
])
def test_sentence_end_polite_endings_returns_true(text):
    assert is_sentence_end(text) is True


def test_sentence_end_strips_trailing_whitespace():
    assert is_sentence_end("そうですね  \n") is True


# --- StreamingSession.add_chunk_text -------------------------------------


def test_partial_emitted_when_no_sentence_end():
    s = StreamingSession(now=lambda: 0.0)
    ev = s.add_chunk_text("次の議題に移ります")
    assert ev["type"] == "partial"
    assert ev["text"] == "次の議題に移ります"


def test_partial_event_includes_delta():
    """delta は「このチャンクで新たに追加された分」を表す。
    UI 側がチャンク単位の追記アニメーションをするのに使う。
    """
    s = StreamingSession(now=lambda: 0.0)
    ev1 = s.add_chunk_text("今日のテーマは")
    assert ev1["delta"] == "今日のテーマは"

    ev2 = s.add_chunk_text("売上の確認で")
    assert ev2["type"] == "partial"
    assert ev2["delta"] == "売上の確認で"
    # full text は累積値
    assert ev2["text"] == "今日のテーマは 売上の確認で"


def test_final_event_includes_delta_for_consistency():
    """final 時も delta フィールドを持つ（UI 側の処理を統一するため）。"""
    s = StreamingSession(now=lambda: 0.0)
    s.add_chunk_text("途中まで")
    ev = s.add_chunk_text("これで完結します。")
    assert ev["type"] == "final"
    assert ev["delta"] == "これで完結します。"


def test_force_finalize_includes_delta_as_empty_when_no_new_chunk():
    """force_finalize は新規チャンクなしで呼ばれるので delta は空文字列。"""
    s = StreamingSession(now=lambda: 0.0)
    s.add_chunk_text("途中で切れた")
    ev = s.force_finalize()
    assert ev["type"] == "final"
    assert ev["delta"] == ""


def test_empty_chunk_partial_event_has_empty_delta():
    s = StreamingSession(now=lambda: 0.0)
    s.add_chunk_text("既存のpartial")
    ev = s.add_chunk_text("")
    assert ev["type"] == "partial"
    assert ev["delta"] == ""


def test_final_emitted_on_japanese_period():
    s = StreamingSession(now=lambda: 0.0)
    ev = s.add_chunk_text("会議を始めます。")
    assert ev["type"] == "final"
    assert ev["text"] == "会議を始めます。"


def test_final_emitted_on_polite_ending():
    s = StreamingSession(now=lambda: 0.0)
    ev = s.add_chunk_text("確認しました")
    assert ev["type"] == "final"


def test_partial_accumulates_until_sentence_end():
    s = StreamingSession(now=lambda: 0.0)
    e1 = s.add_chunk_text("今日のテーマは")
    e2 = s.add_chunk_text("売上の確認です。")
    assert e1["type"] == "partial"
    assert e1["text"] == "今日のテーマは"
    assert e2["type"] == "final"
    assert "今日のテーマは" in e2["text"]
    assert "売上の確認です。" in e2["text"]


def test_empty_chunk_text_returns_partial_with_no_change():
    s = StreamingSession(now=lambda: 0.0)
    s.add_chunk_text("途中まで")
    ev = s.add_chunk_text("")
    assert ev["type"] == "partial"
    assert ev["text"] == "途中まで"


# --- 6-second forced finalize --------------------------------------------


def test_forced_final_after_max_partial_duration():
    clock = [0.0]
    s = StreamingSession(now=lambda: clock[0], max_partial_duration_s=6.0)

    # First chunk at t=0
    e1 = s.add_chunk_text("途中の発話")
    assert e1["type"] == "partial"

    # Second chunk at t=5.5 - still partial
    clock[0] = 5.5
    e2 = s.add_chunk_text("が続いている")
    assert e2["type"] == "partial"

    # Third chunk at t=6.5 - exceeds 6s, force finalize
    clock[0] = 6.5
    e3 = s.add_chunk_text("まだ続く")
    assert e3["type"] == "final"
    assert "途中の発話" in e3["text"]
    assert "まだ続く" in e3["text"]


def test_partial_clock_resets_after_finalize():
    clock = [0.0]
    s = StreamingSession(now=lambda: clock[0], max_partial_duration_s=6.0)

    s.add_chunk_text("最初の文。")     # finalized at t=0
    clock[0] = 5.0
    e = s.add_chunk_text("二番目の発話")
    # Should still be partial - 5s since the *new* partial began (which is 0s ago)
    assert e["type"] == "partial"


# --- Context inheritance --------------------------------------------------


def test_initial_prompt_is_empty_when_session_is_fresh():
    s = StreamingSession(now=lambda: 0.0)
    assert s.get_initial_prompt() == ""


def test_initial_prompt_combines_base_and_confirmed_text():
    s = StreamingSession(now=lambda: 0.0)
    s.add_chunk_text("田中さんと打ち合わせしました。")  # → final → goes to confirmed
    prompt = s.get_initial_prompt(base_prompt="商談会議。成約率について。")
    assert "商談会議" in prompt
    assert "田中さん" in prompt


def test_initial_prompt_includes_partial_text_for_continuity():
    s = StreamingSession(now=lambda: 0.0)
    s.add_chunk_text("先週の在庫について")  # partial (no sentence end)
    prompt = s.get_initial_prompt(base_prompt="物流会議")
    assert "在庫" in prompt
    assert "物流会議" in prompt


def test_initial_prompt_truncated_to_context_chars():
    s = StreamingSession(now=lambda: 0.0, context_chars=20)
    long = "一" * 100 + "。"
    s.add_chunk_text(long)
    prompt = s.get_initial_prompt()
    # Only the most recent N chars of confirmed text are preserved
    assert len(prompt) <= 20


# --- force_finalize on close ---------------------------------------------


def test_force_finalize_emits_final_with_pending_partial():
    s = StreamingSession(now=lambda: 0.0)
    s.add_chunk_text("途中で切れた発話")
    ev = s.force_finalize()
    assert ev is not None
    assert ev["type"] == "final"
    assert ev["text"] == "途中で切れた発話"


def test_force_finalize_returns_none_when_nothing_pending():
    s = StreamingSession(now=lambda: 0.0)
    s.add_chunk_text("既に確定。")
    ev = s.force_finalize()
    assert ev is None


# --- whitespace and joining behavior -------------------------------------


def test_chunk_texts_joined_with_single_space():
    s = StreamingSession(now=lambda: 0.0)
    s.add_chunk_text("こんにちは")
    ev = s.add_chunk_text("元気ですか？")
    assert ev["type"] == "final"
    # Single space joiner; no double-space artifacts
    assert "  " not in ev["text"]
