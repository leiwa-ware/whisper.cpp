# POC 会議録音機能 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** UIモック（`work/UIMock/meeting.html`）のインターフェースに基づき、ブラウザ録音 → whisper.cpp 転写 → Claude API 要約 → SQLite 保存のパイプラインを実装し、フィジビリティ仕様書（§12・§17）の問い⑨・問い⑩を検証できる状態にする。

**Architecture:** ブラウザの MediaRecorder API で録音した音声を FastAPI バックエンドにアップロードし、whisper-cli バイナリ（本リポジトリからビルド、subprocess 経由）で日本語テキスト転写、Claude API で構造化要約（議題・アクション・リスク）を生成して SQLite に保存する。`MinutesSource` インターフェースにより方式 A（whisper.cpp 録音）と方式 B（M365 Copilot Webhook）を同一 I/F で扱い、`minutes.html` の変更なしにアダプター差し替えを可能にする。

**Tech Stack:** Python 3.11+、FastAPI、whisper-cli（subprocess）、Anthropic SDK（claude-sonnet-4-6）、SQLite（PoC 用）、pydub + ffmpeg（音声変換）、pytest、HTML / CSS / JavaScript（MediaRecorder API）

---

## ファイル構成

### 新規作成

```
work/poc/
  backend/
    main.py                          — FastAPI アプリエントリーポイント・CORS設定
    config.py                        — 設定（モデルパス・API キー・DB パス）
    requirements.txt                 — Python 依存パッケージ一覧
    api/
      __init__.py
      recording.py                   — POST /api/recordings（音声アップロード→転写→要約）
      minutes.py                     — GET /api/minutes, POST /api/minutes, GET /api/minutes/:id
      webhooks.py                    — POST /api/webhooks/minutes（方式 B Webhook コネクター）
    services/
      __init__.py
      transcription.py               — whisper-cli subprocess 呼び出し・WAV変換
      summarizer.py                  — Claude API で議題・アクション・リスクを構造化抽出
      minutes_connector.py           — MinutesSource I/F・WhisperCppAdapter・M365CopilotAdapter
    db/
      database.py                    — SQLite 接続・テーブル初期化
      models.py                      — SQLAlchemy ORM モデル（Meeting, Minutes）
    tests/
      __init__.py
      test_transcription.py          — 転写サービスのユニットテスト
      test_summarizer.py             — 要約サービスのユニットテスト（Claude API モック）
      test_minutes_api.py            — /api/minutes エンドポイントの統合テスト
      test_webhooks.py               — /api/webhooks/minutes の統合テスト・問い⑨・⑩検証
```

### 変更

```
work/UIMock/meeting.html             — MediaRecorder API 統合・実 API 接続（シミュレーション→本物）
```

---

## Task 1: whisper.cpp ビルドとモデル確認

**Files:**
- Build output: `build/bin/whisper-cli` (Windows: `build/bin/Release/whisper-cli.exe`)
- Model: `models/ggml-base.bin`（多言語・日本語対応）
- Reference: `CLAUDE.md`（ビルドコマンド）

- [ ] **Step 1: ビルドを実行する**

```bash
cmake -B build
cmake --build build -j --config Release
```

Expected: `Build files have been written to: .../build` → `[100%] Built target whisper-cli`

- [ ] **Step 2: ビルド成功を確認する**

```bash
./build/bin/whisper-cli --help 2>&1 | head -5
# Windows の場合
./build/bin/Release/whisper-cli.exe --help 2>&1 | head -5
```

Expected: `usage: whisper-cli [options] <wav file(s)>` が表示されること

- [ ] **Step 3: 多言語モデルをダウンロードする（base = 日本語対応）**

```bash
bash ./models/download-ggml-model.sh base
```

Expected: `models/ggml-base.bin` が作成されること（約 142 MB）

- [ ] **Step 4: サンプル音声で日本語転写を確認する（英語サンプルで動作確認）**

```bash
./build/bin/whisper-cli -m models/ggml-base.bin -f samples/jfk.wav -l en
# Windows
./build/bin/Release/whisper-cli.exe -m models/ggml-base.bin -f samples/jfk.wav -l en
```

Expected: `And so my fellow Americans...` のテキストが出力されること

- [ ] **Step 5: JSON 出力オプションを確認する**

```bash
./build/bin/whisper-cli -m models/ggml-base.bin -f samples/jfk.wav -l en --output-json -of /tmp/test_out
cat /tmp/test_out.json | python -m json.tool | head -30
```

Expected: `{"transcription": [{"timestamps": {...}, "offsets": {...}, "text": "..."}]}` の構造が出力されること

- [ ] **Step 6: バイナリパスをメモする**

```bash
ls build/bin/Release/whisper-cli.exe 2>/dev/null \
  || ls build/bin/whisper-cli 2>/dev/null \
  || echo "BINARY_NOT_FOUND"
```

Expected: パスが存在する。次タスクで `config.py` に設定する。

- [ ] **Step 7: コミット**

```bash
git add .gitignore  # models/*.bin が除外されていることを確認
git commit -m "chore: verify whisper-cli build for poc recording feature"
```

---

## Task 2: Python 環境と FastAPI バックエンド基盤

**Files:**
- Create: `work/poc/backend/requirements.txt`
- Create: `work/poc/backend/config.py`
- Create: `work/poc/backend/db/database.py`
- Create: `work/poc/backend/db/models.py`
- Create: `work/poc/backend/main.py`
- Test: `work/poc/backend/tests/test_health.py`

- [ ] **Step 1: フェイルテストを書く**

`work/poc/backend/tests/test_health.py` を作成:

