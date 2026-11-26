# COSTS.md

Measurements for every stage of the Heritage Short pipeline, computed from `runs.jsonl` (91 lines, 26 Nov 2026). "List-price equivalent" means what the same work would cost at the provider's published pay-as-you-go price, even though most of it ran on free tiers. Counts exclude cache hits unless stated.

## 1. Per-stage table

| Stage | Provider, model | Real calls | Cache hits | Errors | Latency, total | Latency, mean per call | GPU minutes | List-price equivalent (USD) | What I actually paid |
|---|---|---|---|---|---|---|---|---|---|
| refsheet (12 options, 576×1024) | Cloudflare, FLUX.2 klein 4B | 12 | 0 | 0 | 133.0 s | 11.1 s | n/a | 0.0138 | 0 (free allowance) |
| keyframes (10 shots + 1 retake + 1 no-reference test, 1088×1920) | same | 12 | 1 (line 48) | 0 | 105.5 s | 8.8 s | n/a | 0.0417 | 0 (free allowance) |
| narration, Gemini | Gemini 3.8 Flash TTS (Kore) | 9 | 0 | 0 | see note | 6.74 s (first call, line 20) | n/a | about 0.02 (estimate, §3) | 0 (free tier) |
| narration, E2 test | Gemini 3.8 Flash-Lite TTS | 2 | 0 | 0 | 12.0 s | 6.0 s | n/a | under 0.01 (estimate) | 0 (free tier) |
| narration, first version | Addis AI, `am-hamen` | 9 | 0 | 0 | 56.6 s | 6.3 s (4.99–7.32 s) | n/a | about 0.022 (§3) | **3.45 ETB** for 41.4 s |
| music | ACE-Step 1.5 on Colab T4 | 3 | 0 | 0 | 211.0 s (71.19, 68.55, 71.27) | 70.3 s | **3.52** (1.186, 1.143, 1.188) | about 0.02 (§3) | 0 (Colab free tier) |
| shots (Ken Burns) | FFmpeg | 10 | 10 (lines 70–79) | 0 | 129.7 s | 13.0 s | n/a | 0 | 0 |
| radio cut (prototype) | FFmpeg | 4 steps | n/a | 0 | 22.5 s | 5.6 s | n/a | 0 | 0 |
| film | FFmpeg | 10 steps | 0 | 0 | 100.0 s | `join_shots` 33.6 s, `export_9x16` 30.5 s, `export_16x9` 31.6 s | n/a | 0 | 0 |
| smoke tests (6 providers/models, lines 1–9) | Gemini, Addis, Cloudflare | 5 ok, 4 errors | 0 | 4 | 141.5 s (a 118.5 s text call dominates) | n/a | n/a | not priced | 0.198 ETB (Addis, line 9) |

**Note on Gemini narration latency.** Lines 21–28 log 20–22 s each. That figure includes the 21 s wait the code inserts between Gemini calls (FAILURES F14), so only line 20 (6.74 s) is the true latency of a call. Nine calls took about 175 s logged, 2 min 50 s of wall-clock time.

**Wall-clock and GPU.** The whole score cost 3.52 GPU-minutes on a T4. The film's picture work (keyframes, shots, film) took about 335 s of compute in total.

## 2. Free tiers and their limits (what limited me)

| Service | Limit | Reset | Effect |
|---|---|---|---|
| Cloudflare Workers AI | 10,000 neurons a day, $0.011 per 1,000 neurons beyond | 00:00 UTC | All 24 images used about 5,030 neurons (§3): half a day's allowance, no 429 |
| Gemini TTS (Flash), AI Studio | 10 requests a day, 3 a minute | midnight Pacific = 08:00 UTC = 11:00 EAT in November | A 9-line pass used the day's quota (F13); the code keeps calls 21 s apart and aborts above 9 |
| Gemini TTS (Flash-Lite) | 10 requests a day | same | Used 2 (E2) |
| Addis AI | no daily cap; paid per second | n/a | 3.45 ETB for the first narration |
| Colab free T4 | no fixed minutes; GPU availability is not guaranteed | n/a | "No backend with GPU available" once (F12); Kaggle's queue never started (F11) |

To count today's Flash TTS calls (PowerShell, from the repo folder in the VS Code terminal; it prints one line per call with time and shot):

```
Get-Content runs.jsonl | ForEach-Object { $_ | ConvertFrom-Json } | Where-Object { $_.model -eq "gemini-3.8-flash-tts" -and $_.status -eq "ok" -and -not $_.cache_hit } | Select-Object ts, shot_id
```

## 3. How the list-price equivalents were computed

- **Cloudflare:** published rates for FLUX.2 klein 4B are $0.000287 per output 512×512 tile and $0.000059 per input tile (5.37 and 26.05 neurons) [https://developers.cloudflare.com/workers-ai/platform/pricing/]. A 1088×1920 keyframe is 3×4 = 12 output tiles = $0.003444 and about 313 neurons; with the 287×511 reference (1 input tile) $0.003503 and about 318 neurons. A 576×1024 reference option is 2×2 = 4 tiles = $0.001148 and about 104 neurons. Total for the 24 images: about 5,030 neurons. The `cost_usd_equiv` column in `runs.jsonl` uses the same tile prices; how partial tiles round is not documented, so it is an estimate.
- **Gemini 3.8 Flash TTS:** list price $0.50 per million input tokens and $9.00 per million output (audio) tokens through 31 Dec 2026 [https://cloud.google.com/text-to-speech/pricing]. Audio is billed at 25 tokens per second [https://ai.google.dev/gemini-api/docs/pricing]. The nine lines are about 73 s of speech and pauses (sum of shot lengths minus lead-ins and holds), so about 1,800 audio tokens, about $0.016, plus a few cents' fraction for text input: **about $0.02**. This is an estimate: the logs don't record token counts.
- **Addis AI:** 41.4 s of speech is 0.69 min; at the list price I recorded in E1 (about 5 ETB a minute, $0.032) that is about $0.022; I paid 3.45 ETB.
- **GPU:** Google Cloud lists one NVIDIA T4 at $0.35 per hour on demand in Oregon (us-west1) [https://cloud.google.com/products/compute/gpus-pricing]. 3.52 GPU-minutes × $0.35 / 60 = **$0.0205**. Colab was free, so this is a price equivalent, not a payment.
- **FFmpeg and Pillow** run on my own computer: no model cost.

## 4. Totals

| | USD list-price equivalent | What I paid |
|---|---|---|
| Images | 0.0555 | 0 |
| Narration (Gemini, final) | about 0.02 | 0 |
| Narration (Addis AI, first version, not in the film) | about 0.022 | 3.45 ETB |
| Score (T4) | about 0.02 | 0 |
| **Whole film** | **about 0.10** | **3.45 ETB** (the Addis AI version only) |

## 5. Frontier comparison

I had no access to a frontier video or image model (for example Veo or a hosted Wan), so there is no measured comparison and I haven't invented one. The brief asks for a frontier comparison "where available"; here it is not available.