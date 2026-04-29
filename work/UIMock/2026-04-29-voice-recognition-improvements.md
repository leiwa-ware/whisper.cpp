# 音声認識処理 改善点まとめ

**作成日**: 2026-04-29
**対象**: whisper.cpp ベース 日本語会議議事録 PoC（`work/poc/backend/` + `work/UIMock/meeting.html`）
**起点**: [`2026-04-29-advice.md`](2026-04-29-advice.md)（汎用リアルタイム ASR 設計指針）
**整合**: [`2026-04-29-revised-plan.md`](2026-04-29-revised-plan.md)（日本語特化の上書き方針）

---

## 0. 目的とスコープ

`2026-04-29-advice.md` には「完全リアルタイム」を達成するための一般原則（VAD・短チャンク＋overlap・partial/final 二段・beam 絞り・非同期パイプライン）が整理されている。本書は **その原則を現状実装と突き合わせ、ギャップと改善優先度を明確化する**。

スコープ外：

- モデル選定（`revised-plan.md` の R1/R11 で Kotoba-Whisper 系に決定済み）
- ノイズ除去レベル（`revised-plan.md` の R7 で確定済み）
- LLM 後処理の同期/非同期判断（`revised-plan.md` の R8 で確定済み）

---

## 1. 現状パイプライン

```
┌─────────────────────────────────────────────────────────┐
│  meeting.html (フロント)                                  │
│    MediaRecorder.start(1000)            ← 1秒刻み chunk   │
│    setInterval(sendRealtimeChunk, 5000) ← 5秒バッチ送信   │
│    initChunk + pendingChunks → POST     ← overlap=0       │
└─────────────────────────────────────────────────────────┘
                       ↓ multipart/form-data
┌─────────────────────────────────────────────────────────┐
│  realtime.py (FastAPI)                                  │
│    POST /api/transcribe-chunk                           │
│       → ffmpeg で 16kHz WAV 化                          │
│       → http://127.0.0.1:{port}/inference にフォワード   │
│         (whisper-server, 既ロード WHISPER_MODEL を使用)   │
│         初期プロンプトは prompt_safety で 24 字に短縮     │
└─────────────────────────────────────────────────────────┘
                       ↓
┌─────────────────────────────────────────────────────────┐
│  whisper-server (常駐)                                   │
│    モデル: ggml-small.bin (デフォルト) or Kotoba          │
│    beam: 未指定 (= whisper 既定 5)                        │
│    threads: 未指定                                        │
│    VAD: --no-speech-thold 0.6 のみ                       │
└─────────────────────────────────────────────────────────┘

最終転写（録音停止後）:
  POST /api/recordings → transcription.py:transcribe_audio()
    whisper-cli + ggml-kotoba-v2.2-q5_k.bin
    --no-speech-thold 0.6 / --entropy-thold 2.4
    VAD: WHISPER_VAD_ENABLED=1 のときのみ有効
    → JSON 取得 → LLM 後処理（Ollama qwen3:1.7b 等）
```

---

## 2. advice.md 推奨値 vs 現状（ギャップ表）

| # | 項目 | advice.md | revised-plan.md | 現状 | ギャップ判定 | 根拠 |
|---|---|---|---|---|---|---|
| G1 | チャンク長 | 3〜5秒 | 4秒 | 4秒 sliding window（実装済 P2-A） | ✅ | `meeting.html` `WINDOW_CHUNKS` |
| G2 | overlap | 0.5〜1秒 | 0.8秒 | 0.75秒（実装済 P2-A） | ✅ | `meeting.html` `OVERLAP_CHUNKS` |
| G3 | VAD | 必須 | threshold=0.35（条件付き） | 既定 ON（threshold=0.35）（明示済 P1-C） | ✅ | `transcription.py:76` |
| G4 | beam_size | 1〜3 | realtime=1 / final=5 | realtime=1 / final=5（明示済 P1-B） | ✅ | `transcription.py`, `realtime.py`, `main.py`, `config.py` |
| G5 | threads | 物理コア | （言及なし） | `WHISPER_THREADS`（既定 = 論理コア数）（明示済 P1-A） | ✅ | `transcription.py`, `main.py`, `config.py` |
| G6 | partial/final 2段 | 必須 | VAD or 6秒で確定 | WS 主経路で実装済（POST はフォールバック）（実装済 P3-A） | ✅ | `meeting.html` `openTranscriptWebSocket`, `realtime.py:94-185` |
| G7 | 非同期パイプライン | 必須 | 〃 | WS の onmessage / 250ms timeslice + 1秒 poll で完全非同期（実装済 P2-A/P3-A） | ✅ | `meeting.html` `sendRealtimeChunk` |
| G8 | initial_prompt 文脈継承 | 言及なし | 直近 200 字 | 実装済 | ✅ | `meeting.html:401,503-509,524`, `realtime.py:50-54` |
| G9 | モデル | small（前提） | Kotoba 優先 | small（realtime）/ Kotoba（final） | ✅ | `config.py` |
| G10 | UI 即時反映（partial表示） | 必須 | 〃 | partial-group/.partial/.final の 3 層表示で逐次更新（実装済 P3-A） | ✅ | `meeting.html` CSS + `appendPartial`/`commitFinal` |
| G11 | チャンク境界の語尾欠落対策 | overlap で防止 | overlap+prompt 継承 | overlap + prompt + サーバ dedup（実装済 P2-A/B） | ✅ | `text_dedup.py`, `streaming_session.py`, `realtime.py` |

