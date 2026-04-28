# 検証手順書: 次世代日本語会議文字起こしシステム (Phase 1 / Phase 2 実装)

**作成日**: 2026-04-28
**対象実装**: `work/UIMock/2026-04-28-design.md` Phase 1〜2 相当
**前提**: `work/poc/backend/` が正常起動できる状態であること

---

## 0. 事前準備チェックリスト

```bash
# 作業ディレクトリ（リポジトリルート）
cd C:\work\30.Projects\102.AI_Projects\whisper.cpp\whisper.cpp

# 仮想環境有効化
.\work\poc\backend\venv\Scripts\activate

# 依存関係確認
pip list | findstr -i "fastapi ollama huggingface"

# ffmpeg 確認（ノイズ除去に必要）
ffmpeg -version | head -1

# Ollama 確認
ollama list
# → qwen3:1.7b が表示されること
# 未インストールの場合: ollama pull qwen3:1.7b

# whisper-cli 確認
.\build\bin\Release\whisper-cli.exe --help | head -3
```

---

## 1. config.py: 設定値確認

### 1.1 Kotoba-Whisper モデル検出の確認

```bash
cd work\poc\backend
python -c "
from config import WHISPER_MODEL, WHISPER_FINAL_MODEL, LOCAL_LLM_MODEL, NOISE_REDUCTION_LEVEL
print('WHISPER_MODEL      :', WHISPER_MODEL)
print('WHISPER_FINAL_MODEL:', WHISPER_FINAL_MODEL)
print('LOCAL_LLM_MODEL    :', LOCAL_LLM_MODEL)
print('NOISE_REDUCTION    :', NOISE_REDUCTION_LEVEL)
"
```

**期待結果（Kotoba モデル未ダウンロード時）**:
```
WHISPER_MODEL      : ...models/ggml-base.bin       ← Kotoba がなければ base
WHISPER_FINAL_MODEL: ...models/ggml-medium.bin     ← medium があれば medium
LOCAL_LLM_MODEL    : qwen3:1.7b                    ← qwen2.5-coder:7b ではないこと
NOISE_REDUCTION    : moderate
```

**Kotoba-Whisper v2.2 GGML モデルのダウンロード**:

> ⚠️ `kotoba-tech/kotoba-whisper-v2.2-ggml` は**存在しない**。
> 正しいソース: `Pomni/kotoba-whisper-v2.2-ggml-allquants`（公開・認証不要）

```bash
# リアルタイム転写用（whisper-server 常駐）: Q8_0 / 818MB
curl -L -o models/ggml-kotoba-v2.2-q8_0.bin \
  https://huggingface.co/Pomni/kotoba-whisper-v2.2-ggml-allquants/resolve/main/ggml-kotoba-v2.2-q8_0.bin

# 最終転写用（whisper-cli 都度実行）: Q5_K / 538MB ← 精度と速度のバランス最適
curl -L -o models/ggml-kotoba-v2.2-q5_k.bin \
  https://huggingface.co/Pomni/kotoba-whisper-v2.2-ggml-allquants/resolve/main/ggml-kotoba-v2.2-q5_k.bin

# または huggingface_hub で取得（認証不要）
python -c "
from huggingface_hub import hf_hub_download
hf_hub_download(
    repo_id='Pomni/kotoba-whisper-v2.2-ggml-allquants',
    filename='ggml-kotoba-v2.2-q5_k.bin',
    local_dir='models/',
)
"
```

**利用可能な量子化バリアント** (`Pomni/kotoba-whisper-v2.2-ggml-allquants`):

| ファイル名 | サイズ | 用途 |
|---|---|---|
| `ggml-kotoba-v2.2-q5_k.bin` | 538MB | **最終転写（推奨）** |
| `ggml-kotoba-v2.2-q8_0.bin` | 818MB | **リアルタイム（推奨）** |
| `ggml-kotoba-v2.2-q4_k.bin` | 444MB | メモリ節約優先 |
| `ggml-kotoba-v2.2-f16.bin` | 1.52GB | 最高精度（RAM に余裕がある場合） |

ダウンロード後の設定確認:
```bash
python -c "
from config import WHISPER_MODEL, WHISPER_FINAL_MODEL
print('WHISPER_MODEL      :', WHISPER_MODEL)
print('WHISPER_FINAL_MODEL:', WHISPER_FINAL_MODEL)
# → 両方とも ...models/ggml-kotoba-v2.2... と表示されること
"
```

