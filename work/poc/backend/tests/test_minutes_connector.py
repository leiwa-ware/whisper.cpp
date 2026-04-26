import pytest
from services.minutes_connector import (
    WhisperCppAdapter,
    M365CopilotAdapter,
    MinutesSource,
)


def test_whisper_adapter_implements_interface():
    adapter = WhisperCppAdapter(
        raw_transcript="田中: テストです。",
        opportunity_id="OPP-0001",
        participants=["田中"],
    )
    assert isinstance(adapter, MinutesSource)
    md = adapter.to_markdown()
    assert "## 議事録" in md
    assert "OPP-0001" in md


def test_m365_adapter_implements_interface():
    m365_raw = "# Meeting Notes\n\n## Key Points\n- Point 1\n\n## Action Items\n- Action 1 (Owner: 佐藤)"
    adapter = M365CopilotAdapter(
        raw_content=m365_raw,
        opportunity_id="OPP-0002",
        participants=["佐藤"],
    )
    assert isinstance(adapter, MinutesSource)
    md = adapter.to_markdown()
    assert "## 議事録" in md
    assert "OPP-0002" in md


def test_both_adapters_produce_same_markdown_structure():
    """問い⑩: アダプターが変わっても出力の構造が同一であることを確認"""
    whisper = WhisperCppAdapter(
        raw_transcript="佐藤: 商談が進んでいます。",
        opportunity_id="OPP-X",
        participants=["佐藤"],
    )
    m365 = M365CopilotAdapter(
        raw_content="# Meeting\n\n## Key Points\n- 商談が進んでいます",
        opportunity_id="OPP-X",
        participants=["佐藤"],
    )
    assert whisper.to_markdown().startswith("## 議事録")
    assert m365.to_markdown().startswith("## 議事録")
