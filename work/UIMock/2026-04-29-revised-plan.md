# 訂正版計画書: CPU環境・モバイル端末・日本語会議リアルタイム文字起こしシステム

**作成日**: 2026-04-29
**対象**: `work/UIMock/2026-04-29-advice.md`（汎用ASRアドバイス）のレビュー結果を統合した訂正版計画
**前提プロジェクト**: whisper.cpp ベースの日本語会議議事録 PoC（[`work/poc/backend/`](../poc/backend/)）

---

## 1. このドキュメントの位置付け

### 1.1 目的

`2026-04-29-advice.md` は **汎用的なリアルタイムASR設計アドバイス**で、英語前提の Whisper 系全般に通用する内容だった。しかし本プロジェクトは以下の固有制約があり、汎用アドバイスをそのまま採用すると**現PoCで意図的に避けた失敗を再導入するリスク**がある。

- 日本語会議（同音異義語密度・短い相づち・敬語語尾）
- CPU only 環境（スマホ・iPad・タブレット端末）
- 業界別ドメイン語彙（営業/物流/小売）
- 機密性の高い会議内容（オンデバイス or 閉域前提）

本書は元アドバイスの **「正しいが文脈不適切」「言及がなく危険」** な12項目（R1-R12）を訂正し、本プロジェクトに適用可能な実装計画として再構成する。

### 1.2 既存ドキュメントとの関係

| ドキュメント | 役割 | 本書との関係 |
|---|---|---|
| [2026-04-28-design.md](2026-04-28-design.md) | 全体アーキテクチャ Phase 1-4 | 上位設計。**本書はその差分修正のみ**を担当 |
| [2026-04-27-improvement-plan.md](2026-04-27-improvement-plan.md) | PoC P1-P7 修正 | 既存実装の最適化指針。本書は **その方針を端末別に拡張** |
| [2026-04-28-verification.md](2026-04-28-verification.md) | 検証手順書 | 本書の Step 0 検証で継続利用 |
| [2026-04-29-advice.md](2026-04-29-advice.md) | レビュー対象（汎用） | **本書で訂正される対象** |

### 1.3 本書を読むべき場面

- 元アドバイスの「small.int8」「VAD必須」「beam=1」をそのまま実装する前
- iPad/Android タブレットでの on-device 化を検討する時
- partial/final 二段出力の API 設計をする時

---

## 2. 想定環境の明確化

### 2.1 ターゲット端末と実効リソース

| 端末カテゴリ | 代表機種 | 物理RAM | 1アプリ実効RAM | 物理コア（big） |
|---|---|---|---|---|
| PC（現PoC） | x86/ARM デスクトップ | 8.7GB+ | 4-6GB | 4+ |
| iPad（高位） | iPad Pro M2 / A14+ | 8-16GB | 3-4GB | 4-6 |
| Android タブレット高位 | SD 8 Gen 1+ | 8-12GB | 2.5-3GB | 3-4 |
| Android タブレット中位 | SD 7 Gen 2 | 4-6GB | 1.5-2GB | 2-3 |
| スマホ（汎用） | iPhone 14 / Pixel 7+ | 4-8GB | 1.5-2GB | 2-4 |

> **重要**: 「物理RAM」と「1アプリ実効RAM」は別物。iOS / Android はバックグラウンド OS や WebView 等で常時 1-3GB 消費している。**モデルサイズ + KV キャッシュ + 録音バッファ** の合計が実効上限を超えると即 OOM kill される。

### 2.2 ネットワーク前提

- **完全on-device** または **閉域内サーバ通信**（クラウド外）
- Phase 1 では LLM 後処理のみサーバ側で実行する選択肢を残す
- パブリック API（OpenAI Whisper 等）は使用しない

---

## 3. 元アドバイスのリスクサマリ（R1-R12）