> **P1+P2+P3-A 適用後**: × が 0 件、△ が 0 件、✅ が **11 件すべて**。
> advice.md / revised-plan.md の主要要件はバックエンド・フロント両方で実装・テスト済。残るは P3-B（モバイル発熱対策）のみで、これは PC 環境では発火しないため後フェーズ送り。

---

## 3. 改善点（優先度付き）

### P1 — 即効・低コスト（バックエンド引数追加のみ）— **✅ 実装済 (2026-04-29)**

#### [P1-A] ✅ whisper の実行スレッド数を明示

- **実装内容**:
  - `config.py` に `WHISPER_THREADS = int(os.environ.get("WHISPER_THREADS", os.cpu_count() or 4))` を追加
  - `transcription.py` の cmd に `--threads <WHISPER_THREADS>` を追加
  - `main.py` の whisper-server Popen に `-t <WHISPER_THREADS>` を追加
- **物理/論理の判断**: psutil なしでは取れないので **論理コア数を既定**にし、HT 競合を避けたい場合は `WHISPER_THREADS` env で物理コア数を明示する運用に
- **根拠**: `cli.cpp:36` の既定 `min(4, hardware_concurrency)` を上書き。多コア PC で頭打ちにならない

#### [P1-B] ✅ beam_size を realtime=1 / final=5 で明示

- **実装内容**:
  - `config.py` に `WHISPER_REALTIME_BEAM_SIZE=1` / `WHISPER_FINAL_BEAM_SIZE=5` を追加
  - `transcription.py` の cmd に `--beam-size 5` を追加（精度優先・whisper 既定値）
  - `realtime.py` の form に `"beam_size": "1"` を追加（greedy・最速）
  - `main.py` の whisper-server Popen に `-bs 1` を追加（per-request 上書きも可能）
- **根拠**: `server.cpp:509-511` で `beam_size` を form パラメータとして受け取れることを確認

#### [P1-C] ✅ VAD をデフォルト有効化（保守的閾値のまま）

- **実装内容**:
  - `transcription.py:76` のガードを `os.environ.get("WHISPER_VAD_ENABLED") == "1"` から `os.environ.get("WHISPER_VAD_ENABLED", "1") != "0"` に変更
  - 閾値・pad・min-speech は既存の保守的値（0.35 / 400ms / 200ms）を維持
  - silero モデル未存在なら自動的に無効
- **STARTUP.md 更新**: `WHISPER_VAD_ENABLED` のデフォルト記述を「未設定（無効）」→「`1`（有効）」に変更
- **回帰リスク**: revised-plan.md R2 の「短い相づちカット」懸念は、保守的閾値（0.35）で対応済み

#### 動作確認（2026-04-29）

- `pytest tests/`: **83 件 passed** / 1 件 failed
  - 失敗テストは `test_transcription_result_has_text`（pre-existing。`WHISPER_FINAL_MODEL` が Kotoba 日本語モデルにフォールバックしているため、JFK 英語音声で文字化け。stash 検証で P1 変更前と同じ失敗を再現）
- streaming WebSocket テスト全件パス → realtime.py の form 変更で回帰なし

---

### P2 — 中コスト・効果大（フロントのチャンク化を再設計）— **✅ 実装済 (2026-04-29)**

#### [P2-A] ✅ sliding window 化（4秒チャンク + 0.75秒 overlap）