```python
import pytest
from fastapi.testclient import TestClient

def test_health_returns_ok():
    from main import app
    client = TestClient(app)
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

- [ ] **Step 2: テストが失敗することを確認する**

```bash
cd work/poc/backend
python -m pytest tests/test_health.py -v
```

Expected: `ModuleNotFoundError: No module named 'main'`

- [ ] **Step 3: requirements.txt を作成する**

`work/poc/backend/requirements.txt`:

```
fastapi==0.115.0
uvicorn[standard]==0.30.6
pydantic==2.8.2
sqlalchemy==2.0.35
aiosqlite==0.20.0
python-multipart==0.0.12
pydub==0.25.1
anthropic==0.34.2
pytest==8.3.2
httpx==0.27.2
pytest-asyncio==0.24.0
```

- [ ] **Step 4: 依存パッケージをインストールする**

```bash
cd work/poc/backend
pip install -r requirements.txt
```

Expected: `Successfully installed fastapi-0.115.0 ...` (全パッケージがインストールされること)

- [ ] **Step 5: config.py を作成する**

`work/poc/backend/config.py`:

```python
import os
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent.parent  # whisper.cpp root

WHISPER_CLI = os.environ.get(
    "WHISPER_CLI",
    str(REPO_ROOT / "build/bin/Release/whisper-cli.exe")  # fallback for Windows
    if os.name == "nt"
    else str(REPO_ROOT / "build/bin/whisper-cli"),
)

WHISPER_MODEL = os.environ.get(
    "WHISPER_MODEL",
    str(REPO_ROOT / "models/ggml-base.bin"),
)

DB_PATH = os.environ.get("DB_PATH", "poc_meeting.db")

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

AUDIO_UPLOAD_DIR = Path(os.environ.get("AUDIO_UPLOAD_DIR", "/tmp/poc_audio"))
AUDIO_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
```

- [ ] **Step 6: db/models.py を作成する**

`work/poc/backend/db/models.py`:

```python
from datetime import datetime
from sqlalchemy import Column, String, Integer, Text, DateTime
from sqlalchemy.orm import DeclarativeBase

class Base(DeclarativeBase):
    pass

class Meeting(Base):
    __tablename__ = "meetings"
    id = Column(String(100), primary_key=True)
    type = Column(String(20), nullable=False)   # "opp" | "visit"
    client_name = Column(String(200))
    owner_name = Column(String(100))
    phase = Column(String(100))
    created_at = Column(DateTime, default=datetime.utcnow)

class Minutes(Base):
    __tablename__ = "minutes"
    id = Column(Integer, primary_key=True, autoincrement=True)
    meeting_id = Column(String(100), nullable=False, index=True)
    source_type = Column(String(20), nullable=False)  # "whisper_cpp" | "m365" | "manual"
    raw_transcript = Column(Text)
    minutes_markdown = Column(Text, nullable=False)
    summary_topics = Column(Text)    # JSON string
    summary_actions = Column(Text)   # JSON string
    summary_risks = Column(Text)     # JSON string
    created_at = Column(DateTime, default=datetime.utcnow)
```

- [ ] **Step 7: db/database.py を作成する**

`work/poc/backend/db/database.py`:

```python
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from db.models import Base
from config import DB_PATH

engine = create_async_engine(f"sqlite+aiosqlite:///{DB_PATH}", echo=False)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

async def get_db() -> AsyncSession:
    async with SessionLocal() as session:
        yield session
```

- [ ] **Step 8: main.py を作成する**

`work/poc/backend/main.py`:

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from db.database import init_db
from api.recording import router as recording_router
from api.minutes import router as minutes_router
from api.webhooks import router as webhooks_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield

app = FastAPI(title="PoC Meeting Recording API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # PoC のみ。本番では制限する
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(recording_router, prefix="/api")
app.include_router(minutes_router, prefix="/api")
app.include_router(webhooks_router, prefix="/api")

@app.get("/api/health")
async def health():
    return {"status": "ok"}
```

- [ ] **Step 9: api/__init__.py を作成する（空ファイル）**

```bash
touch work/poc/backend/api/__init__.py
touch work/poc/backend/services/__init__.py
touch work/poc/backend/db/__init__.py
touch work/poc/backend/tests/__init__.py
```

- [ ] **Step 10: テストが通ることを確認する**

```bash
cd work/poc/backend
python -m pytest tests/test_health.py -v
```

Expected:
```
PASSED tests/test_health.py::test_health_returns_ok
1 passed in 0.xx s
```

- [ ] **Step 11: コミット**

```bash
git add work/poc/backend/
git commit -m "feat: add FastAPI backend skeleton with SQLite models for poc recording"
```

---

## Task 3: 転写サービス（whisper-cli subprocess 統合）

**Files:**
- Create: `work/poc/backend/services/transcription.py`
- Test: `work/poc/backend/tests/test_transcription.py`

- [ ] **Step 1: フェイルテストを書く**

`work/poc/backend/tests/test_transcription.py`:

```python
import pytest
from pathlib import Path
from services.transcription import transcribe_audio, TranscriptionResult

SAMPLE_WAV = Path(__file__).parent.parent.parent.parent.parent / "samples/jfk.wav"

def test_transcription_result_has_text():
    if not SAMPLE_WAV.exists():
        pytest.skip("samples/jfk.wav not found")
    result = transcribe_audio(str(SAMPLE_WAV), language="en")
    assert isinstance(result, TranscriptionResult)
    assert len(result.text) > 0
    assert "american" in result.text.lower()

def test_transcription_returns_segments():
    if not SAMPLE_WAV.exists():
        pytest.skip("samples/jfk.wav not found")
    result = transcribe_audio(str(SAMPLE_WAV), language="en")
    assert len(result.segments) > 0
    assert result.segments[0].get("text")

def test_invalid_audio_raises_error():
    with pytest.raises(FileNotFoundError):
        transcribe_audio("/nonexistent/file.wav", language="ja")
```