| # | 元アドバイスの主張 | 本プロジェクトでの問題 | 訂正の方向性 |
|---|---|---|---|
| **R1** | 「smallモデル前提（モバイル）」 | 英語ベース small は**日本語CER 30-40%**で実用不可 | Kotoba-Whisper-v2.2 (Q4_K/Q5_K) または distil-whisper-ja を使用 |
| **R2** | 「VADは必須・無音検出でfinalize」 | Silero-VAD は**「はい」「いえ」「そう」など短い相づちを切る**。現PoCは [config.py:64-70](../poc/backend/config.py) で**VAD既定OFF** | threshold=0.35 + pad_ms=400 の**慎重設定**、または時間ベース確定で代替 |
| **R3** | 「beam=1〜3」 | 日本語は同音異義語が多くbeam=1は誤変換が増える | **realtime=1 / final=5** の二段で速度と精度を両立 |
| **R4** | 「partialを即出し（UXで遅延を隠す）」 | 現PoC `/api/transcribe-chunk` は **interim のみで partial/final 二段未実装** | 確定タイミング（VAD or 時間 or 文末ヒューリスティクス）と UI commit/edit 遷移を仕様化 |
| **R5** | 「3〜5秒チャンク＋オーバーラップ0.5〜1秒」 | 機械的な切断で敬語・語尾が壊れる | チャンク境界で **initial_prompt に直前文脈200字を継承**（[2026-04-27-improvement-plan.md](2026-04-27-improvement-plan.md) P5） |
| **R6** | iOS「Metal有効化」/Android「NNAPI」 | Metal 生実装は工数大、NNAPI は whisper モデルと相性悪い | iOS = **WhisperKit (Core ML)**、Android = **whisper.cpp NDK + Q5_K**。中位機は Q4_K に降格 |
| **R7** | ノイズ除去への言及なし | 物流倉庫・小売店舗は **SN比 10-15dB** で危険 | RNNoise（[noise_reduction.py](../poc/backend/services/noise_reduction.py)）必須。会議室=mild / 店舗=moderate / 倉庫=aggressive |
| **R8** | LLM後処理への言及なし | 同音語修復には **小型LLM（qwen3:1.7b / gemma3:2b）が事実上必須** | モバイル端末では同期実行禁止。**確定後にサーバ送信** または **会議終了後一括** |
| **R9** | 語彙プロンプト戦略なし | 業界用語（成約率・ピッキング・棚割り）は initial_prompt 戦略で **CER 10-20%改善** | 自然文プロンプト（[vocabulary.py](../poc/backend/services/vocabulary.py)）。**カンマ区切り語彙列は逆効果**で禁止 |
| **R10** | バッテリー・サーマルへの言及なし | 30-60分連続でモバイル CPU は**20-40%スループット低下** | `threads = bigコア数-1` で平準化。発熱検知で realtime モデルを Q4 へ自動降格 |
| **R11** | メモリ上限への言及なし | iPad/Android タブレットの実効 1.5-3GB / app 制約 | Q8_0（818MB）は不可、Q5_K (538MB) or Q4_K (444MB) のみ |
| **R12** | プライバシー・オフライン要件 | 会議内容は機密性大 | 完全on-device or 閉域サーバを明示。OpenAI API 等の外部送信を全面禁止 |

---

## 4. 訂正版・設計原則

### 4.1 6つの中核原則（元アドバイスの「設計ルール」差し替え）

1. **日本語特化モデル前提** — Kotoba-Whisper-v2.2 / distil-whisper-ja。英語ベース small / medium は **realtime のフォールバックのみ**
2. **VAD は条件付き有効** — threshold=0.35 + pad_ms=400 + 時間ベース確定併用。**汎用 0.5 設定は禁止**
3. **二段モデル戦略** — realtime（軽量、低beam、即時partial）+ final（高精度、高beam、確定/再生成）
4. **チャンク境界で文脈継承** — initial_prompt に直前200字。これにより敬語・語尾・固有名詞の継続性を保つ
5. **業界別語彙は自然文** — 「商談会議。成約率や見積もり、フォローアップについて話します」のような**文体プロンプト**
6. **LLM 後処理は確定後** — モバイルでは同期実行禁止。サーバ閉域 or 会議終了後の一括処理

### 4.2 元アドバイスから保持する部分（良い指摘）

| 元アドバイス | 保持判断 |
|---|---|
| 録音/推論/UI の非同期分離 | ✅ そのまま採用 |
| 短いチャンク（3-5秒）+ オーバーラップ | ✅ ただし**チャンク=4秒, overlap=0.8秒** に固定 |
| temperature=0 で出力安定 | ✅ そのまま採用 |
| beam を絞る（速度優先） | ⚠️ realtime のみ。final は beam=5 |
| partial/final の二段出力 | ✅ 設計思想は採用、実装仕様は本書 §7 で詳細化 |

---

## 5. 端末別構成（訂正版）

### 5.1 マトリクス