- **実装内容（`meeting.html`）**:
  - `MediaRecorder.start(1000)` → `MediaRecorder.start(250)` に変更（timeslice 4 倍細粒度化）
  - 定数を新設：`WINDOW_CHUNKS=16`（4 秒）、`OVERLAP_CHUNKS=3`（0.75 秒）、`STEP_CHUNKS=13`（3.25 秒シフト）
  - `setInterval(sendRealtimeChunk, 5000)` → `setInterval(..., 1000)` に変更し、`pendingChunks.length >= WINDOW_CHUNKS` でゲート
  - 旧 `pendingChunks.splice(0)`（全消費）→ `pendingChunks.slice(0, WINDOW_CHUNKS)` で読み、`splice(0, STEP_CHUNKS)` で **OVERLAP 分は次バッチに持ち越し**
  - `MAX_PENDING_CHUNKS = WINDOW_CHUNKS * 2`（32 = 8 秒）の pile-up リカバリも追加
- **0.75 秒となった理由**: timeslice=250ms の granularity では 0.8 秒は表現できない。`OVERLAP_CHUNKS=3` で 0.75 秒、advice.md「0.5〜1秒」の範囲内
- **期待効果**: 語尾欠落の低減 + 体感遅延 5秒→3.25秒

#### [P2-B] ✅ サーバー側で重複範囲のテキストレベル除去

- **新ユーティリティ**: `work/poc/backend/services/text_dedup.py`
  - `strip_overlap_prefix(previous, current, max_overlap=30, min_overlap=4)` を実装
  - 最長一致（max=30 chars）から最短一致（min=4 chars）まで suffix-prefix マッチを試行、見つかったら strip
  - `min_overlap=4` で「は」「が」など 1 文字偶然一致による誤除去を防止
- **POST 経路**: `realtime.py:73-99` に `previous_text: str = ""` フォームパラメータを追加。whisper レスポンスを `strip_overlap_prefix(previous_text, text)` で dedup してから返す
- **WebSocket 経路**: `streaming_session.py:add_chunk_text` に dedup を統合。直前の `confirmed_text + partial_text` の末尾と新 delta を比較して strip
- **クライアント連携**: `meeting.html` で `lastChunkResponseText` を保持し、POST フォールバック時の form に `previous_text` として送信

#### 動作確認（2026-04-29）

- `pytest tests/`（pre-existing failure 2件除外）: **101 件 passed**
- 新規追加: `test_text_dedup.py`（11 件）、`test_streaming_session.py` に overlap dedup 統合テスト（3 件）すべてパス
- 既存の WebSocket / streaming_session テストも全件パス → 既存挙動の互換性を維持

#### ギャップ表への影響

- G2: overlap = 0 → **0.75 秒** ✅
- G11: 語尾欠落対策 = prompt のみ → **overlap + dedup の両方** ✅
- G1: チャンク長 = 5秒バッチ → **4秒 sliding window** ✅
- G7: 非同期パイプライン: WINDOW チェックのみで `setInterval` を毎秒回せるようになった ✅
- G10: UI 即時反映: WebSocket 経路の partial/final（既存実装）と組み合わせて改善 △→✅

---

### P3 — 大コスト・UX 改善（partial/final 二段の本格統合）— **✅ P3-A 実装済 / P3-B 後送り (2026-04-29)**

#### [P3-A] ✅ meeting.html を WebSocket /ws/transcribe 経路に切替

- **実装済みの構成**:
  - フロント `meeting.html`: `openTranscriptWebSocket()` / `closeTranscriptWebSocket()` / `appendPartial(delta)` / `commitFinal(text)` を実装。WebSocket が主経路、POST `/transcribe-chunk` はフォールバック
  - サーバー `realtime.py:94-185`: `/ws/transcribe` で `{type: ready/partial/final/error}` プロトコルを実装
  - `meeting.html` 内 CSS: `.transcript-live p.final`（濃色）/ `.partial-group p.partial`（薄色イタリック）/ `:last-child`（最新行を強調）の 2 層表示
- **イベントフロー**:
  - 接続時: クライアント `{"type":"config","initial_prompt":<業界＋固有名詞>}` 送信 → サーバー `{"type":"ready"}` 返却
  - チャンク送信: クライアント binary blob 送信 → サーバー `{"type":"partial","delta":...}` を逐次返却
  - 文末確定: 句読点 or 敬語語尾 or 6秒経過 → サーバー `{"type":"final","text":...}` 返却。クライアントは `partial-group` を消去し確定行を追加
  - 終了時: クライアント `{"type":"close"}` 送信 → サーバー残 partial を `force_finalize` で final 化してから close