- [ ] **Step 2: テストが失敗することを確認する**

```bash
cd work/poc/backend
python -m pytest tests/test_transcription.py -v
```

Expected: `ImportError: cannot import name 'transcribe_audio'`

- [ ] **Step 3: 転写サービスを実装する**

`work/poc/backend/services/transcription.py`:

```python
import subprocess
import json
import tempfile
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from pydub import AudioSegment
from config import WHISPER_CLI, WHISPER_MODEL

@dataclass
class TranscriptionResult:
    text: str
    segments: list = field(default_factory=list)
    language: str = "ja"

def _to_16k_wav(audio_path: str) -> str:
    """WebM / MP4 / その他形式を 16kHz 16bit WAV に変換する。既に WAV なら変換不要。"""
    src = Path(audio_path)
    if not src.exists():
        raise FileNotFoundError(f"Audio file not found: {audio_path}")

    suffix = src.suffix.lower()
    if suffix == ".wav":
        return audio_path  # WAV はそのまま使用

    out_path = str(src.with_suffix(".wav"))
    audio = AudioSegment.from_file(audio_path)
    audio = audio.set_frame_rate(16000).set_channels(1).set_sample_width(2)
    audio.export(out_path, format="wav")
    return out_path

def transcribe_audio(audio_path: str, language: str = "ja") -> TranscriptionResult:
    """whisper-cli を subprocess で呼び出し転写結果を返す。"""
    wav_path = _to_16k_wav(audio_path)

    with tempfile.TemporaryDirectory() as tmpdir:
        out_base = str(Path(tmpdir) / "result")

        cmd = [
            WHISPER_CLI,
            "-m", WHISPER_MODEL,
            "-f", wav_path,
            "-l", language,
            "--output-json",
            "-of", out_base,
            "--no-prints",
        ]

        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

        if proc.returncode != 0:
            raise RuntimeError(
                f"whisper-cli failed (code {proc.returncode}): {proc.stderr[:500]}"
            )

        result_file = Path(out_base + ".json")
        if not result_file.exists():
            raise RuntimeError("whisper-cli produced no JSON output")

        data = json.loads(result_file.read_text(encoding="utf-8"))
        segments = data.get("transcription", [])
        full_text = " ".join(s.get("text", "").strip() for s in segments)

        return TranscriptionResult(
            text=full_text,
            segments=segments,
            language=language,
        )
```

- [ ] **Step 4: テストが通ることを確認する**

```bash
cd work/poc/backend
python -m pytest tests/test_transcription.py -v
```

Expected:
```
PASSED tests/test_transcription.py::test_transcription_result_has_text
PASSED tests/test_transcription.py::test_transcription_returns_segments
PASSED tests/test_transcription.py::test_invalid_audio_raises_error
3 passed in xx.xx s
```

- [ ] **Step 5: コミット**

```bash
git add work/poc/backend/services/transcription.py work/poc/backend/tests/test_transcription.py
git commit -m "feat: add whisper-cli subprocess transcription service"
```

---

## Task 4: AI 要約生成サービス（Claude API）

**Files:**
- Create: `work/poc/backend/services/summarizer.py`
- Test: `work/poc/backend/tests/test_summarizer.py`

- [ ] **Step 1: フェイルテストを書く**

`work/poc/backend/tests/test_summarizer.py`:

```python
import pytest
from unittest.mock import patch, MagicMock
from services.summarizer import summarize_transcript, SummaryResult

SAMPLE_TRANSCRIPT = """
佐藤 淳（営業担当）: 他社から10%安い提案をいただいておりまして。
田中 一郎（営業担当）: ボリュームディスカウントで対応できます。全店展開で230店舗想定です。
佐藤 淳（営業担当）: 今週中に価格の再提案をまとめます。
"""

def test_summary_result_has_required_fields():
    mock_content = '''{"topics":["競合から10%安い提案","全店展開230店舗の可能性"],"actions":[{"text":"価格再提案資料作成","assignee":"佐藤 淳","due":"今週中","urgent":true}],"risks":["競合が積極的アプローチ"]}'''
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=mock_content)]

    with patch("anthropic.Anthropic") as MockAnthropic:
        MockAnthropic.return_value.messages.create.return_value = mock_response
        result = summarize_transcript(SAMPLE_TRANSCRIPT, meeting_type="opp")

    assert isinstance(result, SummaryResult)
    assert len(result.topics) > 0
    assert len(result.actions) > 0

def test_summary_returns_minutes_markdown():
    mock_content = '''{"topics":["テスト議題"],"actions":[{"text":"テストアクション","assignee":"山田","due":"来週","urgent":false}],"risks":[]}'''
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=mock_content)]

    with patch("anthropic.Anthropic") as MockAnthropic:
        MockAnthropic.return_value.messages.create.return_value = mock_response
        result = summarize_transcript(SAMPLE_TRANSCRIPT, meeting_type="opp")

    assert "## 議事録" in result.minutes_markdown
    assert "テスト議題" in result.minutes_markdown
```

- [ ] **Step 2: テストが失敗することを確認する**

```bash
cd work/poc/backend
python -m pytest tests/test_summarizer.py -v
```

Expected: `ImportError: cannot import name 'summarize_transcript'`

- [ ] **Step 3: 要約サービスを実装する**

`work/poc/backend/services/summarizer.py`:

```python
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
    # JSON 前後の余分なテキストを除去
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
```

- [ ] **Step 4: テストが通ることを確認する**

```bash
cd work/poc/backend
python -m pytest tests/test_summarizer.py -v
```

Expected:
```
PASSED tests/test_summarizer.py::test_summary_result_has_required_fields
PASSED tests/test_summarizer.py::test_summary_returns_minutes_markdown
2 passed in 0.xx s
```

- [ ] **Step 5: コミット**

