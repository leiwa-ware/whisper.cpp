import json
import logging
import re
from dataclasses import dataclass, field
import ollama
from config import LOCAL_LLM_MODEL, OLLAMA_HOST

_log = logging.getLogger(__name__)


@dataclass
class ActionItem:
    text: str
    assignee: str
    due: str
    urgent: bool = False


@dataclass
class SummaryResult:
    topics: list[str] = field(default_factory=list)
    actions: list[ActionItem] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    minutes_markdown: str = ""


# 誤認識補正 + 構造化抽出を 1 回の LLM 呼び出しで実行するプロンプト
_COMBINED_PROMPT = """以下は日本語の業務会議の音声認識テキストです。

【音声認識の典型的な誤りパターン】
1. カタカナ語を漢字に誤変換: フォロー→鼓動、アポ→アハ、フィード→不意打ち 等
2. 同音異字: 成約→奠約・専約、先週→前週、母数→ハハ数 等
3. 語尾・助詞の崩れ: とどまったね→留まったり 等
4. 幻覚フレーズ（実際には発話されていない）:
   「ご視聴ありがとうございました」「チャンネル登録をお願いします」
   「以上で終わります」等のYouTube/動画的な締め言葉 → 必ず削除する

【修正方針】
- 文脈上ありえない単語（「鼓動不足」「ハハ数」等）は積極的に正しい語に直す
- 幻覚フレーズは削除する（会議の発言ではないため）
- ビジネス用語（成約率・フォロー・母数・アポイント・進捗管理等）の誤認識を優先修正

マークダウンなしで純粋なJSONのみ出力してください：

{{
  "corrected_transcript": "修正後の文字起こし全文",
  "topics": ["主な議題（3〜5件）"],
  "actions": [
    {{"text": "アクション内容", "assignee": "担当者名", "due": "期限", "urgent": true/false}}
  ],
  "risks": ["リスク・注意点（あれば）"]
}}

会議種別: {meeting_type}
{context_line}
音声認識テキスト:
{transcript}
"""


def _parse_llm_json(raw: str, fallback_transcript: str) -> dict:
    """LLM 出力から JSON を抽出。失敗時は文字起こしを保持した最小辞書を返す。"""
    # qwen3 / deepseek-r1 等の thinking モデルは <think>...</think> を出力する。
    # ブロック内に { } が含まれると後続の JSON 検索が誤動作するため先に除去する。
    raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()

    # 試行 1: 最初の { から最後の } を取る
    start = raw.find("{")
    end = raw.rfind("}") + 1
    if start >= 0 and end > start:
        try:
            return json.loads(raw[start:end])
        except json.JSONDecodeError as e:
            _log.warning("JSON parse failed (attempt 1): %s", e)

    # 試行 2: ```json ... ``` コードブロック内を探す
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError as e:
            _log.warning("JSON parse failed (attempt 2): %s", e)

    # 試行 3: 全体を JSON としてパース
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # 全失敗: 文字起こし本文は保持、構造化は空で返す
    _log.error("All JSON parse attempts failed. Returning raw transcript as corrected.")
    return {
        "corrected_transcript": fallback_transcript,
        "topics": [],
        "actions": [],
        "risks": [],
    }


def correct_and_summarize(
    raw_transcript: str,
    meeting_type: str = "opp",
    context: str = "",
) -> tuple[str, SummaryResult]:
    """
    音声認識テキストの誤認識補正と議事録構造化を 1 回の LLM 呼び出しで実行。
    戻り値: (補正済みテキスト, SummaryResult)
    """
    context_line = f"文脈ヒント（固有名詞）: {context}\n" if context else ""
    prompt = _COMBINED_PROMPT.format(
        meeting_type="商談会議" if meeting_type == "opp" else "現場訪問",
        context_line=context_line,
        transcript=raw_transcript,
    )

    client = ollama.Client(host=OLLAMA_HOST)
    try:
        response = client.chat(
            model=LOCAL_LLM_MODEL,
            messages=[{"role": "user", "content": prompt}],
            options={"temperature": 0.1},
        )
        raw = response["message"]["content"].strip()
    except Exception as e:
        # Ollama 未起動・接続失敗時は補正なし・空の要約で継続（データ喪失防止）
        _log.warning("Ollama unavailable: %s", e)
        result = SummaryResult()
        result.minutes_markdown = _to_markdown(raw_transcript, result)
        return raw_transcript, result

    data = _parse_llm_json(raw, raw_transcript)

    corrected = data.get("corrected_transcript", raw_transcript)

    actions = [
        ActionItem(
            text=a.get("text", ""),
            assignee=a.get("assignee", ""),
            due=a.get("due", ""),
            urgent=a.get("urgent", False),
        )
        for a in data.get("actions", [])
    ]

    result = SummaryResult(
        topics=data.get("topics", []),
        actions=actions,
        risks=data.get("risks", []),
    )
    result.minutes_markdown = _to_markdown(corrected, result)
    return corrected, result


# 後方互換: テスト・既存呼び出し元のために残す
def summarize_transcript(transcript: str, meeting_type: str = "opp") -> SummaryResult:
    _, result = correct_and_summarize(transcript, meeting_type=meeting_type)
    return result


def _to_markdown(transcript: str, summary: SummaryResult) -> str:
    lines = ["## 議事録\n"]

    lines.append("### 主な議題")
    for t in summary.topics:
        lines.append(f"- {t}")

    lines.append("\n### アクションアイテム")
    for a in summary.actions:
        urgent_tag = " **[緊急]**" if a.urgent else ""
        lines.append(f"- {a.text}{urgent_tag} → {a.assignee} / {a.due}")

    if summary.risks:
        lines.append("\n### リスク・注意点")
        for r in summary.risks:
            lines.append(f"- {r}")

    lines.append("\n---\n\n### 文字起こし全文\n")
    lines.append(transcript)

    return "\n".join(lines)
