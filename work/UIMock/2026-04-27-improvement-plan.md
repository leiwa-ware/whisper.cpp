# 日本語会議文字起こしシステム 改善計画書

**作成日**: 2026-04-27  
**対象コード**: `work/poc/backend/`  
**参照ドキュメント**: `work/UIMock/adv.md`、`work/poc_feasibility_spec.md`  
**ステータス**: 即時実行可能（追加インフラ不要）

---

## 1. 現状分析

### 1.1 動作している部分

| コンポーネント | 状態 | 根拠 |
|---|---|---|
| FastAPI + 4 ルーター | ✅ 動作中 | `main.py` の lifespan 管理・CORS 設定済み |
| whisper-cli（medium モデル）| ✅ 動作中 | `--no-speech-thold 0.6 --entropy-thold 2.4` による幻覚抑制済み |
| whisper-server（ポート 8178）| ✅ 動作中 | 起動チェック・コンカレンシーロック済み |
| Ollama + qwen2.5-coder:7b（1 コール）| ✅ 動作中 | 補正 + 要約を統合して OOM 回避済み |
| SQLite / SQLAlchemy async | ✅ 動作中 | aiosqlite による非同期 I/O |
| MediaRecorder + WebM チャンク送信 | ✅ 動作中 | `api/realtime.py` にロック済み |
| `MinutesSource` インターフェース | ✅ 動作中 | `WhisperCppAdapter` / `M365CopilotAdapter` が同一 I/F |

### 1.2 現在の問題点

**問題 A — OOM リスクが常在（最重要）**

`config.py:37` のデフォルトモデルは `qwen2.5-coder:7b`。Q4 換算で 4.5〜5.5GB の RAM を要求する。whisper-server（約 0.5GB）＋ whisper-cli medium（約 1.5GB）が同時起動する 8.7GB 環境では、Ollama 推論ピーク時に合計 7〜8GB を超えてスワップが発生する。

```python
# config.py:37（現状）
LOCAL_LLM_MODEL = os.environ.get("LOCAL_LLM_MODEL", "qwen2.5-coder:7b")
```

**問題 B — JSON パース失敗でデータ全損**

`summarizer.py:81-83` の `json.loads()` は例外未捕捉。LLM が不完全な JSON を返した場合に `HTTPException(500)` が上がり、録音データが失われる。

**問題 C — リアルタイムチャンク間のコンテキスト断絶**

各チャンクが独立して転写されるため、チャンク境界で固有名詞の再認識失敗が発生する。`api/realtime.py` は `initial_prompt` パラメーターを受け付けるが、フロントエンドが前チャンクのテキストを渡していない。

**問題 D — initial_prompt に業務語彙なし**

`api/recording.py:28-29` が渡すのは得意先名と担当者名のみ。「成約率」「フォローアップ」等の業務語彙がないため、whisper がカタカナ誤変換しやすい。

**問題 E — VAD 未使用による無音区間の幻覚**

`--vad` フラグが未使用。`--no-speech-thold 0.6` で一部抑制しているが、VAD（Silero-VAD v6.2）を使えばより確実に除去できる。whisper.cpp のビルド済みバイナリと `models/download-vad-model.sh` が既に利用可能。

**問題 F — Ollama 未起動時のフォールバックなし**

`summarizer.py` の `client.chat()` 呼び出しが失敗すると全機能が停止する。

---

## 2. 改善優先順位

| 優先度 | 改善項目 | 影響 | 工数目安 |
|---|---|---|---|
| **P1** | LLM モデルを `gemma3:2b` に切り替え | RAM 5.5GB → 1.8GB（約 3GB 削減） | 30 分 |
| **P2** | JSON パース失敗リカバリー追加 | データ全損バグ修正 | 1 時間 |
| **P3** | `initial_prompt` に業務語彙を追加 | カタカナ誤変換の抑制 | 2 時間 |
| **P4** | VAD 統合（`--vad` フラグ） | 無音区間の幻覚フレーズを根本除去 | 1 時間 |
| **P5** | チャンク間コンテキストチェーン | リアルタイム転写の精度向上 | 3 時間 |
| **P6** | Ollama 未起動フォールバック | ロバスト性向上 | 2 時間 |
| **P7** | 話者分離（pyannote-audio）統合 | 「誰が何を言ったか」の明示 | 1〜2 日 |