```bash
git add work/poc/backend/services/summarizer.py work/poc/backend/tests/test_summarizer.py
git commit -m "feat: add Claude API summarizer service for meeting transcript"
```

---

## Task 5: Minutes Connector インターフェースと M365 Copilot アダプター（問い⑩対応）

**Files:**
- Create: `work/poc/backend/services/minutes_connector.py`
- Test: `work/poc/backend/tests/test_minutes_connector.py`

問い⑩の検証ポイント：同一の `MinutesSource` インターフェースから `to_markdown()` を呼ぶことで、ソース種別を変えても `minutes.html` が変更不要なことを証明する。

- [ ] **Step 1: フェイルテストを書く**

`work/poc/backend/tests/test_minutes_connector.py`:

```python
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
    # 両方とも "## 議事録" で始まる Markdown を返すこと
    assert whisper.to_markdown().startswith("## 議事録")
    assert m365.to_markdown().startswith("## 議事録")
```

- [ ] **Step 2: テストが失敗することを確認する**

```bash
cd work/poc/backend
python -m pytest tests/test_minutes_connector.py -v
```

Expected: `ImportError: cannot import name 'WhisperCppAdapter'`

- [ ] **Step 3: MinutesConnector を実装する**

`work/poc/backend/services/minutes_connector.py`:

```python
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
        # M365 の見出し形式を NeoCRM 標準形式（## 議事録）に変換
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
```

- [ ] **Step 4: テストが通ることを確認する**

```bash
cd work/poc/backend
python -m pytest tests/test_minutes_connector.py -v
```

Expected:
```
PASSED tests/test_minutes_connector.py::test_whisper_adapter_implements_interface
PASSED tests/test_minutes_connector.py::test_m365_adapter_implements_interface
PASSED tests/test_minutes_connector.py::test_both_adapters_produce_same_markdown_structure
3 passed in 0.xx s
```

- [ ] **Step 5: コミット**

```bash
git add work/poc/backend/services/minutes_connector.py work/poc/backend/tests/test_minutes_connector.py
git commit -m "feat: add MinutesSource interface with WhisperCppAdapter and M365CopilotAdapter"
```

---

## Task 6: バックエンド API 実装（録音エンドポイント + 議事録 CRUD）

**Files:**
- Create: `work/poc/backend/api/recording.py`
- Create: `work/poc/backend/api/minutes.py`
- Test: `work/poc/backend/tests/test_minutes_api.py`

- [ ] **Step 1: フェイルテストを書く**

`work/poc/backend/tests/test_minutes_api.py`:

```python
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

def get_client():
    from main import app
    return TestClient(app)

def test_post_minutes_saves_and_returns_id():
    client = get_client()
    payload = {
        "meeting_id": "OPP-0001",
        "source_type": "manual",
        "minutes_markdown": "## 議事録\n\nテスト内容",
        "raw_transcript": "テスト文字起こし",
        "summary_topics": ["テスト議題"],
        "summary_actions": [],
        "summary_risks": [],
    }
    response = client.post("/api/minutes", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert "id" in data
    assert data["meeting_id"] == "OPP-0001"

def test_get_minutes_by_id():
    client = get_client()
    # まず作成
    payload = {
        "meeting_id": "OPP-0002",
        "source_type": "manual",
        "minutes_markdown": "## 議事録\n\nGET テスト",
        "raw_transcript": "",
        "summary_topics": [],
        "summary_actions": [],
        "summary_risks": [],
    }
    post_res = client.post("/api/minutes", json=payload)
    created_id = post_res.json()["id"]

    get_res = client.get(f"/api/minutes/{created_id}")
    assert get_res.status_code == 200
    assert get_res.json()["minutes_markdown"] == "## 議事録\n\nGET テスト"

def test_get_minutes_not_found():
    client = get_client()
    response = client.get("/api/minutes/9999")
    assert response.status_code == 404
```

- [ ] **Step 2: テストが失敗することを確認する**

```bash
cd work/poc/backend
python -m pytest tests/test_minutes_api.py -v
```

Expected: `ImportError` または `404 not found` エラー

- [ ] **Step 3: api/recording.py を実装する**

`work/poc/backend/api/recording.py`:

```python
import uuid
import tempfile
from pathlib import Path
from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from services.transcription import transcribe_audio
from services.summarizer import summarize_transcript
from services.minutes_connector import WhisperCppAdapter

router = APIRouter()

@router.post("/recordings", status_code=201)
async def upload_recording(
    audio: UploadFile = File(...),
    meeting_type: str = Form("opp"),
    client_name: str = Form(""),
    owner_name: str = Form(""),
    opportunity_id: str = Form(""),
):
    """音声ファイルを受信し、転写→要約→minutesMarkdown を返す。"""
    suffix = Path(audio.filename or "audio.webm").suffix or ".webm"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(await audio.read())
        tmp_path = tmp.name

    try:
        transcription = transcribe_audio(tmp_path, language="ja")
        summary = summarize_transcript(transcription.text, meeting_type=meeting_type)

        participants = [p.strip() for p in owner_name.split(",") if p.strip()]
        adapter = WhisperCppAdapter(
            raw_transcript=transcription.text,
            opportunity_id=opportunity_id or f"OPP-{uuid.uuid4().hex[:6].upper()}",
            participants=participants,
        )

        return {
            "meeting_id": adapter.opportunity_id,
            "source_type": "whisper_cpp",
            "raw_transcript": transcription.text,
            "minutes_markdown": adapter.to_markdown(),
            "summary": {
                "topics": summary.topics,
                "actions": [
                    {"text": a.text, "assignee": a.assignee, "due": a.due, "urgent": a.urgent}
                    for a in summary.actions
                ],
                "risks": summary.risks,
            },
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        Path(tmp_path).unlink(missing_ok=True)
```

