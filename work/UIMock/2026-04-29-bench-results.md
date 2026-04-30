# ベンチマーク結果: distil-whisper-ja モデル切替検証

**実施日**: 2026-04-29
**対象**: [2026-04-29-revised-plan.md §5.1](2026-04-29-revised-plan.md) PC 構成（small=realtime / kotoba-q5_k=final）の妥当性検証
**環境**: Windows / CPU only / 8.7GB RAM / [whisper-cli.exe](../../build/bin/Release/whisper-cli.exe)
**入力**: `NeoCRM-mate/python/src/output/part_0.wav` (5.802秒・日本語ビジネス会話)

---

## 1. モデル別 RTF と転写出力

| モデル | サイズ | 時間 | RTF | リアルタイム判定 |
|---|---|---|---|---|
| ggml-small.bin (244M params, 英語ベース) | 488MB | **7.4s** | **1.28** | borderline (chunk batching で運用可) |
| ggml-kotoba-v2.2-q5_k.bin (Medium-distil-ja) | 538MB | 34.3s | 5.91 | **too slow** |
| ggml-kotoba-v2.2-q8_0.bin (Medium-distil-ja) | 818MB | 32.6s | 5.62 | **too slow** |

**転写結果（同一音声）**:
- small:        「先週の**制約**率だけど目標**に10%**に対して15%にとどまったね」
- kotoba-q5_k:  「先週の**制約**率だけど目標**20%**に対して15%にとどまったね」
- kotoba-q8_0:  「先週の**制約**率だけど目標**20%**に対して15%にとどまったね」

**観察**:
1. **数値精度**: small は 20%→10% と取り違える。kotoba は両方 20% で一致。
2. **同音異義語**: 全モデルが「成約率」→「制約率」に誤認識（業務用語が一般語に負ける）。
3. **q5_k vs q8_0**: q8_0 が 0.3s ほど速い（量子化カーネルの差）。サイズは q5_k が小さい。

---

## 2. 語彙プロンプトの効果（kotoba-q5_k 単独で検証）

| プロンプト | 時間 | 出力 |
|---|---|---|
| なし | 40.1s | 先週の制約率だけど目標20%に対して15%にとどまったね |
| `成約率` | 43.7s | 同上（成約率に修正されない） |
| `商談` | 47.8s | 同上 |
| `成約率について話します。` | 50.9s | 同上 |
| `営業会議です。` | 51.1s | 同上 |
| `商談会議。成約率や見積もり、フォローアップについて話します。`（31文字） | 54.0s | **「先週」のみ（出力崩壊）** ⚠️ |

**重要な発見**:
1. **語彙プロンプトは「制約率→成約率」の同音異義語選択を覆さない**。Whisper は音響スコア優先で、業務語の preference は弱い。
2. **kotoba モデルは 30文字以上のプロンプトで出力が壊れる**。1文字～15文字程度なら安全だが、`vocabulary.py` の build_initial_prompt が生成する 100-200文字のプロンプトを kotoba に渡すと**転写が崩壊する**。
3. プロンプト長に比例して処理時間も伸びる（同じ kotoba モデルで 40s → 54s）。

---

## 3. プランとの照合と修正

### 3.1 既存プラン [2026-04-29-revised-plan.md §5.1](2026-04-29-revised-plan.md) の判定

| プラン項目 | 検証結果 | 判定 |
|---|---|---|
| PC realtime = small (488MB) | RTF 1.28 で borderline | ✅ **妥当** |
| PC final = kotoba-q5_k (538MB) | 高精度（数値正確）かつ実行可能 | ✅ **妥当** |
| 語彙プロンプトで CER 10-20%改善（[2026-04-27-improvement-plan.md P3](2026-04-27-improvement-plan.md)） | 同音異義語に対しては改善せず | ⚠️ **条件付き** |

### 3.2 新たに判明した問題と対応

**問題A: kotoba + 長プロンプトで出力崩壊** ✅ **対応済み（2026-04-29）**

- 影響: `services/transcription.py` で final transcription（kotoba）に長い `initial_prompt` を渡すと、転写が崩壊する可能性
- 詳細閾値: 30文字以上で破綻、27文字までは正常（5文字刻みで実測確認）
- **対応**: [services/prompt_safety.py](../poc/backend/services/prompt_safety.py) を新規追加
  - `safe_prompt_for_model(prompt, model_path)` が kotoba 検出時に **24文字** を上限に切断
  - 句読点（。、！？空白）境界で自然に切断、なければ hard cut
  - [transcription.py](../poc/backend/services/transcription.py) と [realtime.py](../poc/backend/api/realtime.py) の2経路に適用
  - kotoba 以外（small/medium/base 等）はパススルーで無影響