優先順位の根拠: P1 は即時 OOM クラッシュリスク。P2 はデータ喪失防止。P3・P4 は設定変更のみで精度改善。P5 はフロントエンド中心の中規模実装。P7 は HuggingFace トークン等の追加インフラが必要なため最後。

---

## 3. 実装詳細

### P1: LLM モデル切り替え（gemma3:2b）

**ファイル**: `work/poc/backend/config.py:37`

```python
# 変更前
LOCAL_LLM_MODEL = os.environ.get("LOCAL_LLM_MODEL", "qwen2.5-coder:7b")

# 変更後
# gemma3:2b (Q4_K_M, ~1.7GB RAM)。日本語補正・要約ともに実用品質。
# 環境変数 LOCAL_LLM_MODEL で上書き可能（A/Bテスト用）
LOCAL_LLM_MODEL = os.environ.get("LOCAL_LLM_MODEL", "gemma3:2b")
```

**事前準備**:
```bash
ollama pull gemma3:2b
# または量子化レベルを明示する場合
ollama pull gemma3:2b:q4_K_M
```

**RAM 使用量比較（Q4 換算）**:
| モデル | RAM目安 | 日本語補正 | 備考 |
|---|---|---|---|
| qwen2.5-coder:7b | 4.5〜5.5GB | 高（コード向け訓練のため業務語彙に強い） | OOM リスクあり |
| gemma3:2b | 1.5〜1.8GB | 中〜高（Gemma 3 は多言語対応強化済み） | 推奨 |
| gemma2:2b | 1.4〜1.7GB | 中（英語能力が若干高い互換モデル） | 代替案 |

**A/B テスト方法**:
```bash
# 旧モデルで起動（ポート 8000）
LOCAL_LLM_MODEL=qwen2.5-coder:7b uvicorn main:app --port 8000

# 新モデルで起動（ポート 8001）
LOCAL_LLM_MODEL=gemma3:2b uvicorn main:app --port 8001
```
同一録音ファイルを両ポートに投げ、`summary.topics` と `raw_transcript`（補正後）の品質を手動比較する。

**リスク**: gemma3:2b はコーディング特化ではないため、業務固有の誤変換パターン補正精度が低い可能性がある。`_COMBINED_PROMPT` の誤認識パターンリストを充実させることで補完する（P3 参照）。

---

### P2: JSON パース失敗リカバリー

**ファイル**: `work/poc/backend/services/summarizer.py`

LLM が不完全な JSON を返しても**文字起こし結果は必ず保持**する 3 段フォールバックを実装する。

```python
def _parse_llm_json(raw: str, fallback_transcript: str) -> dict:
    """LLM 出力から JSON を抽出。失敗時は最小辞書を返す。"""
    import json, re, logging
    log = logging.getLogger(__name__)

    # 試行 1: 最初の { から最後の } を取る
    start = raw.find("{")
    end = raw.rfind("}") + 1
    if start >= 0 and end > start:
        try:
            return json.loads(raw[start:end])
        except json.JSONDecodeError as e:
            log.warning("JSON parse failed (attempt 1): %s", e)

    # 試行 2: コードブロック（```json ... ```）内を探す
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError as e:
            log.warning("JSON parse failed (attempt 2): %s", e)

    # 試行 3: 全体を JSON としてパース
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # 全失敗: 文字起こしは保持、構造化は空で返す
    log.error("All JSON parse attempts failed. Returning raw transcript as corrected.")
    return {
        "corrected_transcript": fallback_transcript,
        "topics": [],
        "actions": [],
        "risks": [],
    }
```