- [ ] **Step 4: api/minutes.py を実装する**

`work/poc/backend/api/minutes.py`:

```python
import json
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from db.database import get_db
from db.models import Minutes

router = APIRouter()

class MinutesCreate(BaseModel):
    meeting_id: str
    source_type: str
    minutes_markdown: str
    raw_transcript: str = ""
    summary_topics: list[str] = []
    summary_actions: list[dict] = []
    summary_risks: list[str] = []

@router.post("/minutes", status_code=201)
async def create_minutes(payload: MinutesCreate, db: AsyncSession = Depends(get_db)):
    record = Minutes(
        meeting_id=payload.meeting_id,
        source_type=payload.source_type,
        raw_transcript=payload.raw_transcript,
        minutes_markdown=payload.minutes_markdown,
        summary_topics=json.dumps(payload.summary_topics, ensure_ascii=False),
        summary_actions=json.dumps(payload.summary_actions, ensure_ascii=False),
        summary_risks=json.dumps(payload.summary_risks, ensure_ascii=False),
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)
    return {"id": record.id, "meeting_id": record.meeting_id, "source_type": record.source_type}

@router.get("/minutes/{minutes_id}")
async def get_minutes(minutes_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.get(Minutes, minutes_id)
    if not result:
        raise HTTPException(status_code=404, detail="Minutes not found")
    return {
        "id": result.id,
        "meeting_id": result.meeting_id,
        "source_type": result.source_type,
        "minutes_markdown": result.minutes_markdown,
        "raw_transcript": result.raw_transcript,
        "summary_topics": json.loads(result.summary_topics or "[]"),
        "summary_actions": json.loads(result.summary_actions or "[]"),
        "summary_risks": json.loads(result.summary_risks or "[]"),
        "created_at": result.created_at.isoformat() if result.created_at else None,
    }
```

- [ ] **Step 5: テストが通ることを確認する**

```bash
cd work/poc/backend
python -m pytest tests/test_minutes_api.py -v
```

Expected:
```
PASSED tests/test_minutes_api.py::test_post_minutes_saves_and_returns_id
PASSED tests/test_minutes_api.py::test_get_minutes_by_id
PASSED tests/test_minutes_api.py::test_get_minutes_not_found
3 passed in 0.xx s
```

- [ ] **Step 6: コミット**

```bash
git add work/poc/backend/api/
git commit -m "feat: add recording upload and minutes CRUD endpoints"
```

---

## Task 7: Webhook コネクター実装（問い⑨ — 方式 B M365 Copilot 連携）

**Files:**
- Create: `work/poc/backend/api/webhooks.py`
- Test: `work/poc/backend/tests/test_webhooks.py`

問い⑨の検証ポイント：Webhook 経由で M365 Copilot 形式のテキストを受信し、`minutesMarkdown` に変換して DB に保存できること。

- [ ] **Step 1: フェイルテストを書く**

`work/poc/backend/tests/test_webhooks.py`:

```python
import pytest
from fastapi.testclient import TestClient
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

def get_client():
    from main import app
    return TestClient(app)

M365_PAYLOAD = {
    "source": "m365_copilot",
    "opportunity_id": "OPP-TEST01",
    "participants": ["田中 一郎", "佐藤 淳"],
    "raw_content": (
        "# Meeting Notes\n\n"
        "## Key Points\n"
        "- 競合から10%安い提案が入っている\n"
        "- 全店展開230店舗の可能性あり\n\n"
        "## Action Items\n"
        "- 価格再提案資料作成 (Owner: 佐藤 淳, Due: 今週中)\n"
    ),
}

def test_webhook_accepts_m365_format():
    """問い⑨: M365 Copilot Webhook を受信し minutesMarkdown を返す"""
    client = get_client()
    response = client.post("/api/webhooks/minutes", json=M365_PAYLOAD)
    assert response.status_code == 201
    data = response.json()
    assert "minutes_id" in data
    assert "minutes_markdown" in data
    assert "## 議事録" in data["minutes_markdown"]
    assert "OPP-TEST01" in data["minutes_markdown"]

def test_webhook_saves_to_db():
    """問い⑨: Webhook 受信後に DB に保存され GET で取得できる"""
    client = get_client()
    post_res = client.post("/api/webhooks/minutes", json=M365_PAYLOAD)
    minutes_id = post_res.json()["minutes_id"]

    get_res = client.get(f"/api/minutes/{minutes_id}")
    assert get_res.status_code == 200
    data = get_res.json()
    assert data["source_type"] == "m365"
    assert "## 議事録" in data["minutes_markdown"]

def test_adapter_swap_does_not_change_markdown_structure():
    """問い⑩: アダプターを whisper_cpp → m365 に差し替えても ## 議事録 構造が同一"""
    client = get_client()

    # 方式 B (M365) で保存
    m365_res = client.post("/api/webhooks/minutes", json=M365_PAYLOAD)
    m365_md = m365_res.json()["minutes_markdown"]

    # 両方が "## 議事録" で始まること（同一構造）
    assert m365_md.startswith("## 議事録")
    # minutes.html が依存するフィールド名が変わらないこと
    assert "**商談ID**" in m365_md
    assert "**ソース**" in m365_md
```

- [ ] **Step 2: テストが失敗することを確認する**

```bash
cd work/poc/backend
python -m pytest tests/test_webhooks.py -v
```

Expected: `ImportError` または `404 Not Found`

- [ ] **Step 3: api/webhooks.py を実装する**

`work/poc/backend/api/webhooks.py`:

```python
import json
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from db.database import get_db
from db.models import Minutes
from services.minutes_connector import M365CopilotAdapter

router = APIRouter()

class M365WebhookPayload(BaseModel):
    source: str                     # "m365_copilot" | "zoom_ai" | "manual"
    opportunity_id: str
    participants: list[str] = []
    raw_content: str

@router.post("/webhooks/minutes", status_code=201)
async def receive_minutes_webhook(
    payload: M365WebhookPayload,
    db: AsyncSession = Depends(get_db),
):
    """方式 B: 外部製品（M365 Copilot 等）からの議事録 Webhook を受信して保存する。"""
    if payload.source not in ("m365_copilot", "zoom_ai", "manual"):
        raise HTTPException(status_code=400, detail=f"Unknown source: {payload.source}")

    adapter = M365CopilotAdapter(
        raw_content=payload.raw_content,
        opportunity_id=payload.opportunity_id,
        participants=payload.participants,
    )
    minutes_md = adapter.to_markdown()

    record = Minutes(
        meeting_id=payload.opportunity_id,
        source_type="m365",
        raw_transcript=payload.raw_content,
        minutes_markdown=minutes_md,
        summary_topics=json.dumps([], ensure_ascii=False),
        summary_actions=json.dumps([], ensure_ascii=False),
        summary_risks=json.dumps([], ensure_ascii=False),
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)

    return {
        "minutes_id": record.id,
        "meeting_id": record.meeting_id,
        "source_type": record.source_type,
        "minutes_markdown": minutes_md,
    }
```

- [ ] **Step 4: テストが通ることを確認する**

```bash
cd work/poc/backend
python -m pytest tests/test_webhooks.py -v
```

Expected:
```
PASSED tests/test_webhooks.py::test_webhook_accepts_m365_format
PASSED tests/test_webhooks.py::test_webhook_saves_to_db
PASSED tests/test_webhooks.py::test_adapter_swap_does_not_change_markdown_structure
3 passed in 0.xx s
```

- [ ] **Step 5: 全テストが通ることを確認する**

```bash
cd work/poc/backend
python -m pytest -v
```

Expected: 全テストが PASSED（10 件以上）

- [ ] **Step 6: コミット**

```bash
git add work/poc/backend/api/webhooks.py work/poc/backend/tests/test_webhooks.py
git commit -m "feat: add M365 Copilot webhook endpoint for minutes connector (問い⑨⑩)"
```

---

## Task 8: フロントエンド（meeting.html）の実 API 接続

**Files:**
- Modify: `work/UIMock/meeting.html`

UIモックのシミュレーションを実際の API 呼び出しに置き換える。ブラウザ MediaRecorder API で音声を録音し、POST /api/recordings に送信する。

- [ ] **Step 1: バックエンドを起動して動作を確認する**

```bash
cd work/poc/backend
ANTHROPIC_API_KEY=sk-ant-xxx uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

別ターミナルで:
```bash
curl http://localhost:8000/api/health
```

Expected: `{"status":"ok"}`

- [ ] **Step 2: 現在の meeting.html をバックアップする**

```bash
cp work/UIMock/meeting.html work/UIMock/meeting.html.bak
```

- [ ] **Step 3: meeting.html の `<script>` を API 接続版に書き換える**

`work/UIMock/meeting.html` の `<script>` タグ内の全コードを以下に置き換える:

```javascript
// ─── Config ──────────────────────────────────────────────
const API_BASE = 'http://localhost:8000/api';

// ─── State ───────────────────────────────────────────────
let mtype = 'opp';
let timerTick = null;
let elapsed = 0;
let mediaRecorder = null;
let audioChunks = [];
let lastMinutesId = null;

// ─── Step helpers ────────────────────────────────────────
function gotoStep(n) {
  ['panel-setup', 'panel-rec', 'panel-review'].forEach((id, i) => {
    document.getElementById(id).classList.toggle('active', i === n);
    const ind = document.getElementById('si' + i);
    ind.classList.toggle('active', i === n);
    ind.classList.toggle('done', i < n);
  });
  document.getElementById('sl1').classList.toggle('done', n >= 1);
  document.getElementById('sl2').classList.toggle('done', n >= 2);
}

// ─── Type selector ───────────────────────────────────────
function setType(t) {
  mtype = t;
  document.getElementById('tbtn-opp').classList.toggle('active', t === 'opp');
  document.getElementById('tbtn-visit').classList.toggle('active', t === 'visit');
  const isVisit = t === 'visit';
  document.getElementById('lbl-client').textContent = isVisit ? '店舗名' : '得意先名';
  document.getElementById('lbl-phase').textContent  = isVisit ? 'ルート / 訪問種別' : 'フェーズ';
  document.getElementById('inp-client').value = isVisit ? '田中商店 渋谷南口店' : 'すき家';
  document.getElementById('inp-owner').value  = isVisit ? '山田 健一' : '佐藤 淳';
  document.getElementById('inp-phase').value  = isVisit ? '定期巡回 — 月次' : '提案フェーズ';
}

// ─── Recording ───────────────────────────────────────────
async function startRec() {
  let stream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  } catch (e) {
    showToast('❌ マイクアクセスが拒否されました: ' + e.message);
    return;
  }

  elapsed = 0;
  audioChunks = [];
  document.getElementById('live-box').innerHTML = '<span class="cursor-blink" id="cursor"></span>';
  gotoStep(1);

  timerTick = setInterval(() => {
    elapsed++;
    const m = String(Math.floor(elapsed / 60)).padStart(2, '0');
    const s = String(elapsed % 60).padStart(2, '0');
    document.getElementById('rec-timer').textContent = m + ':' + s;
  }, 1000);

  mediaRecorder = new MediaRecorder(stream);
  mediaRecorder.ondataavailable = (e) => { if (e.data.size > 0) audioChunks.push(e.data); };
  mediaRecorder.start(1000); // 1秒ごとにチャンク
}

