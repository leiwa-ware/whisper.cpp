# GitHub Issue Draft: kotoba-whisper (2-layer distil) collapses with prompts ≥35 chars

**Target repo**: https://github.com/ggml-org/whisper.cpp
**Title candidate**: `2-layer distil models (e.g. kotoba-whisper-v2.2) emit empty / drastically truncated output when --prompt is moderately long`
**Status**: 起票候補（未起票）／プロジェクト内ガード [services/prompt_safety.py](../poc/backend/services/prompt_safety.py) で workaround 実装済み

---

## 投稿本文（English, ready to paste）

### Summary

When using a 2-layer distillation model — concretely `kotoba-whisper-v2.2`
(`Pomni/kotoba-whisper-v2.2-ggml-allquants`) — the decoder produces empty
or drastically truncated output once `--prompt` reaches **roughly 35
characters of Japanese** (≈70 BPE tokens). With the same audio and shorter
prompts the model transcribes correctly. Other models (small / medium /
large-v3) handle prompts of identical length without issue.

The threshold shifts when `--no-timestamps` is used:

| flags                                    | threshold | n_tokens at threshold |
|------------------------------------------|-----------|----------------------|
| `--output-json` (no `-nt`)               | 32 OK / 35 BROKEN | ≈70 |
| `-nt` (`--no-timestamps`)                | 27 OK / 30 BROKEN | ≈63 |

So timestamp tokens contribute ~3-5 chars worth of headroom before collapse.

### Reproduction

Sample audio and prompts available at: (link to gist / attachments)

```bash
# Working: 30-char prompt
./build/bin/Release/whisper-cli \
  -m models/ggml-kotoba-v2.2-q5_k.bin \
  -f sample_5.8s_japanese.wav \
  -l ja --output-json -of out --no-prints \
  --no-speech-thold 0.6 --entropy-thold 2.4 \
  --prompt "商談会議。成約率や見積もり、フォローアップについて話します。"
# → JSON has 1 segment with full transcription

# Broken: 35-char prompt
./build/bin/Release/whisper-cli \
  -m models/ggml-kotoba-v2.2-q5_k.bin \
  -f sample_5.8s_japanese.wav \
  -l ja --output-json -of out --no-prints \
  --no-speech-thold 0.6 --entropy-thold 2.4 \
  --prompt "商談会議。成約率や見積もり、フォローアップについて話します。改善"
# → JSON has 0 segments (empty transcription)
```

Verified across `q4_k`, `q5_k`, `q8_0`, `f16` quantizations of
`kotoba-whisper-v2.2-ggml`. Identical input audio with `ggml-medium.bin`
or `ggml-small.bin` and the same long prompt transcribes without issue.

### Model attributes

The kotoba-whisper-v2.2 GGML model has:

```
n_vocab       = 51866
n_audio_layer = 32
n_text_ctx    = 448
n_text_state  = 1280
n_text_head   = 20
n_text_layer  = 2     ← distillation: only 2 decoder layers
```

The encoder is full `large-v3` (32 layers), the decoder is distilled to **2 layers**.

### Hypothesis: stale `is_distil` heuristic

`src/whisper.cpp` at line 6969 (current `master`) classifies distil models as:

```cpp
const bool is_distil = ctx->model.hparams.n_text_layer == 2 && ctx->model.hparams.n_vocab != 51866;
```

This was written when first-generation distil-whisper used a smaller vocab.
Newer distillations such as `kotoba-whisper-v2.2` keep the **v3-turbo
vocab size of 51866**, so `is_distil` is false for them and the
"force `no_timestamps`" path is skipped.

That alone does not explain the collapse (it still fails with `-nt` set
explicitly), but it shows the heuristic is no longer accurate for modern
2-layer distillations and may need broadening to `n_text_layer == 2`.

### Suspected root cause

A 2-layer decoder has very limited self-attention capacity. When the
prompt fills the text-side context past a few dozen tokens, the limited
attention dilutes audio-feature attention. Empirically the decoder begins
emitting `<|endoftext|>` after only a handful of generated tokens, which
manifests as either:
- 1-segment with `先週` only (typical with `-nt`)
- 0 segments (output is empty / discarded by VAD-style filtering when no real text emitted)

Lowering `--no-speech-thold` and `--entropy-thold` does not change the
threshold; using `--carry-initial-prompt` does not help and sometimes
makes it worse.

### Proposed fixes (any of)

1. **Broaden the `is_distil` detection** at `src/whisper.cpp:6969` to include
   `n_text_layer == 2` regardless of vocab. The behavioral consequence
   (forcing `no_timestamps`) may already be undesirable per the empirical
   data above, so this should be guarded behind a separate "distil safety"
   flag.

2. **Add a soft warning** when `params.prompt_n_tokens > N_DISTIL_PROMPT_SAFE`
   (suggest ~50 tokens) on a model with `n_text_layer <= 4`:
   ```cpp
   if (n_text_layer <= 4 && params.prompt_n_tokens > 50) {
       WHISPER_LOG_WARN("%s: prompt is %d tokens; distil models with "
                        "n_text_layer=%d may produce truncated output. "
                        "Consider truncating to <50 tokens or splitting "
                        "via --carry-initial-prompt.\n",
                        __func__, params.prompt_n_tokens, n_text_layer);
   }
   ```

3. **Document** in README / examples that distil models have practical
   prompt-length limits much smaller than `n_text_ctx/2 = 224`.

### Workaround in our project (interim)

`work/poc/backend/services/prompt_safety.py` truncates prompts to ≤24
characters when the target model basename contains "kotoba". The
boundary is conservative (well below the empirical 32-char OK / 35-char
broken edge) and prefers Japanese sentence-end punctuation when possible.

### Environment

- whisper.cpp commit: <fill in `git rev-parse HEAD`>
- OS: Windows 11 Pro 26200 / MSVC build
- CPU: Intel x64, no GPU
- Models: `Pomni/kotoba-whisper-v2.2-ggml-allquants` (q4_k, q5_k, q8_0, f16)

---

## 起票時の付帯資料

このリポジトリ内に証跡として残る関連ファイル:

- [work/UIMock/2026-04-29-bench-results.md](2026-04-29-bench-results.md) — 詳細ベンチ結果
- [work/poc/backend/services/prompt_safety.py](../poc/backend/services/prompt_safety.py) — workaround 実装
- [work/poc/backend/tests/test_prompt_safety.py](../poc/backend/tests/test_prompt_safety.py) — 24 ケースの単体テスト
- 再現スクリプト: `C:\Users\...Temp\bench_prod_threshold.py`、`bench_prod_30_51.py`

## 起票判断のチェックポイント

- [ ] 既存 issue 検索（`kotoba prompt`, `distil prompt collapse`, `2-layer prompt`）で重複なし
- [ ] HEAD コミットでの再現確認（whisper.cpp は活発に更新されるため）
- [ ] サンプル音声を gist にアップ（`part_0.wav` 5.8s 日本語ビジネス会話）
- [ ] 起票後、本ドキュメント末尾に issue URL を追記

---

*作成日: 2026-04-29*
*関連: work/UIMock/2026-04-29-bench-results.md §3 問題A、work/UIMock/2026-04-29-revised-plan.md §10 追9*