`correct_and_summarize` 関数内の `json.loads(raw[start:end])` を `_parse_llm_json(raw, raw_transcript)` に置き換える。また、Ollama 接続失敗もキャッチするよう `client.chat()` を `try/except` で囲む（P6 と同一修正）。

---

### P3: initial_prompt に業務語彙を追加

**ファイル**: `work/poc/backend/services/transcription.py`

Whisper の `--prompt` はデコーダーの初期コンテキストとして機能し、語彙バイアスを付与できる。現在は固有名詞のみで業務語彙がない。

**`transcription.py` の先頭 import 直後に追加**:
```python
# 日本語営業会議の標準的なビジネス語彙。
# whisper の --prompt に含めることでカタカナ誤変換を抑制する。
_JA_BUSINESS_VOCAB = (
    "成約率、フォローアップ、アポイントメント、見積もり、提案書、"
    "発注、受注、在庫、母数、進捗管理、商談、得意先、担当者、"
    "定期巡回、フィードバック、クロージング、値引き、競合"
)
```

**`transcribe_audio` 関数内の `--prompt` 組み立てを変更**:
```python
# 変更前
if initial_prompt:
    cmd += ["--prompt", initial_prompt]

# 変更後（固有名詞 + 業務語彙を常時付与）
_prompt_parts = [p for p in [initial_prompt, _JA_BUSINESS_VOCAB] if p]
if _prompt_parts:
    cmd += ["--prompt", "、".join(_prompt_parts)]
```

**`api/recording.py` の context 組み立ても拡充**:
```python
# 変更前
context = ", ".join(filter(None, [client_name, owner_name]))

# 変更後（meeting_type も含める）
_context_parts = list(filter(None, [
    client_name,
    owner_name,
    "商談会議" if meeting_type == "opp" else "現場訪問",
]))
context = "、".join(_context_parts)
```

**注意**: `--prompt` の実効上限は約 224 トークン（日本語換算 100〜150 文字）。`_JA_BUSINESS_VOCAB` は 100 文字以内に抑えること。

---

### P4: VAD 統合（Silero-VAD v6.2）

**前提**: VAD モデルのダウンロードが完了していること。
```bash
bash models/download-vad-model.sh silero-v6.2.0
```

**ファイル**: `work/poc/backend/config.py`（VAD モデルパスを追加）
```python
import glob as _glob

_vad_candidates = sorted(_glob.glob(str(REPO_ROOT / "models/silero-vad*.bin")))
WHISPER_VAD_MODEL = os.environ.get(
    "WHISPER_VAD_MODEL",
    _vad_candidates[-1] if _vad_candidates else "",
)
```

**ファイル**: `work/poc/backend/services/transcription.py`（cmd 組み立てに追加）
```python
from config import WHISPER_CLI, WHISPER_FINAL_MODEL, WHISPER_VAD_MODEL

# VAD モデルが存在する場合のみ有効化（オプション機能として安全に追加）
if WHISPER_VAD_MODEL:
    cmd += ["--vad", "--vad-model", WHISPER_VAD_MODEL]
```

**効果**: 無音区間（移動・休憩・雑談中断）を事前に除去してから whisper に渡すため、「ご視聴ありがとうございました」等の幻覚フレーズの発生源を根本から減らせる。`--no-speech-thold` との二重防御になる。

---

### P5: リアルタイムチャンク間コンテキストチェーン

**バックエンド変更なし**: `api/realtime.py` は既に `initial_prompt: str = ""` を受け付けている。

**ファイル**: `work/UIMock/meeting.html`（JavaScript 部分）