| 端末 | realtime モデル | final モデル | LLM後処理 | チャンク | beam | スレッド |
|---|---|---|---|---|---|---|
| **PC（現PoC）** | small (488MB) | kotoba-q5_k (538MB) | qwen3:1.7b on-device | 4s/0.8s | 1/5 | 物理コア-1 |
| **iPad A14+** | distil-whisper-ja-q5 (~300MB) | kotoba-q5_k (538MB) | サーバ送信（確定後） | 4s/0.8s | 1/5 | 4 |
| **Android 高位** | kotoba-q4_k (444MB) | （即時確定で final 省略可） | 確定後サーバ送信 | 4s/0.8s | 1 | 3 |
| **Android 中位** | small-q4_k (~250MB) | （バッチ転送、サーバ側 final） | サーバ専任 | 4s/0.8s | 1 | 2 |
| **スマホ汎用** | distil-whisper-ja-q4 (~200MB) | サーバ転送 | サーバ専任 | 4s/0.8s | 1 | 2 |

### 5.2 RTF・OOM・遅延の目安（理論値）

| 端末 | 想定 RTF (realtime) | 想定 RAM 使用 | 想定 partial 表示遅延 | 想定 final 確定遅延 |
|---|---|---|---|---|
| PC | 0.3-0.6 | 1.5-2GB | 0.5-1.0s | 1.5-2.5s |
| iPad A14+ | 0.6-1.0 | 1.5-2GB | 0.8-1.2s | 2.0-3.0s |
| Android 高位 | 0.8-1.4 | 1.5-2.0GB | 1.0-1.5s | 2.5-4.0s |
| Android 中位 | 1.2-2.0 | 1.0-1.5GB | 1.5-2.5s | サーバ依存 |
| スマホ | 1.0-1.8 | 0.8-1.2GB | 1.2-2.0s | サーバ依存 |

> RTF > 1.0 でも **partial 即時表示 + チャンク並列処理**で体感リアルタイム化は可能。ただし RTF > 1.5 が連続するとバッファが膨張するため**バッファ上限 10秒**で古い chunk を破棄する設計が必要。

### 5.3 端末別実装パス

- **PC**: 現PoC 拡張（[main.py](../poc/backend/main.py) の whisper-server に streaming endpoint 追加、[realtime.py](../poc/backend/api/realtime.py) を partial/final 二段化）
- **iPad**: WhisperKit (Swift) on-device。Core ML 変換済み Kotoba-Whisper を使用。**Metal 生実装はしない**
- **Android 高位**: whisper.cpp の NDK ビルド（[bindings/java/](../../bindings/java/)）。NNAPI は使わない
- **Android 中位**: 同上 + Q4_K に降格、final はサーバへ
- **スマホ**: distil-whisper-ja (Q4) on-device for partial、final はサーバ

---

## 6. パラメータ表（訂正版）

| パラメータ | 推奨値 | 理由 / 出典 |
|---|---|---|
| chunk長 | **4秒** | 5秒は相づちで切れる、3秒は文末欠落。日本語平均文長から逆算 |
| overlap | **0.8秒** | 語尾欠落防止 + 文脈接続。元アドバイス 0.5-1秒の中央値 |
| beam_size (realtime) | **1** | 速度優先 |
| beam_size (final) | **5** | 同音語修復、final は時間余裕あり |
| temperature | **0** | 出力安定（元アドバイス踏襲） |
| no_speech_threshold | **0.6** | 幻覚抑止。現PoC [transcription.py:62](../poc/backend/services/transcription.py) 継承 |
| entropy_threshold | **2.4** | 同上 [transcription.py:63](../poc/backend/services/transcription.py) |
| VAD threshold | **0.35**（有効時） | Silero 既定 0.5 は短い相づちを切る |
| VAD speech_pad_ms | **400** | 立ち上がり音欠落防止 |
| VAD finalize 補助 | 時間 6秒 経過で強制確定 | VAD 沈黙が来ないケースの保険 |
| threads | **物理 big コア数 - 1** | サーマル余裕、UI スレッド確保 |
| initial_prompt | 業界別自然文 200字 + 直前文脈 200字 | [vocabulary.py](../poc/backend/services/vocabulary.py) + チャンク継承 |

---

## 7. UI/UX: partial/final 二段出力の具体仕様

### 7.1 状態遷移