- E2E 検証: 51文字プロンプト → 22文字に短縮 → kotoba が正常な28文字を返した（崩壊なし）
- 単体テスト: [tests/test_prompt_safety.py](../poc/backend/tests/test_prompt_safety.py) 24ケース
- 恒久対応（要 follow-up）: whisper.cpp 側のバグ調査 or kotoba モデルの再変換検証

**問題B: 同音異義語（成約率↔制約率）はプロンプトで修正不可**

- 影響: 業務用語の固有名詞ではない一般同音語は ASR 段階で正解できない
- 対応: **LLM 後処理（qwen3:1.7b）で文脈ベース修正**を頼る（既に実装済み [services/summarizer.py](../poc/backend/services/summarizer.py)）
- プラン §4.1 原則に追記: 「同音異義語は ASR で正解しない前提で LLM 後処理に委ねる」

**問題C: モバイル向け distil-whisper-ja-q4 (~200MB) が GGML として存在しない**

- 影響: [revised-plan §5.1](2026-04-29-revised-plan.md) の iPad/Android 構成のうち realtime 用「distil-whisper-ja-q4/q5」は現時点で**入手困難**
- 候補:
  - `Pomni/kotoba-whisper-v2.2-ggml-allquants` の q4_k (444MB) → モバイルでは大きすぎ
  - `whisper-base.bin` (148MB) → 日本語特化なし、CER 25% 程度
  - **要対応**: 自前で kotoba を base/small サイズに distill する研究タスクが必要 → Phase 3+ ロードマップへ

---

## 4. 結論と次アクション

### 結論

- **PC 構成（small=realtime / kotoba-q5_k=final）は実機ベンチで妥当性確認**
- **realtime 用に kotoba を使うことは CPU 環境では不可能**（RTF 5+）
- **語彙プロンプトの効果は punctuation 追加レベル**であり、同音異義語修正は LLM 後処理に委ねる
- **kotoba + 長プロンプトの組合せは avoid**

### 即時対応（Step 0 完了に必要）

1. ✅ 検証完了 → PC 構成は本ベンチで確定
2. **要対応**: [services/transcription.py](../poc/backend/services/transcription.py) で kotoba 使用時のプロンプト長を 15文字以内に制限する安全装置を入れる
3. **要対応**: [revised-plan.md §10](2026-04-29-revised-plan.md) 「よくある失敗」に「追9: kotoba モデルに 30文字以上のプロンプトを渡す → 出力崩壊」を追記

### モバイル向けロードマップ修正

- Step 1 (iPad WhisperKit) の realtime モデルは **kotoba-q4_k (444MB)** を第一候補に変更（distil-whisper-ja-q4 の代替）
- ただし iPad A14+ で RTF < 1.0 が達成できるか実機検証が必要（Apple Silicon は CPU でも whisper を高速処理する Metal 並列性あり）

### Step 0 完了判定

- [x] PC dual-lane 構成検証
- [x] 語彙プロンプト挙動の確定
- [x] kotoba プロンプト崩壊の発見・記録
- [ ] 後続: transcription.py のプロンプト長安全装置（別タスク）
- [ ] 後続: revised-plan.md §10 への追記（別タスク）

---

## 5. 再現方法

```bash
# WAV を 16kHz に変換
ffmpeg -y -i "C:/work/30.Projects/102.AI_Projects/NeoCRM-mate/python/src/output/part_0.wav" \
  -ar 16000 -ac 1 -c:a pcm_s16le "C:/.../AppData/Local/Temp/part_0_16k.wav"

# ベンチマークスクリプト実行
cd C:/work/30.Projects/102.AI_Projects/whisper.cpp/whisper.cpp
./work/poc/backend/venv/Scripts/python.exe "C:/.../AppData/Local/Temp/bench_models.py"
./work/poc/backend/venv/Scripts/python.exe "C:/.../AppData/Local/Temp/bench_kotoba_small_prompt.py"
```

スクリプトは `C:\...\Temp\` に保存済み。

---

*作成日: 2026-04-29 / 検証対象: 2026-04-29-revised-plan.md §5.1 PC 構成*