```javascript
// リアルタイム転写の状態管理を追加
const realtimeState = {
  contextBuffer: "",       // 直近の認識テキスト（initial_prompt として使用）
  MAX_CONTEXT_CHARS: 200,  // whisper の --prompt 上限に合わせた最大文字数
};

async function sendChunkForTranscription(audioBlob) {
  const form = new FormData();
  form.append("audio", audioBlob, "chunk.webm");

  // 固有名詞 + 直近コンテキストを initial_prompt として付与
  const context = [
    document.getElementById("inp-client").value,
    document.getElementById("inp-owner").value,
    realtimeState.contextBuffer,
  ].filter(Boolean).join("、");
  form.append("initial_prompt", context.slice(-realtimeState.MAX_CONTEXT_CHARS));

  try {
    const res = await fetch(`${API_BASE}/transcribe-chunk`, {
      method: "POST",
      body: form,
    });
    if (!res.ok) return;
    const data = await res.json();
    if (data.available && data.text) {
      // 認識結果をバッファに追記（末尾 200 文字を保持）
      realtimeState.contextBuffer = (realtimeState.contextBuffer + data.text)
        .slice(-realtimeState.MAX_CONTEXT_CHARS);
      // ライブテキストエリアに追記
      appendLiveText(data.text);
    }
  } catch (e) {
    console.warn("チャンク転写失敗:", e);
  }
}

// 録音停止時にコンテキストをリセット
function resetRealtimeState() {
  realtimeState.contextBuffer = "";
}
```

`mediaRecorder.ondataavailable` ハンドラーを変更:
```javascript
// 変更前
mediaRecorder.ondataavailable = (e) => {
  if (e.data.size > 0) audioChunks.push(e.data);
};

// 変更後
mediaRecorder.ondataavailable = async (e) => {
  if (e.data.size > 0) {
    audioChunks.push(e.data);
    await sendChunkForTranscription(e.data);  // リアルタイム転写も並行実行
  }
};
```

---

### P6: Ollama 未起動フォールバック + ヘルスチェック強化

**ファイル**: `work/poc/backend/services/summarizer.py`

`client.chat()` を `try/except` で囲み、Ollama 接続失敗時は補正なし・空の要約で処理を継続する（P2 の `_parse_llm_json` と合わせて実装）。

```python
try:
    response = client.chat(
        model=LOCAL_LLM_MODEL,
        messages=[{"role": "user", "content": prompt}],
        options={"temperature": 0.1},
    )
    raw = response["message"]["content"].strip()
except Exception as e:
    import logging
    logging.getLogger(__name__).warning("Ollama unavailable: %s", e)
    result = SummaryResult()
    result.minutes_markdown = _to_markdown(raw_transcript, result)
    return raw_transcript, result
```

**ファイル**: `work/poc/backend/main.py`（ヘルスチェックに Ollama 状態を追加）

```python
@app.get("/api/health")
async def health():
    # whisper-server チェック（既存）
    whisper_ok = _check_port(WHISPER_SERVER_PORT)

    # Ollama チェック（追加）
    ollama_ok = False
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(f"{OLLAMA_HOST}/api/tags", timeout=2.0)
            ollama_ok = r.status_code == 200
    except Exception:
        pass

    return {
        "status": "ok",
        "whisper_server": whisper_ok,
        "ollama": ollama_ok,
        "llm_model": LOCAL_LLM_MODEL,
        "whisper_final_model": str(WHISPER_FINAL_MODEL),
    }
```

---

### P7: 話者分離（pyannote-audio）統合ロードマップ（将来対応）

**前提条件**:
- conda 環境 `whisper-diarize` が構築済み（`work/pyannote-audio/install.md` 参照）
- HuggingFace の 3 リポジトリへのアクセス同意済み
- `HF_TOKEN` 環境変数に `hf_` トークンが設定されていること

**新規ファイル**: `work/poc/backend/services/diarization.py`

whisper のセグメントタイムスタンプ（`transcription[].offsets.from/to` ミリ秒）と pyannote の話者区間を重複率でマージし、各セグメントに `"speaker": "SPEAKER_00"` フィールドを追加する。

**`api/recording.py` への統合方針**:
```python
# HF_TOKEN が設定されている場合のみ話者分離を実行
if HF_TOKEN:
    try:
        speakers = diarize(wav_path, hf_token=HF_TOKEN)
        transcription.segments = merge_with_transcript(transcription.segments, speakers)
    except Exception as e:
        log.warning("Diarization failed (non-fatal): %s", e)
```