```
[録音中]
  ├─ partial chunk N (灰色, 編集不可)
  │     ↓ 0.8-1.5s
  ├─ partial chunk N (灰色, 修正後)
  │     ↓ VAD沈黙 OR 6秒経過 OR 文末ヒューリスティクス
  └─ final chunk N (黒色, 編集可)
       ↓ 後段
       LLM後処理（サーバ）→ corrected (青色)
```

### 7.2 確定（finalize）トリガー（OR条件）

1. VAD が 800ms 以上の沈黙を検出（VAD有効時のみ）
2. チャンク開始から **6秒経過**（保険、VAD無効時の主トリガー）
3. 文末ヒューリスティクス: 「。」「？」「！」「ですね」「ました」「と思います」等の語尾を検出
4. ユーザが手動で「確定」ボタンを押下

### 7.3 編集ポリシー

- **partial（灰色）**: 編集不可、自動で更新される
- **final（黒色）**: ユーザ編集可、編集すると LLM 後処理から除外
- **corrected（青色）**: LLM 後処理結果。トグルで final 表示と切替可能

### 7.4 既存実装からの差分

現PoC [meeting.html](meeting.html) には `realtimeContextBuffer` が実装済み（[2026-04-28-verification.md](2026-04-28-verification.md) 付録より）。この上に partial/final マーキング、確定トリガー、編集ロックを追加する。

---

## 8. 段階的実装ロードマップ

### Step 0: 現PoC PC側 partial/final 二段化（**最優先・即着手**）

- [`api/realtime.py`](../poc/backend/api/realtime.py) を WebSocket 化（または SSE）
- partial: chunk 受信ごとに即送出
- final: 6秒タイマー or 文末検出で送出
- チャンク継承（initial_prompt に直前200字）を有効化
- 検証: [2026-04-28-verification.md](2026-04-28-verification.md) §8 を流用

### Step 1: iPad WhisperKit on-device

- WhisperKit Swift Package を導入
- Kotoba-Whisper の Core ML 変換（[Pomni/kotoba-whisper-v2.2-coreml] が公開済みか確認、無ければ自前変換）
- AVAudioEngine で 16kHz/16bit 録音 → リングバッファ → 4秒chunk
- partial/final UI は SwiftUI でPC版と同等に
- LLM 後処理は当面サーバ送信（HTTPS / 閉域）

### Step 2: Android whisper.cpp NDK

- [`bindings/java/`](../../bindings/java/) JNI を ARM64 NDK 向けにビルド
- Q5_K（高位機）/ Q4_K（中位機）を端末判定で切替
- AudioRecord で 16kHz 録音
- 高位機は on-device final、中位機は final もサーバ
- スレッド = `Runtime.availableProcessors() - 1`

### Step 3: 端末-サーバ ハイブリッド（LLM後処理API化）

- 既存 [`summarizer.py`](../poc/backend/services/summarizer.py) を `/api/correct-and-summarize` として独立 API 化
- 端末は final テキストを送信、サーバは qwen3:1.7b で修正＋議事録化
- 認証は閉域前提（社内VPN / 端末証明書）

### Step 4: 評価ハーネス

- CER 計測: 同一テスト音声で各端末・各モデルの CER を比較（[2026-04-28-verification.md](2026-04-28-verification.md) §9 を端末別に拡張）
- RTF 計測: 30分連続録音時のサーマル降下率
- バッテリー消費: 30/60/90分連続録音

---

## 9. 検証方法

### 9.1 単体テスト

| テスト | コマンド/箇所 | 合格基準 |
|---|---|---|
| チャンク継承 | `services/transcription.py` の `initial_prompt` に直前200字注入を確認 | 連続発話で固有名詞が継続 |
| 確定トリガー | 6秒タイマー/文末ヒューリスティクスの単体テスト | 各条件で `final` イベント発火 |
| ノイズ除去 | [`noise_reduction.py`](../poc/backend/services/noise_reduction.py) の moderate/aggressive | [2026-04-28-verification.md](2026-04-28-verification.md) §2 を流用 |

### 9.2 端末ベンチマーク

3軸計測を端末ごとに記録:

| 軸 | 計測方法 | 合格基準 |
|---|---|---|
| **CER** | 30秒日本語音声 vs 正解テキスト（CER 計算は[2026-04-28-verification.md](2026-04-28-verification.md) §9 のスクリプト流用） | medium baseline 比 **20%改善** |
| **RTF** | 30分連続録音中の chunk 推論時間 / chunk 長 | サーマル後でも **RTF < 1.5** 維持 |
| **バッテリー** | 30分連続録音前後の電池残量差 | iPad で 8% 以下 / 30min |

