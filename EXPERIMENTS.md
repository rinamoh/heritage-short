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

E4: Music: choosing 1 of 3 ACE-Step candidates
Date: 2026-11-26
Where it ran: Google Colab, free T4 GPU (provider colab-t4). The Kaggle notebook never left its queue (FAILURES F11) and Colab first had no free GPU (F12).
Hypothesis: of three seeds with the same caption, the one with the least prominent melody sits best under the narration. (The listening below shows a different quality mattered more: staying consistent over the whole 87.9 s, since the brief says ACE-Step is most stable at 30–60 s.)
Change: seed only (11, 12, 13); same caption, bpm 72, key D minor, duration 87.875 s.
Result: I listened to all three, to the end, against the narration.
Seed 11: the most consistent from start to finish, with a calm, ambient feel that matches a tribute. It fits the narration and the pauses.
Seeds 12 and 13: less consistent. Each lost the tempo it had set up, at points that felt random, and neither matched the calm mood I was aiming for.
The long length did not break seed 11, so the two-part fallback (generate halves, crossfade at s05) wasn't needed.
Evidence: outputs/music/music_11.wav, music_12.wav, music_13.wav; runs.jsonl lines 44 (seed 11), 45 (seed 12) and 46 (seed 13), merged from runs_kaggle.jsonl by music-import. GPU: Tesla T4. Model: ACE-Step 1.5 acestep-v15-turbo + acestep-5Hz-lm-1.7B, 8 inference steps, shift 3.0. Latency per 87.875 s track: 71.19 s (seed 11), 68.55 s (seed 12), 71.27 s (seed 13); GPU minutes 1.186 / 1.143 / 1.188, total 3.52 min for the three. Generated 2026-11-26 about 10:59–11:02 UTC. The imported files are 87.80 s each against a film length of 87.88 s. Judged by me alone at first; after the radio cut with music I sent it to the family group, and their replies, if any, go below.
Family reaction to the radio cut with music: and they said that the sound fits the narration, it was well timed and it fits the amibance and the vibe of the narration.
Decision: seed 11, because it holds its tempo and calm mood for the whole film and sits naturally under the voice. Recorded with python run.py --stage music-import --choose 11 (music.chosen in storyboard.json).

## E5: Choosing one reference image per look

- **Date:** 2026-11-26
- **Hypothesis:** choosing the three references for cross-look consistency (the same build, skin tone and hair at 16, about 18, and in her thirties) gives a more consistent character across shots than choosing each look's best-looking image on its own.
- **Change:** 4 options per look (seeds 1–4), same prompt per look; only the seed varies. Generated at 576×1024 to save free image allowance (references are shrunk below 512 px before use).
- **Result:**
  - **L1 (16, leaving home):** chose **L1_4**, because `because it fits the story and the visual better`.
  - **L2 (student):** chose **L2_1**, because `because it fits the story and the visual better`.
  - **L3 (mother):** chose **L3_4**, because `because it fits the story and the visual better`.
  - Rejected options: `they did not fit the story and the setting`.
- **Evidence:** `outputs/refs/L1_1–4, L2_1–4, L3_1–4.png`; runs.jsonl lines `<refsheet lines>` (Cloudflare FLUX.2 klein 4B, latency per image, ≈ 1,250 neurons for all 12).
- **Decision:** `ref_image` set to L1_4, L2_1, L3_4. Every shot with a look sends its reference as `input_image_0`. E6 tests whether this actually keeps her consistent.