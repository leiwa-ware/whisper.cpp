"""Unit tests for services.text_dedup.strip_overlap_prefix.

P2-B の overlap dedup ロジック。sliding window で送られた重複範囲を
正しく除去できることと、誤除去（短すぎる偶然一致）を起こさないことを確認する。
"""
import pytest

from services.text_dedup import strip_overlap_prefix


# --- 基本動作 ----------------------------------------------------------


def test_strips_matching_overlap_prefix():
    """previous の末尾が current の先頭と一致したら strip する。"""
    assert strip_overlap_prefix("今日のテーマは", "テーマは売上の確認") == "売上の確認"


def test_no_match_returns_current_unchanged():
    """一致しなければ current をそのまま返す。"""
    assert strip_overlap_prefix("おはようございます", "こんにちは皆さん") == "こんにちは皆さん"


def test_empty_previous_returns_current():
    assert strip_overlap_prefix("", "新しいテキスト") == "新しいテキスト"


def test_empty_current_returns_empty():
    assert strip_overlap_prefix("先行テキスト", "") == ""


def test_full_duplicate_returns_empty():
    """完全に同じ内容なら空文字列を返す（重複行を出さない）。"""
    assert strip_overlap_prefix("こんにちは皆さん", "こんにちは皆さん") == ""


# --- 境界条件 ----------------------------------------------------------


def test_min_overlap_threshold_prevents_short_false_match():
    """min_overlap=4 未満の偶然一致は dedup しない（誤除去防止）。"""
    # "は" 1 文字が偶然一致してもストリップされない
    assert strip_overlap_prefix("会議です", "すぐに開始") == "すぐに開始"


def test_three_char_match_below_default_min_is_not_stripped():
    # tail "テーマ" (3 chars) で match するが min_overlap=4 のため除去されない
    assert strip_overlap_prefix("今日テーマ", "テーマ売上") == "テーマ売上"


def test_max_overlap_caps_search_length():
    """max_overlap を超える長さの一致は探さない（性能担保）。"""
    long_prev = "あ" * 100
    long_curr = "あ" * 100 + "新しい話"
    # max_overlap=10 で頭打ち → 10 文字までしか strip しない
    result = strip_overlap_prefix(long_prev, long_curr, max_overlap=10)
    assert result == "あ" * 90 + "新しい話"


def test_picks_longest_match():
    """複数の候補があれば最長一致を選ぶ。"""
    # tail-4 "ーマは" は match しないが tail-7 "今日のテーマは" は match
    # → 7 chars strip される
    assert strip_overlap_prefix("今日のテーマは", "今日のテーマは売上") == "売上"


# --- 実用シナリオ -------------------------------------------------------


def test_typical_sliding_window_scenario():
    """実際の sliding window 利用イメージ：4秒チャンク + 0.8秒overlap。"""
    chunk_n = "本日の議題は売上目標の確認と"
    chunk_n_plus_1 = "売上目標の確認と来期の見通しです。"
    deduped = strip_overlap_prefix(chunk_n, chunk_n_plus_1)
    assert deduped == "来期の見通しです。"


def test_partial_word_boundary_no_match():
    """単語の途中で切れている場合（whisper 出力ゆらぎ）はマッチしないので保守的に保持。"""
    # 同じ文意でも文字列が完全一致しなければ strip しない
    assert strip_overlap_prefix("田中さんに連絡", "田中さんへ連絡してください") == "田中さんへ連絡してください"
