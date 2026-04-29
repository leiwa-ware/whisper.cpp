# PoC バックエンド 起動手順

## 起動が必要なプロセス一覧

| プロセス | 必要性 | 起動方法 |
|---|---|---|
| **Ollama** | 必須（LLM補正・要約） | 別途手動起動 |
| **uvicorn** | 必須（FastAPI バックエンド） | 手動起動 |
| **whisper-server.exe** | 自動（リアルタイム転写） | uvicorn 起動時に自動管理 |
| **whisper-cli.exe** | 自動（録音ファイル転写） | API 呼び出し時に subprocess 実行 |

> whisper-server.exe と whisper-cli.exe はバイナリが存在するだけでよい。
> 手動での起動・停止は不要。

---

## 前提条件（初回のみ）

### 1. ビルド済みバイナリの確認

```
build\bin\Release\whisper-cli.exe
build\bin\Release\whisper-server.exe
```

ない場合はプロジェクトルートでビルドする：

```powershell
cmake -B build
cmake --build build -j --config Release
```

### 2. 音声モデルのダウンロード

```bash
# リアルタイム転写用（軽量・低遅延）
bash models/download-ggml-model.sh base

# 最終転写用（精度優先）
bash models/download-ggml-model.sh medium

# VAD モデル（任意・無音幻覚抑制）
bash models/download-vad-model.sh silero-v6.2.0
```

### 3. Ollama モデルのダウンロード

```powershell
ollama pull qwen3:1.7b
```

### 4. Python 仮想環境のセットアップ

```powershell
cd work\poc\backend
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

---

## 通常の起動手順

### ステップ 1：Ollama を起動

```powershell
ollama serve
```

> 既に Windows サービスとして起動済みの場合は不要。
> ブラウザで http://localhost:11434 にアクセスして確認できる。

### ステップ 2：FastAPI バックエンドを起動

別のターミナルを開いて：

```powershell
cd work\poc\backend
venv\Scripts\activate
uvicorn main:app --host 127.0.0.1 --port 8080 --reload
```

起動ログに以下が表示されれば正常：

```
INFO:     whisper-server ready on port 8178     ← 自動起動成功
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8000
```

whisper-server.exe が見つからない場合は代わりに：

```
WARNING:  whisper-server not found at ... — realtime disabled
```

この場合、リアルタイム文字起こしは無効になるが、録音ファイルのアップロード転写は引き続き動作する。

### ステップ 3：動作確認

```powershell
# ヘルスチェック（whisper-server と Ollama の状態を確認）
curl http://localhost:8080/api/health
```

期待するレスポンス：

```json
{
  "status": "ok",
  "whisper_server": true,
  "whisper_server_port": 8178,
  "whisper_final_model": "...\\models\\ggml-medium.bin",
  "ollama": true,
  "llm_model": "qwen3:1.7b"
}
```

### ステップ 4：UI にアクセス

ブラウザで http://localhost:8080 を開く（UIMock の静的ファイルが提供される）。

---

## 停止手順

`uvicorn` のターミナルで `Ctrl+C` を押す。
whisper-server.exe は uvicorn 終了時に自動で terminate される。
Ollama は必要に応じて停止する（次回も使う場合はそのままでよい）。

---

## 環境変数による設定変更

| 変数名 | デフォルト | 説明 |
|---|---|---|
| `LOCAL_LLM_MODEL` | `qwen3:1.7b` | Ollama で使用する LLM モデル |
| `WHISPER_FINAL_MODEL` | `models/ggml-medium.bin` | 録音転写に使うモデル（精度優先） |
| `WHISPER_MODEL` | `models/ggml-base.bin` | リアルタイム転写モデル（速度優先） |
| `WHISPER_SERVER_PORT` | `8178` | whisper-server のポート番号 |
| `OLLAMA_HOST` | `http://localhost:11434` | Ollama のエンドポイント |
| `WHISPER_VAD_ENABLED` | `1`（有効） | `0` にすると VAD 無効化。silero モデル未存在なら自動的に無効。 |
| `WHISPER_THREADS` | `os.cpu_count()`（論理コア数） | whisper-cli/server の `-t`。HT 競合を避けたい場合は物理コア数を指定 |
| `WHISPER_REALTIME_BEAM_SIZE` | `1` | リアルタイム転写の beam（1＝greedy・最速） |
| `WHISPER_FINAL_BEAM_SIZE` | `5` | 最終転写の beam（whisper 既定値・精度優先） |

設定例：

```powershell
$env:LOCAL_LLM_MODEL = "qwen3:4b"
$env:WHISPER_VAD_ENABLED = "1"
uvicorn main:app --host 127.0.0.1 --port 8080 --reload
```

---

## トラブルシューティング

| 症状 | 原因 | 対処 |
|---|---|---|
| `whisper_server: false` | whisper-server.exe が未ビルド | cmake でビルドする |
| `ollama: false` | Ollama が起動していない | `ollama serve` を実行 |
| `500 Internal Server Error` | LLM モデル未ダウンロード | `ollama pull qwen3:1.7b` |
| 転写結果が空 | medium モデル未存在 | base モデルにフォールバック済み、または `WHISPER_FINAL_MODEL` を設定 |
| リアルタイム文字起こしが動かない | whisper-server 未起動 | ヘルスチェックで `whisper_server` を確認 |