**制約**: CPU のみで 30 分音声の処理に約 5〜10 分かかる。PoC では「録音停止後の非同期処理」として扱う。

---

## 4. 検証方法

### P1 検証
```bash
# gemma3:2b の日本語補正品質を直接確認
cd work/poc/backend
LOCAL_LLM_MODEL=gemma3:2b python -c "
from services.summarizer import correct_and_summarize
txt = 'フォロー不足でアポが取れませんでした。成約率が下がっています。鼓動不足という認識です。'
corrected, result = correct_and_summarize(txt)
print('補正結果:', corrected)
print('議題:', result.topics)
"
```
合格基準: 「フォロー不足」「アポ」「成約率」が正しく認識される。「鼓動不足」が「フォロー不足」に補正される。応答時間 60 秒以内。

### P2 検証
```bash
cd work/poc/backend
python -c "
from services.summarizer import _parse_llm_json
# 壊れた JSON
result = _parse_llm_json('{\"corrected_transcript\": \"テスト\", \"topics\": [broken}', 'fallback')
assert result['corrected_transcript'] == 'fallback', '失敗: fallback が返っていない'
print('P2 検証: PASS')
"
```

### P3 検証
```bash
# --prompt あり/なしで同じ日本語音声を比較
./build/bin/Release/whisper-cli.exe -m models/ggml-medium.bin \
  -f /tmp/meeting.wav -l ja --output-txt -of /tmp/no_prompt

./build/bin/Release/whisper-cli.exe -m models/ggml-medium.bin \
  -f /tmp/meeting.wav -l ja \
  --prompt "成約率、フォローアップ、アポイントメント" \
  --output-txt -of /tmp/with_prompt

diff /tmp/no_prompt.txt /tmp/with_prompt.txt
```

### P4 検証
```bash
# VAD あり/なしで無音区間を含む音声を比較
./build/bin/Release/whisper-cli.exe -m models/ggml-medium.bin \
  -f /tmp/silent_meeting.wav -l ja --output-txt -of /tmp/no_vad

./build/bin/Release/whisper-cli.exe -m models/ggml-medium.bin \
  -f /tmp/silent_meeting.wav -l ja \
  --vad --output-txt -of /tmp/with_vad

diff /tmp/no_vad.txt /tmp/with_vad.txt
```
合格基準: `with_vad.txt` から「ご視聴ありがとうございました」等の幻覚フレーズが消えていること。

### P5 検証
ブラウザ DevTools の Network タブで `/api/transcribe-chunk` リクエストを確認。2 チャンク目以降に `initial_prompt` フィールドが含まれ、1 チャンク目の認識テキストが入っていれば成功。

### 全体統合テスト
```bash
cd work/poc/backend

# P1 + P2 + P3 + P4 + P6 を有効にして起動
LOCAL_LLM_MODEL=gemma3:2b uvicorn main:app --port 8000 --reload &

# ヘルスチェック（Ollama ステータスも確認）
curl http://localhost:8000/api/health | python -m json.tool

# サンプル録音で E2E テスト
curl -s -X POST http://localhost:8000/api/recordings \
  -F "audio=@/tmp/meeting.webm" \
  -F "meeting_type=opp" \
  -F "client_name=田中商店" \
  -F "owner_name=佐藤 淳" \
  | python -m json.tool | head -60
```

---

## 5. リスクと制約

### 5.1 RAM 使用量（全改善共通）

**P1 移行後の想定 RAM 使用量**:
| プロセス | RAM 目安 |
|---|---|
| OS + 常駐プロセス | 2.0GB |
| whisper-server（base モデル常駐） | 0.5GB |
| whisper-cli medium（転写時のみ） | 1.5GB |
| Ollama + gemma3:2b | 1.7〜2.0GB |
| FastAPI + Python | 0.3GB |
| **合計（転写 + LLM 直列実行時）** | **~6.0GB** |

