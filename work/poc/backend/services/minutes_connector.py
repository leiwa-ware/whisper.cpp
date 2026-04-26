from abc import ABC, abstractmethod
from dataclasses import dataclass


class MinutesSource(ABC):
    """統一インターフェース。アダプターはこのクラスを継承する。"""

    @property
    @abstractmethod
    def source_type(self) -> str:
        ...

    @abstractmethod
    def to_markdown(self) -> str:
        ...


@dataclass
class WhisperCppAdapter(MinutesSource):
    raw_transcript: str
    opportunity_id: str
    participants: list[str]

    @property
    def source_type(self) -> str:
        return "whisper_cpp"

    def to_markdown(self) -> str:
        participant_list = "\n".join(f"- {p}" for p in self.participants)
        return (
            f"## 議事録\n\n"
            f"**商談ID**: {self.opportunity_id}  \n"
            f"**ソース**: whisper.cpp（自動文字起こし）\n\n"
            f"### 参加者\n{participant_list}\n\n"
            f"---\n\n{self.raw_transcript}"
        )


@dataclass
class M365CopilotAdapter(MinutesSource):
    raw_content: str
    opportunity_id: str
    participants: list[str]

    @property
    def source_type(self) -> str:
        return "m365"

    def to_markdown(self) -> str:
        participant_list = "\n".join(f"- {p}" for p in self.participants)
        converted = self.raw_content.replace("# Meeting Notes", "")
        converted = converted.replace("## Key Points", "### 主な議題")
        converted = converted.replace("## Action Items", "### アクションアイテム")
        return (
            f"## 議事録\n\n"
            f"**商談ID**: {self.opportunity_id}  \n"
            f"**ソース**: M365 Copilot（外部連携）\n\n"
            f"### 参加者\n{participant_list}\n\n"
            f"---\n\n{converted.strip()}"
        )