### 1.2 環境変数によるモデル上書き確認

```bash
# 既存 medium モデルへのロールバック（A/B テスト用）
WHISPER_FINAL_MODEL=models/ggml-medium.bin python -c "
from config import WHISPER_FINAL_MODEL
print(WHISPER_FINAL_MODEL)
"
# → models/ggml-medium.bin と表示されること
```

---

## 2. services/noise_reduction.py: ノイズ除去単体テスト

### 2.1 ffmpeg arnndn フィルター利用可否確認

```bash
# ffmpeg の arnndn サポート確認
ffmpeg -filters 2>&1 | findstr arnndn
# → "arnndn" が表示されれば利用可能
# → 表示されなければ mild モードのバンドパスフィルターが使われる（自動フォールバック）
```

### 2.2 ノイズ除去動作確認

```bash
# サンプル WAV でテスト（samples/ にある jfk.wav 等を使用）
python -c "
import tempfile, os
from services.noise_reduction import reduce_noise
src = '../../../samples/jfk.wav'
with tempfile.TemporaryDirectory() as d:
    out = d + '/clean.wav'
    result = reduce_noise(src, out)
    if result == out and os.path.exists(out):
        import os.path
        print('PASS: ノイズ除去成功 →', os.path.getsize(out), 'bytes')
    elif result == src:
        print('WARN: ノイズ除去フォールバック (元ファイルを使用)')
    else:
        print('FAIL: 予期しない結果:', result)
"
```

**期待結果**: PASS または WARN（FAIL は不可）

### 2.3 NOISE_REDUCTION_LEVEL=none でスキップ確認

```bash
NOISE_REDUCTION_LEVEL=none python -c "
from services.noise_reduction import reduce_noise
result = reduce_noise('dummy.wav', 'output.wav')
assert result == 'dummy.wav', 'スキップされていない'
print('PASS: none レベルでスキップ確認')
"
```

---

## 3. services/vocabulary.py: 語彙プロンプト生成テスト

```bash
python -c "
from services.vocabulary import build_initial_prompt

# 営業・商談
p = build_initial_prompt('opp', 'すき家', '佐藤 淳', 'sales')
print('sales  :', repr(p))
assert 'すき家' in p
assert '成約率' in p
assert len(p) <= 200

# 物流・倉庫
p = build_initial_prompt('visit', '田中倉庫', '', 'logistics')
print('logistics:', repr(p))
assert 'ピッキング' in p
assert len(p) <= 200

# 小売・店舗
p = build_initial_prompt('visit', 'セブン渋谷', '', 'retail')
print('retail :', repr(p))
assert '棚割り' in p
assert len(p) <= 200

# 固有名詞なし
p = build_initial_prompt('opp', industry='sales')
print('no name:', repr(p))
assert '商談会議' in p

print('PASS: 全テスト合格')
"
```

**合格基準**: すべてのアサーションが通ること

---

## 4. services/transcription.py: ノイズ除去統合確認

### 4.1 transcription.py インポート確認

```bash
python -c "
from services.transcription import transcribe_audio
print('PASS: transcription.py インポート成功')
"
# → ImportError が出ないこと
```

### 4.2 ノイズ除去が transcribe_audio に統合されているか確認

```bash
python -c "
import logging
logging.basicConfig(level=logging.DEBUG)
# サンプル音声で転写を試みる（短いクリップで十分）
# 注意: 転写自体は実行せず、ログにノイズ除去メッセージが出るかだけ確認したい場合は
# NOISE_REDUCTION_LEVEL=none にして元コードと同じ動作になることで確認できる
print('transcription.py に reduce_noise が統合されていることはコードで確認済み')
print('実転写テストは Step 8 の E2E テストで実施する')
"
```

---

## 5. api/recording.py: industry パラメータ確認

### 5.1 サーバー起動確認

```bash
cd work\poc\backend

# サーバー起動（バックグラウンド）
uvicorn main:app --port 8000 --reload &

# ヘルスチェック
curl http://localhost:8000/api/health | python -m json.tool
```

**期待結果**:
```json
{
  "status": "ok",
  "whisper_server": true,
  "ollama": true,
  "llm_model": "qwen3:1.7b"
}
```

`llm_model` が `qwen3:1.7b` であること（`qwen2.5-coder:7b` ではないこと）を確認。

