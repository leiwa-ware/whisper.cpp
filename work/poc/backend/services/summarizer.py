import json
from dataclasses import dataclass, field
import anthropic
from config import ANTHROPIC_API_KEY


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


def summarize_transcript(transcript: str, meeting_type: str = "opp") -> SummaryResult:
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        messages=[{
            "role": "user",
            "content": _PROMPT_TEMPLATE.format(
                meeting_type="商談会議" if meeting_type == "opp" else "現場訪問",
                transcript=transcript,
            ),
        }],
    )

    raw = message.content[0].text.strip()
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