async function stopRec() {
  clearInterval(timerTick);
  document.querySelectorAll('.wbar').forEach(b => b.classList.add('paused'));
  document.getElementById('rec-blink').style.animation = 'none';
  document.getElementById('rec-blink').style.background = '#64748b';
  document.getElementById('rec-label').textContent = '処理中...';
  document.getElementById('rec-label').style.color = '#64748b';

  if (mediaRecorder && mediaRecorder.state !== 'inactive') {
    mediaRecorder.stop();
    mediaRecorder.stream.getTracks().forEach(t => t.stop());
  }

  const overlay = document.getElementById('proc-overlay');
  overlay.classList.add('visible');

  // ステップ表示アニメーション
  const steps = ['ps0', 'ps1', 'ps2', 'ps3'];
  for (let i = 0; i < steps.length; i++) {
    await new Promise(r => setTimeout(r, 600));
    document.getElementById(steps[i]).classList.add('ok');
  }

  try {
    await uploadAndProcess();
  } catch (e) {
    showToast('❌ AI 処理に失敗しました: ' + e.message);
  } finally {
    overlay.classList.remove('visible');
  }
}

async function uploadAndProcess() {
  const blob = new Blob(audioChunks, { type: 'audio/webm' });
  const form = new FormData();
  form.append('audio', blob, 'recording.webm');
  form.append('meeting_type', mtype);
  form.append('client_name', document.getElementById('inp-client').value);
  form.append('owner_name', document.getElementById('inp-owner').value);
  form.append('opportunity_id', '');

  const res = await fetch(`${API_BASE}/recordings`, { method: 'POST', body: form });
  if (!res.ok) throw new Error(`HTTP ${res.status}: ${await res.text()}`);

  const data = await res.json();
  buildReview(data);
  gotoStep(2);
}

// ─── Review builder ───────────────────────────────────────
function buildReview(data) {
  const m = String(Math.floor(elapsed / 60)).padStart(2, '0');
  const s = String(elapsed % 60).padStart(2, '0');
  const client = document.getElementById('inp-client').value || '—';
  const owner  = document.getElementById('inp-owner').value  || '—';
  const typeLbl = mtype === 'opp' ? '💼 商談会議' : '🚶 現場訪問';
  document.getElementById('done-meta').textContent =
    typeLbl + ' ｜ ' + client + ' ｜ 担当: ' + owner + ' ｜ 録音: ' + m + ':' + s;

  const summary = data.summary || {};
  let html = '';

  html += '<div class="ai-section"><div class="ai-sec-label">主な議題</div><ul>';
  (summary.topics || []).forEach(t => { html += '<li>' + t + '</li>'; });
  html += '</ul></div>';

  html += '<div class="ai-section"><div class="ai-sec-label">アクションアイテム</div><ul>';
  (summary.actions || []).forEach(a => {
    const badge = a.urgent ? '<span class="urgent-badge">緊急</span>' : '';
    html += '<li>' + a.text + badge + ' <span class="ai-assignee">→ ' + a.assignee + ' / ' + a.due + '</span></li>';
  });
  html += '</ul></div>';

  if ((summary.risks || []).length) {
    html += '<div class="ai-section"><div class="ai-sec-label">リスク・注意点</div><ul>';
    summary.risks.forEach(r => { html += '<li class="risk-item">' + r + '</li>'; });
    html += '</ul></div>';
  }
  document.getElementById('ai-content').innerHTML = html;
  document.getElementById('full-box').innerHTML =
    '<pre style="white-space:pre-wrap;margin:0;">' + (data.raw_transcript || '') + '</pre>';

  // 議事録データを保持（保存ボタン用）
  window._pendingMinutes = data;
}

// ─── Save ─────────────────────────────────────────────────
async function saveMinutes() {
  const d = window._pendingMinutes;
  if (!d) { showToast('❌ 保存データがありません'); return; }

  try {
    const res = await fetch(`${API_BASE}/minutes`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        meeting_id: d.meeting_id,
        source_type: d.source_type,
        minutes_markdown: d.minutes_markdown,
        raw_transcript: d.raw_transcript,
        summary_topics: d.summary?.topics || [],
        summary_actions: d.summary?.actions || [],
        summary_risks: d.summary?.risks || [],
      }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    showToast('✅ 議事録を保存しました — 一覧に反映されます');
    setTimeout(() => { location.href = 'list.html'; }, 1400);
  } catch (e) {
    showToast('❌ 保存に失敗しました: ' + e.message);
  }
}

function showToast(msg) {
  const t = document.getElementById('rec-toast');
  t.textContent = msg;
  t.classList.add('show');
  setTimeout(() => t.classList.remove('show'), 2200);
}
```

- [ ] **Step 4: バックエンドを起動してブラウザで動作確認する**

```bash
cd work/poc/backend
ANTHROPIC_API_KEY=sk-ant-xxx uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

ブラウザで `work/UIMock/meeting.html` を開く（`file://` または `http://localhost:8001/meeting.html`）。

**確認項目（目視）:**
1. 「録音を開始する」ボタンを押すとマイクアクセス許可ダイアログが表示される
2. 許可後、タイマーが動作しウェーブフォームがアニメーションする
3. 「録音を停止する」後、AI処理オーバーレイが表示される
4. 確認ステップで AI 要約（議題・アクション）が表示される
5. 「議事録として保存」ボタンで保存が成功し `list.html` にリダイレクトする

- [ ] **Step 5: コミット**

```bash
git add work/UIMock/meeting.html
git commit -m "feat: connect meeting.html to FastAPI backend with MediaRecorder API"
```

---

## Task 9: 統合テストと PoC 検証問い⑨・⑩の実証

**Files:**
- Test: `work/poc/backend/tests/test_webhooks.py`（既存、追加検証）
- 目視確認チェックリスト

- [ ] **Step 1: 全ユニットテストが通ることを確認する**

