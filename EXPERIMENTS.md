# EXPERIMENTS.md

> Each entry: **Hypothesis / Change / Result / Evidence / Decision.** Change one thing at a time; keep everything else fixed.

## E1: Narration provider (Gemini vs Addis AI)

- **Date:** 2026-11-26
- **Hypothesis:** an Amharic-specific TTS model (Addis AI, አሌፍ-Audio-AM) pronounces Amharic more accurately than a general multilingual model (Gemini 3.8 Flash Lite TTS).
- **Change:** provider only. The same short Amharic sentence was sent to both providers.
- **Result:**
  - **Addis AI** (`am-hamen`): clearer enunciation and more accurate pronunciation; the tone was more **formal**.
  - **Gemini** (Flash Lite TTS): clear and understandable, with a **looser, more conversational** tone.
- **Evidence:** `outputs/narration/smoke_addis.wav` vs `outputs/narration/smoke_gemini.wav`; runs.jsonl lines 9 (Addis AI: 8.96 s latency, 0.198 ETB for 2.38 s of audio) and 6 (Gemini Lite TTS: 5.62 s latency, free tier) (latency, and Addis `credits_used`).
- **Decision (v1):** **Addis AI** narrates the film. Mispronunciation is the TTS failure the brief warns about most (names, places), and tone can be adjusted with settings; pronunciation can't. E2 tests whether Addis AI's `speed` / `style` settings make the delivery warmer.

- **Revision after Test 1 (2026-11-26):** Addis AI's narration **clipped final consonants** (s03 ends mid-"ች", F7) and has no plain-language style control, while Test 1 needed a wistful, falling delivery for s01. Fixing the clipping needed several probe runs (format, trailing text) with no guarantee. **Revised decision: Gemini 3.8 Flash TTS** (voice Kore) with a style instruction. Its smoke sample was clear and unclipped (runs.jsonl line 6), and the style field addresses the tone feedback directly. Addis AI stays as a candidate for a later comparison (ceiling benchmark).

## E2: Style instruction fixes s01's question-like ending

- **Date:** 2026-11-26
- **Why:** Test 1: s01 "sounds like a question"; it should be wistful and contemplative, and land as a statement.
- **Hypothesis:** with the same voice (Kore), a style instruction that asks for a falling, settled end on every sentence turns s01 into a statement.
- **Change:** style only. v1 was Addis AI (no style); v2 is Gemini with the style in DESIGN.md.
- **Result:** `<does s01 now end as a statement? who judged it>`
- **Evidence:** runs.jsonl lines `<…>`; outputs/narration/s01_*.wav
- **Decision:** `<keep / adjust style wording>`

## E3: Rewording fixes pronunciation and the repetition (s03, s07)

- **Date:** 2026-11-26
- **Hypothesis:** "ወደማታውቀው" is clearer than "የማታውቀው" (s03), and "በየምሽቱ" avoids the repeated-word stutter of "ማታ ማታ" (s07).
- **Change:** text only.
- **Result:** `<clear / unclear per line; who judged it>`
- **Evidence:** runs.jsonl lines `<…>`
- **Decision:** `<…>`

## E4: Music: choosing 1 of 3 ACE-Step candidates

- **Hypothesis:** of three seeds with the same caption, the one with the least prominent melody sits best under the narration.
- **Change:** seed only (11, 12, 13); same caption, bpm, key, duration.
- **Result:** `<per candidate: texture, does it fight the voice?, does the motif return?>`
- **Evidence:** runs_kaggle.jsonl lines `<…>`, GPU name, latency, GPU minutes
- **Decision:** `<seed>`, because `<…>`