### 9.3 E2E 統合テスト

[2026-04-28-verification.md](2026-04-28-verification.md) §8 の手順を partial/final 対応版に拡張:

- WebSocket クライアントで partial/final イベントが両方届くこと
- final 確定後に corrected が遅れて届くこと
- 30分連続会議でメモリリークが無いこと（タスクマネージャー / Xcode Instruments / Android Studio Profiler）

---

## 10. よくある失敗（訂正版）

### 元アドバイスの失敗リスト + 本プロジェクト固有の追加

| # | 失敗 | 結果 |
|---|---|---|
| 元1 | medium を使う | RTF 破綻 |
| 元2 | チャンク > 10秒 | 遅延増大 |
| 元3 | VAD なし | 無音で無駄計算（※ただし VAD threshold 0.5+ も同等の害） |
| 元4 | beam ≥ 5（realtime で） | 速度低下 |
| 元5 | 同期処理 | UIフリーズ |
| **追1** | **英語ベース small / medium を日本語に使用** | CER 30-40%、ユーザ離脱 |
| **追2** | **VAD threshold 0.5+ を日本語で使用** | 「はい」「いえ」等の相づち欠落 |
| **追3** | **カンマ区切り語彙プロンプト** | Whisper が混乱、CER悪化 |
| **追4** | **LLM 後処理を端末で同期実行** | UIフリーズ + バッテリー激減 |
| **追5** | **Q8_0 (818MB) をモバイルで使用** | OOM kill |
| **追6** | **チャンク間で initial_prompt 継承を忘れる** | 固有名詞の連続性が壊れる |
| **追7** | **温度フォールバック有効のままリアルタイム** | partial がぐらつき UX 劣化（temperature=0 固定） |
| **追8** | **発熱対策なしで 30分連続録音** | サーマル降下で RTF 2.0+ → 文字起こし停止 |

---

## 11. 最短で動かす構成（モバイル共通・訂正版）

> 元アドバイスの「最短で動かす構成」も日本語向けに差し替え

| 項目 | 訂正版 | 元アドバイス |
|---|---|---|
| realtime モデル | **distil-whisper-ja-q4 (~200MB)** | small.int8 |
| final モデル | **kotoba-q5_k (538MB)**（高位機）または サーバ | （無し） |
| VAD | threshold=0.35, pad=400ms（条件付き有効） | あり（既定値で） |
| chunk | **4秒** | 3秒 |
| overlap | **0.8秒** | 0.5秒 |
| beam (realtime / final) | **1 / 5** | 1（一段のみ） |
| initial_prompt | **業界別自然文 + 直前200字継承** | （無し） |
| ノイズ除去 | RNNoise (moderate) | （無し） |
| LLM 後処理 | 確定後 サーバ送信 | （無し） |
| temperature | 0 | 0 |
| 確定トリガー | VAD沈黙 OR 6秒タイマー OR 文末 | VAD沈黙のみ |

→ **「ほぼリアルタイム」かつ「日本語会議で実用CER」を両立**

---

## 12. 参照

- [2026-04-29-advice.md](2026-04-29-advice.md) — レビュー対象の汎用アドバイス（本書で訂正）
- [2026-04-28-design.md](2026-04-28-design.md) — 全体設計 Phase 1-4（上位）
- [2026-04-27-improvement-plan.md](2026-04-27-improvement-plan.md) — PoC P1-P7 修正
- [2026-04-28-verification.md](2026-04-28-verification.md) — 検証手順（流用）
- [work/poc/backend/config.py](../poc/backend/config.py) — モデル/VAD/ノイズ設定
- [work/poc/backend/services/transcription.py](../poc/backend/services/transcription.py) — Whisper呼び出し
- [work/poc/backend/services/noise_reduction.py](../poc/backend/services/noise_reduction.py) — RNNoise
- [work/poc/backend/services/vocabulary.py](../poc/backend/services/vocabulary.py) — 業界別プロンプト
- [work/poc/backend/api/realtime.py](../poc/backend/api/realtime.py) — partial/final 拡張対象
- [work/poc/backend/services/summarizer.py](../poc/backend/services/summarizer.py) — LLM後処理（API化対象）

---

*作成日: 2026-04-29 / 対象レビュー文書: `2026-04-29-advice.md` / 出力先: `work/UIMock/2026-04-29-revised-plan.md`*
