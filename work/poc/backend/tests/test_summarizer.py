import pytest
from unittest.mock import patch, MagicMock
from services.summarizer import summarize_transcript, SummaryResult

SAMPLE_TRANSCRIPT = """
佐藤 淳（営業担当）: 他社から10%安い提案をいただいておりまして。
田中 一郎（営業担当）: ボリュームディスカウントで対応できます。全店展開で230店舗想定です。
佐藤 淳（営業担当）: 今週中に価格の再提案をまとめます。
"""


def _mock_ollama_response(content: str):
    """ollama.Client.chat() の戻り値を模倣する辞書を返す。"""
    return {"message": {"content": content}}


def test_summary_result_has_required_fields():
    mock_content = '{"topics":["競合から10%安い提案","全店展開230店舗の可能性"],"actions":[{"text":"価格再提案資料作成","assignee":"佐藤 淳","due":"今週中","urgent":true}],"risks":["競合が積極的アプローチ"]}'

    with patch("ollama.Client") as MockClient:
        MockClient.return_value.chat.return_value = _mock_ollama_response(mock_content)
        result = summarize_transcript(SAMPLE_TRANSCRIPT, meeting_type="opp")

    assert isinstance(result, SummaryResult)
    assert len(result.topics) > 0
    assert len(result.actions) > 0


def test_summary_returns_minutes_markdown():
    mock_content = '{"topics":["テスト議題"],"actions":[{"text":"テストアクション","assignee":"山田","due":"来週","urgent":false}],"risks":[]}'

    with patch("ollama.Client") as MockClient:
        MockClient.return_value.chat.return_value = _mock_ollama_response(mock_content)
        result = summarize_transcript(SAMPLE_TRANSCRIPT, meeting_type="opp")

    assert "## 議事録" in result.minutes_markdown
    assert "テスト議題" in result.minutes_markdown