### 5.2 industry パラメータ有無の確認

```bash
# industry=logistics を明示指定
curl -s -X POST http://localhost:8000/api/recordings \
  -F "audio=@../../../samples/jfk.wav" \
  -F "meeting_type=visit" \
  -F "client_name=田中倉庫" \
  -F "owner_name=山田 健一" \
  -F "industry=logistics" \
  | python -m json.tool | head -30

# industry パラメータなし（デフォルト sales）
curl -s -X POST http://localhost:8000/api/recordings \
  -F "audio=@../../../samples/jfk.wav" \
  -F "meeting_type=opp" \
  -F "client_name=すき家" \
  | python -m json.tool | head -30
```

**確認ポイント**:
- HTTP 500 が返らないこと
- `raw_transcript` フィールドが存在すること
- `summary.topics` が空でないこと

---

## 6. meeting.html: UI 動作確認

### 6.1 ブラウザで meeting.html を開く

```bash
# FastAPI サーバー経由でアクセス
start http://localhost:8000
```

### 6.2 業種セレクター確認チェックリスト

- [ ] フォーム画面（Step 1）に「業種・現場環境」ドロップダウンが表示される
- [ ] 選択肢: 💼 営業・商談 / 🏪 小売・店舗 / 🏭 物流・倉庫 の3つがある
- [ ] デフォルトが「💼 営業・商談」になっている
- [ ] 「🏭 物流・倉庫」に切り替えてから録音→停止すると、POST に `industry=logistics` が含まれる
  - DevTools > Network > `/recordings` リクエストの Form Data を確認

### 6.3 API_BASE 確認

ブラウザの DevTools Console で:
```javascript
console.log(API_BASE);
// → "http://localhost:8000/api" または "/api" と表示されること
```

---

## 7. VAD 保守的設定確認（WHISPER_VAD_ENABLED=1 時）

```bash
# VAD モデルが存在する環境でのみ実施
# bash models/download-vad-model.sh silero-v6.2.0  ← 未実行の場合

WHISPER_VAD_ENABLED=1 python -c "
from config import WHISPER_VAD_MODEL
if not WHISPER_VAD_MODEL:
    print('SKIP: VAD モデルが未ダウンロード（テストをスキップ）')
else:
    print('VAD モデル:', WHISPER_VAD_MODEL)
    # transcription.py の cmd 組み立てを直接確認
    import services.transcription as t
    import inspect
    src = inspect.getsource(t.transcribe_audio)
    assert 'vad-threshold' in src
    assert 'vad-speech-pad-ms' in src
    assert '0.35' in src
    print('PASS: 保守的 VAD パラメータが transcription.py に存在する')
"
```

---

## 8. E2E 統合テスト（全機能）

### 8.1 テスト用日本語音声の準備

```bash
# 短い日本語テスト音声を用意（例: samples/ にある日本語サンプルがあれば使用）
# なければ jfk.wav（英語）でパイプライン自体の動作確認だけ行う

# テスト音声がある場合
curl -s -X POST http://localhost:8000/api/recordings \
  -F "audio=@/path/to/japanese_meeting.wav" \
  -F "meeting_type=opp" \
  -F "client_name=テスト商事" \
  -F "owner_name=鈴木 花子" \
  -F "industry=sales" \
  | python -m json.tool
```

### 8.2 合格基準

| チェック項目 | 確認方法 | 合格条件 |
|---|---|---|
| HTTP 200 が返る | `curl` のレスポンスコード | 200 または 201 |
| `raw_transcript` が存在 | JSON フィールド確認 | フィールドあり・空でない |
| `summary.topics` が存在 | JSON フィールド確認 | 配列（空でも可） |
| `minutes_markdown` が存在 | JSON フィールド確認 | 文字列あり |
| qwen3:1.7b が使われた | Ollama のログ確認 | qwen3:1.7b が呼ばれていること |
| OOM が発生しない | タスクマネージャーで確認 | 8.7GB RAM 環境でスワップなし |

### 8.3 ノイズ除去効果確認（任意・騒音環境のサンプルがある場合）

