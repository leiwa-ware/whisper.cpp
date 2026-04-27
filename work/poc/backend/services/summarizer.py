import json
from dataclasses import dataclass, field
import ollama
from config import LOCAL_LLM_MODEL, OLLAMA_HOST


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


_PROMPT_TEMPLATE = """
以下の会議の文字起こしテキストから、次のJSONを出力してください。
マークダウンなしで純粋なJSONのみ出力してください。

{{
  "topics": ["主な議題を箇条書きで（3〜5件）"],
  "actions": [
    {{"text": "アクション内容", "assignee": "担当者名", "due": "期限", "urgent": true/false}}
  ],
  "risks": ["リスク・注意点（あれば）"]
}}

会議種別: {meeting_type}
文字起こし:
{transcript}
"""


_CORRECTION_PROMPT = """以下は日本語の業務会議を音声認識したテキストです。
誤認識と思われる箇所を、文脈から推測して自然なビジネス日本語に修正してください。

ルール：
- 修正は最小限にし、元の発言の意味・順序を保持する
- 明らかな音声認識ミス（「妖怪」→「了解」など）のみ修正する
- 修正後のテキストのみ出力し、説明・注釈は不要
{context_line}

音声認識テキスト:
{transcript}
"""


def correct_transcript(raw_text: str, context: str = "") -> str:
    """LLM で音声認識テキストの誤認識を文脈補正する。"""
    context_line = f"- 会議の文脈（固有名詞のヒント）: {context}" if context else ""
    prompt = _CORRECTION_PROMPT.format(
        context_line=context_line,
        transcript=raw_text,
    )
    client = ollama.Client(host=OLLAMA_HOST)
    response = client.chat(
        model=LOCAL_LLM_MODEL,
        messages=[{"role": "user", "content": prompt}],
        options={"temperature": 0.1},
    )
    return response["message"]["content"].strip()


def summarize_transcript(transcript: str, meeting_type: str = "opp") -> SummaryResult:
    client = ollama.Client(host=OLLAMA_HOST)
    response = client.chat(
        model=LOCAL_LLM_MODEL,
        messages=[{
            "role": "user",
            "content": _PROMPT_TEMPLATE.format(
                meeting_type="商談会議" if meeting_type == "opp" else "現場訪問",
                transcript=transcript,
            ),
        }],
        options={"temperature": 0.1},  # JSON 出力の安定性のため低温度
    )

    raw = response["message"]["content"].strip()
    start = raw.find("{")
    end = raw.rfind("}") + 1
    data = json.loads(raw[start:end])

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
    result.minutes_markdown = _to_markdown(transcript, result)
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