8.7GB 環境での余裕: 約 2.7GB。`transcribe_audio` → `correct_and_summarize` の**直列実行**（現在の実装）は維持すること。並列化すると RAM がピークを迎え OOM が再発する。

### 5.2 LLM 補正精度のリスク（P1）

| リスク | 発生条件 | 軽減策 |
|---|---|---|
| 日本語補正精度低下 | gemma3:2b は qwen2.5-coder:7b より業務語彙特化度が低い | `_COMBINED_PROMPT` の誤認識パターンリストを追記する |
| JSON 出力形式の変化 | モデルが異なる JSON 構造を出力する | P2 の `_parse_llm_json` フォールバックで対応済み |

### 5.3 MinutesSource インターフェースへの影響

今回の全改善は `MinutesSource.to_markdown()` の入力となる `raw_transcript` の**品質が向上するだけ**で、インターフェース契約は変わらない。問い⑨・問い⑩の検証結果は維持される。

### 5.4 API レスポンス互換性

- 既存フィールドは削除しない（後方互換性を保つ）
- P6 で `/api/health` に `ollama` / `llm_model` フィールドが追加されるが、フロントエンドは新フィールドを無視するため問題なし
- P7（話者分離）後は `segments[].speaker` フィールドが追加されるが、既存の `raw_transcript` / `summary` 構造は変わらない

### 5.5 Windows 固有の注意事項

VAD モデルのパスに日本語や空白が含まれないよう確認すること。`--vad-model` 引数はダブルクォートで囲む。

---

## 6. 実装チェックリスト

上から順に実行することで、最低リスクで最大効果が得られる。

- [ ] **P1**: `ollama pull gemma3:2b` を実行する
- [ ] **P1**: `config.py:37` を `"gemma3:2b"` に変更する
- [ ] **P1 検証**: `correct_and_summarize()` でサンプルテキストの品質確認
- [ ] **P2**: `services/summarizer.py` に `_parse_llm_json()` を追加し、呼び出し元を変更する
- [ ] **P2 検証**: 壊れた JSON でフォールバックが返ることを確認
- [ ] **P3**: `services/transcription.py` に `_JA_BUSINESS_VOCAB` を追加し、`cmd` 組み立てを修正する
- [ ] **P3**: `api/recording.py` の `context` 組み立てを修正する
- [ ] **P4**: `bash models/download-vad-model.sh silero-v6.2.0` を実行する
- [ ] **P4**: `config.py` に `WHISPER_VAD_MODEL` を追加し、`transcription.py` に `--vad` フラグを追加する
- [ ] **P5**: `meeting.html` に `realtimeState` と `sendChunkForTranscription` を実装する
- [ ] **P6**: `summarizer.py` の `client.chat()` を `try/except` で囲む
- [ ] **P6**: `main.py` の `/api/health` に Ollama 状態を追加する
- [ ] **全体統合テスト**: E2E で録音 → 転写 → 補正 → 要約の一連を確認する
- [ ] **P7（将来）**: `services/diarization.py` を作成し、`HF_TOKEN` 環境変数で有効化する

---

## 関連ファイル

| ファイル | 変更内容 |
|---|---|
| `work/poc/backend/config.py` | P1 モデル変更、P4 VAD パス追加 |
| `work/poc/backend/services/transcription.py` | P3 業務語彙、P4 VAD フラグ |
| `work/poc/backend/services/summarizer.py` | P2 JSON リカバリー、P6 フォールバック |
| `work/poc/backend/api/recording.py` | P3 context 拡充 |
| `work/poc/backend/main.py` | P6 ヘルスチェック強化 |
| `work/UIMock/meeting.html` | P5 コンテキストチェーン |
| `work/poc/backend/services/diarization.py` | P7 新規作成（将来） |

---

*作成日: 2026-04-27*  
*参照: `work/UIMock/adv.md`、`work/poc_feasibility_spec.md`、`work/plan/2026-04-26-poc-meeting-recording.md`*  
*対象リポジトリ: whisper.cpp（ggml-org/whisper.cpp）*