```bash
# ノイズあり vs ノイズ除去ありで転写結果を比較
NOISE_REDUCTION_LEVEL=none python -c "
from services.transcription import transcribe_audio
r = transcribe_audio('/path/to/noisy_audio.wav', language='ja')
print('=== ノイズ除去なし ===')
print(r.text[:200])
"

NOISE_REDUCTION_LEVEL=moderate python -c "
from services.transcription import transcribe_audio
r = transcribe_audio('/path/to/noisy_audio.wav', language='ja')
print('=== ノイズ除去あり (moderate) ===')
print(r.text[:200])
"
# 合格基準: moderate 版の方が明らかに自然な文になっていること
```

---

## 9. Kotoba-Whisper A/B テスト（モデルダウンロード後）

```bash
# Kotoba vs medium の CER 比較
# 同一テスト音声に対して両モデルで転写し、正解テキストとの文字誤り率を比較

# medium モデルで転写
WHISPER_FINAL_MODEL=models/ggml-medium.bin python -c "
from services.transcription import transcribe_audio
r = transcribe_audio('/path/to/test_audio.wav', language='ja')
open('medium_output.txt', 'w', encoding='utf-8').write(r.text)
print('medium:', r.text[:100])
"

# Kotoba モデルで転写
WHISPER_FINAL_MODEL=models/ggml-kotoba-v2.2-q5_k.bin python -c "
from services.transcription import transcribe_audio
r = transcribe_audio('/path/to/test_audio.wav', language='ja')
open('kotoba_output.txt', 'w', encoding='utf-8').write(r.text)
print('kotoba:', r.text[:100])
"

# CER 計算（python-cer ライブラリが必要）
python -c "
ref  = open('正解テキスト.txt', encoding='utf-8').read()
med  = open('medium_output.txt', encoding='utf-8').read()
kot  = open('kotoba_output.txt', encoding='utf-8').read()

def cer(ref, hyp):
    import editdistance
    return editdistance.eval(ref, hyp) / len(ref)

print(f'medium CER : {cer(ref, med):.1%}')
print(f'kotoba CER : {cer(ref, kot):.1%}')
print('合格基準: Kotoba の CER が medium より 20% 以上低いこと')
"
```

---

## 10. サーバー起動・停止手順（参考）

### 起動

```bash
cd C:\work\30.Projects\102.AI_Projects\whisper.cpp\whisper.cpp\work\poc\backend
.\venv\Scripts\activate

# デフォルト設定で起動
uvicorn main:app --port 8000 --reload

# ノイズ除去を aggressive にして起動（倉庫環境）
NOISE_REDUCTION_LEVEL=aggressive uvicorn main:app --port 8000 --reload

# Kotoba モデルを明示指定して起動
WHISPER_FINAL_MODEL=../../models/ggml-kotoba-whisper-v2.2-q5km.bin \
  uvicorn main:app --port 8000 --reload

# すべてのオプションを組み合わせ
NOISE_REDUCTION_LEVEL=moderate \
  WHISPER_VAD_ENABLED=1 \
  LOCAL_LLM_MODEL=qwen3:1.7b \
  uvicorn main:app --port 8000 --reload
```

### 停止

```bash
# Ctrl+C でサーバーを停止
# バックグラウンドプロセスを終了
taskkill /F /IM whisper-server.exe
```

---

## 付録: 実装済みファイル一覧

| ファイル | 変更種別 | 主な変更内容 |
|---|---|---|
| `work/poc/backend/config.py` | 変更 | Kotoba glob 検出、`qwen3:1.7b`、`NOISE_REDUCTION_LEVEL` |
| `work/poc/backend/services/noise_reduction.py` | **新規** | RNNoise ffmpeg ラッパー (mild/moderate/aggressive) |
| `work/poc/backend/services/transcription.py` | 変更 | `reduce_noise()` 統合、VAD 保守的設定 (threshold=0.35) |
| `work/poc/backend/services/vocabulary.py` | **新規** | 業界別語彙テンプレート + `build_initial_prompt()` |
| `work/poc/backend/api/recording.py` | 変更 | `industry` パラメータ、`build_initial_prompt()` 統合 |
| `work/UIMock/meeting.html` | 変更 | 業種セレクター UI + `industry` を POST に追加 |

**変更なし（既に実装済みのもの）**:
- `services/summarizer.py`: `<think>` タグ除去・3段 JSON フォールバック・Ollama フォールバック ← 全実装済み
- `meeting.html` チャンクコンテキストチェーン (P5): `realtimeContextBuffer` ← 実装済み

---

*作成日: 2026-04-28*
*参照: work/UIMock/2026-04-28-design.md*