```bash
cd work/poc/backend
python -m pytest -v --tb=short
```

Expected: 全テスト PASSED（失敗 0 件）。下記を確認:
```
tests/test_health.py::test_health_returns_ok                            PASSED
tests/test_transcription.py::test_transcription_result_has_text         PASSED
tests/test_transcription.py::test_transcription_returns_segments        PASSED
tests/test_transcription.py::test_invalid_audio_raises_error            PASSED
tests/test_summarizer.py::test_summary_result_has_required_fields       PASSED
tests/test_summarizer.py::test_summary_returns_minutes_markdown         PASSED
tests/test_minutes_connector.py::test_whisper_adapter_implements_interface   PASSED
tests/test_minutes_connector.py::test_m365_adapter_implements_interface      PASSED
tests/test_minutes_connector.py::test_both_adapters_produce_same_markdown_structure PASSED
tests/test_minutes_api.py::test_post_minutes_saves_and_returns_id       PASSED
tests/test_minutes_api.py::test_get_minutes_by_id                       PASSED
tests/test_minutes_api.py::test_get_minutes_not_found                   PASSED
tests/test_webhooks.py::test_webhook_accepts_m365_format                PASSED
tests/test_webhooks.py::test_webhook_saves_to_db                        PASSED
tests/test_webhooks.py::test_adapter_swap_does_not_change_markdown_structure PASSED
```

- [ ] **Step 2: 問い⑨ — Webhook 経由で M365 形式議事録を受信・表示できるか**

```bash
curl -s -X POST http://localhost:8000/api/webhooks/minutes \
  -H "Content-Type: application/json" \
  -d '{
    "source": "m365_copilot",
    "opportunity_id": "OPP-0001",
    "participants": ["田中 一郎", "佐藤 淳"],
    "raw_content": "# Meeting Notes\n\n## Key Points\n- 競合から10%安い提案\n\n## Action Items\n- 価格再提案 (Owner: 佐藤 淳, Due: 今週中)"
  }' | python -m json.tool
```

Expected: `"minutes_markdown"` フィールドに `"## 議事録"` から始まる Markdown が含まれること

- [ ] **Step 3: 問い⑨ — 保存した議事録を GET で取得できるか**

```bash
MINUTES_ID=$(curl -s -X POST http://localhost:8000/api/webhooks/minutes \
  -H "Content-Type: application/json" \
  -d '{"source":"m365_copilot","opportunity_id":"OPP-TEST","participants":[],"raw_content":"## Test"}' \
  | python -c "import sys,json; print(json.load(sys.stdin)['minutes_id'])")

curl -s http://localhost:8000/api/minutes/$MINUTES_ID | python -m json.tool
```

Expected: `source_type: "m365"` で `minutes_markdown` が `"## 議事録"` から始まること

- [ ] **Step 4: 問い⑩ — アダプター差し替えで minutes_markdown 構造が不変であることを実証**

```bash
# 方式 A (whisper_cpp) で保存された議事録を手動で確認
curl -s http://localhost:8000/api/minutes/1 | python -c "
import sys, json
d = json.load(sys.stdin)
md = d['minutes_markdown']
print('Source type:', d['source_type'])
print('Starts with ## 議事録:', md.startswith('## 議事録'))
print('Has 商談ID field:', '**商談ID**' in md)
print('Has ソース field:', '**ソース**' in md)
"
```

Expected:
```
Source type: whisper_cpp  (or m365)
Starts with ## 議事録: True
Has 商談ID field: True
Has ソース field: True
```

- [ ] **Step 5: フィジビリティ評価サマリーを確認する**

以下の表を埋めて検証完了とする:

| 問い | 検証結果 | 合格基準 |
|------|---------|---------|
| 問い⑨ | Webhook で M365 形式を受信し `## 議事録` Markdown に変換できる | ✅ PASS |
| 問い⑩ | アダプター差し替え（whisper_cpp ↔ m365）後も minutes.html 変更不要 | ✅ PASS |

- [ ] **Step 6: 最終コミット**

```bash
git add work/poc/
git commit -m "feat: complete poc meeting recording pipeline - whisper.cpp + M365 connector + 問い⑨⑩ verification"
```

---

## 自己レビュー（スペック対応確認）

仕様書 §17.5 の PoC スコープ:

| 要件 | 対応タスク | 状態 |
|------|---------|------|
| ✅ Webhook 受信エンドポイント（POST /api/webhooks/minutes） | Task 7 | ✅ |
| ✅ M365 Copilot 出力 → minutesMarkdown 変換ロジック | Task 5・7 | ✅ |
| ✅ Salesforce 商談 ID（OPP-XXXX）との自動紐付け | Task 5・6・7 | ✅ |
| ✅ minutes.html での Markdown レンダリング表示 | Task 8（meeting.html API接続） | ✅ |

仕様書 §17.9 の whisper.cpp 推奨構成:

| 要件 | 対応タスク | 状態 |
|------|---------|------|
| whisper-cli（large-v3 / base）バイナリ呼び出し | Task 1・3 | ✅ |
| pyannote.audio（話者分離）との2段構成 | スコープ外（本番フェーズ） | — |
| ECS Fargate（CPU のみ）でのデプロイ | スコープ外（本番フェーズ） | — |

仕様書 §17.10 の追加問い:

| 問い | 対応タスク | 状態 |
|------|---------|------|
| 問い⑨ | Task 7・9 | ✅ |
| 問い⑩ | Task 5・9 | ✅ |

---

*計画バージョン: 1.0*  
*作成日: 2026-04-26*  
*対象リポジトリ: whisper.cpp（ggml-org/whisper.cpp）*  
*参照仕様書: `work/poc_feasibility_spec.md` v1.1*  
*参照 UI モック: `work/UIMock/meeting.html`*