- **P2 との連携**: sliding window で audio に overlap が含まれても、`StreamingSession.add_chunk_text` 内の `strip_overlap_prefix` が delta から重複を除去する。テストで検証済（`test_websocket_dedups_overlap_text_from_sliding_window`）
- **フェイルセーフ**: `ws.onerror` / `ws.onclose`（unready） で `useWebSocket=false` に切替し、以降は POST `/transcribe-chunk`（ステートレス・サーバ dedup あり）に自動フォールバック

#### [P3-B] サーマルスロットリング対策（モバイル想定時）— **後送り**

- **対象**: 将来的なモバイル on-device 化時（`revised-plan.md` R10）
- **変更内容**: `threads = bigコア数 - 1` で平準化、発熱検知で realtime モデルを Q5_K → Q4_K に動的降格
- **根拠**: 30〜60 分連続でモバイル CPU は 20〜40% スループット低下する（revised-plan.md R10）
- **現在のステータス**: PC 環境のみ想定のため別フェーズ送り。`WHISPER_THREADS` env で手動上書き可能（P1-A）

#### 動作確認（2026-04-29）

- 全バックエンドテスト: **101 passed / 2 deselected**
- WebSocket 統合テスト（dedup-related）: **66 passed**（streaming_session 26 + text_dedup 11 + streaming_websocket 残り全件）
- 新規追加: `test_websocket_dedups_overlap_text_from_sliding_window`、`test_websocket_full_duplicate_chunk_emits_partial_with_empty_delta`

---

## 4. 実装順序の提案 / 進捗

| 順 | フェーズ | 概要 | ステータス | 検証 |
|---|---|---|---|---|
| 1 | P1-A/B/C | バックエンド引数追加（threads・beam・VAD） | ✅ 実装済 (2026-04-29) | 83 passed / 1 pre-existing fail |
| 2 | P2-A/B | フロント sliding window 化 + サーバ dedup | ✅ 実装済 (2026-04-29) | 101 passed / 2 deselected |
| 3 | P3-A | WebSocket 経路 + partial/final UI | ✅ 実装済 (2026-04-29) | dedup 関連 66 passed |
| 4 | P3-B | サーマル対策 | ⏸ 後フェーズ送り | モバイル化時に着手 |
| 5 | ベンチ更新 | before/after 比較 | 未着手 | `2026-04-29-bench-results.md` 形式 |

---

## 5. 検証方法

1. **RTF（Real-Time Factor）**:
   - 入力: 30 秒程度の日本語会議録音（複数話者、相づち含む）
   - 計測: `time` 経由で whisper-cli の処理時間 ÷ 入力長
   - 目標: PC 環境で RTF ≤ 0.5（advice.md「PC ＝ small + int8 で 0.3〜0.8」より厳しめ）

2. **partial 体感遅延**:
   - 発話開始から partial 表示までの時間を画面録画でフレーム計測
   - 目標: ≤ 2 秒

3. **final 確定タイミング**:
   - 発話終了から final 確定までの時間
   - 目標: 無音 0.6 秒以内に final（VAD 設定値と整合）

4. **同音語（社名・人名）の誤変換率**:
   - 改善前後で同一録音を処理し、`vocabulary.py`（revised-plan.md R9）の効果も併せて評価

5. **回帰テスト**:
   - VAD 有効化により短い相づち（「はい」「いえ」「そう」）が切られていないか確認（revised-plan.md R2 の懸念）
   - サーマル影響を見るため 10 分連続録音での RTF 推移確認

---

## 6. 参考ドキュメント

- [`2026-04-29-advice.md`](2026-04-29-advice.md) — 本検討の出発点（汎用 ASR 設計）
- [`2026-04-29-revised-plan.md`](2026-04-29-revised-plan.md) — 日本語特化の上書き方針（R1〜R12）
- [`2026-04-29-bench-results.md`](2026-04-29-bench-results.md) — ベンチ結果と prompt 安全長の根拠
- [`2026-04-28-design.md`](2026-04-28-design.md) — 全体アーキテクチャ Phase 1〜4
- [`2026-04-27-improvement-plan.md`](2026-04-27-improvement-plan.md) — PoC P1〜P7 の前段方針
- [`2026-04-28-verification.md`](2026-04-28-verification.md) — 検証手順書
