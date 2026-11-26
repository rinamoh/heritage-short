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
- **Result:** s01 now ends as a statement. In Test 2 none of the four family replies and not the friend raised s01, which Test 1 had flagged as sounding like a question. Judged by me and the Test 2 listeners (DESIGN.md).
- **Evidence:** the nine Gemini Flash TTS lines, runs.jsonl lines 20–28 (08:44–08:47 UTC on 26 Nov) (s01 is the first); `outputs/narration/s01_*.wav`.
- **Decision:** keep the style instruction as written (`voice.style` in storyboard.json).
- **Caveat:** the absence of a complaint is weaker evidence than a direct before/after listen.

## E3: Rewording fixes pronunciation and the repetition (s03, s07)

- **Date:** 2026-11-26
- **Hypothesis:** "ወደማታውቀው" is clearer than "የማታውቀው" (s03), and "በየምሽቱ" avoids the repeated-word stutter of "ማታ ማታ" (s07).
- **Change:** text only.
- **Result:** in Test 2 nobody (four family replies, one friend) reported a problem with s03's "ወደማታውቀው" or s07's repeated word, both of which Test 1 had flagged. Judged by the Test 2 listeners (DESIGN.md).
- **Evidence:** the s03 and s07 lines among runs.jsonl lines 20–28; the changed text is in storyboard.json. Unchanged lines stayed cache hits when the text changed, which also showed the cache working.
- **Decision:** keep both rewordings.
- **Caveat:** the same as E2: no complaint is not the same as a direct re-listen.

## E4: Music: choosing 1 of 3 ACE-Step candidates

- **Date:** 2026-11-26
- **Where it ran:** Google Colab, free T4 GPU (provider `colab-t4`). The Kaggle notebook never left its queue (FAILURES F11) and Colab first had no free GPU (F12).
- **Hypothesis:** of three seeds with the same caption, the one with the least prominent melody sits best under the narration. (The listening below shows a different quality mattered more: staying consistent over the whole 87.9 s, since the brief says ACE-Step is most stable at 30–60 s.)
- **Change:** seed only (11, 12, 13); same caption, bpm 72, key D minor, duration 87.875 s.
- **Result:** I listened to all three, to the end, against the narration.
  - **Seed 11:** the most **consistent** from start to finish, with a calm, ambient feel that matches a tribute. It fits the narration and the pauses.
  - **Seeds 12 and 13:** **less consistent**. Each lost the tempo it had set up, at points that felt random, and neither matched the calm mood I was aiming for.
  - The long length did not break seed 11, so the two-part fallback (generate halves, crossfade at s05) wasn't needed.
- **Evidence:** `outputs/music/music_11.wav`, `music_12.wav`, `music_13.wav`; runs.jsonl lines 44 (seed 11), 45 (seed 12) and 46 (seed 13), merged from `runs_kaggle.jsonl` by `music-import`. GPU: Tesla T4. Model: ACE-Step 1.5 `acestep-v15-turbo` + `acestep-5Hz-lm-1.7B`, 8 inference steps, shift 3.0. Latency per 87.875 s track: 71.19 s (seed 11), 68.55 s (seed 12), 71.27 s (seed 13); GPU minutes 1.186 / 1.143 / 1.188, total 3.52 min for the three. Generated 2026-11-26 about 10:59–11:02 UTC. The imported files are 87.80 s each against a film length of 87.88 s. Judged by me alone.
- **Family reaction:** I did not send the radio cut with music to the family; they first heard the music in the near-final cut (Test 2). Their replies are in DESIGN.md, Test 2: none mentioned the score.
- **Decision:** **seed 11**, because it holds its tempo and calm mood for the whole film and sits naturally under the voice. Recorded with `python run.py --stage music-import --choose 11` (`music.chosen` in storyboard.json).

## E5: Four options per look (reference sheet)

> If your repo's EXPERIMENTS.md already has an E5 with your reasons for each choice, keep yours and drop this one.

- **Hypothesis:** generating four options per look and choosing one (the brief's practice, Appendix B) gives a reference that keeps the character recognisably the same person across shots.
- **Change:** four seeds (1–4) per look with the same prompt, so the only difference between options is the seed.
- **Result:** twelve images in `outputs/refs/`. I chose **L1_4, L2_1 and L3_4** by eye (the same woman in all three looks: build, skin tone, hair; age and clothes differ). All ten shot keyframes built on them were accepted without regenerating any.
- **Evidence:** the twelve refsheet calls in runs.jsonl (stage `refsheet`); `outputs/refs/`; `ref_image` fields in storyboard.json.
- **Decision:** use those three as each look's `ref_image`.

## E6: Reference image vs no reference (s04)

- **Date:** 2026-11-26
- **Hypothesis:** the reference image is what keeps the figure consistent. Without it, s04 will drift from the L1 look.
- **Change:** the reference only. s04 was generated with L1_4 as `input_image_0` and again without it, with the same prompt, seed (104), model and size.
- **Result:** without the reference the figure differed from the L1 reference in **three ways: build, clothes and hair, and the cloth bundle**. With it, she stayed recognisably L1.
- **Evidence:** runs.jsonl lines 52 (with reference, key `335ef8af7e0d`) and 59 (no reference, key `14f5a1172e15`); `outputs/keyframes/e5/s04_14f5a1172e15.png` is the no-reference image. The s04 prompt in storyboard.json contains both the old and the new wording, because the retake prompt was appended. Both runs used the same text, so the comparison stays fair.
- **Decision:** keep the reference for every shot with a person. The no-reference file is kept as evidence.
- **Caveat:** one shot, one seed, judged by me.

## E7: Same text, Flash TTS vs Flash Lite TTS on s04 and s06 (Test 2)

- **Date:** 2026-11-26
- **Why:** Test 2: a friend heard s04 (and the first sentence of s06) as a foreigner speaking Amharic. Gemini 3.8 Flash TTS is the narration model the brief's stack table suggests.
- **Planned hypothesis:** an everyday verb (ሄደች for ተጓዘች) would remove the accent. **Not tested:** the storyboard text was never edited.
- **What was tested instead:** model only. Same Amharic text, voice Kore and style as the film; the original Flash audio against new audio from `gemini-3.8-flash-lite-tts` (own 10-a-day quota; the Flash quota was down to one request, F13).
- **Result:** I judged the Lite s04 audio **much better** (single listener: me). Both Lite clips (s04, s06) were about **3 s**, shorter than the Flash lines. I did not check whether they were complete or why they were shorter.
- **Evidence:** runs.jsonl lines 90–91 (stage `narration_e2`, model `gemini-3.8-flash-lite-tts`, latency 5.8 s and 6.2 s; two calls, both the old text; the new-text variant was never run); files in `outputs/narration/e2/`.
- **Decision:** **not used in the film.** Shorter audio would shorten the shots and shift the 87.875 s score against the picture; the pipeline reads one model for all lines, so using Lite for two shots needed code changes; time was short. The original Flash narration stays; the accent is documented as a known weakness. Next time: generate the narration on both models first and choose by ear before building the timeline.
- **Caveat:** one listener and unchecked clip completeness. This is a lead, not a conclusion.

## E8: Narration-driven shot lengths vs planned lengths (Test 1) *(logged afterwards, from work done 26 Nov)*

- **Date:** 2026-11-26
- **Hypothesis:** if each shot lasts as long as its narration plus a short hold, the dead silences that Test 1 listeners heard disappear. Fixed lengths planned before the narration existed (7–10 s per shot) leave 3–5 s of near-silence in each shot.
- **Change:** the timing rule. From fixed per-shot durations to **0.2 s lead-in + the shot's narration + a hold**, computed in `pipeline/timeline.py`. This change was made together with the Test 1 text fixes, so it is not isolated.
- **Result:** before, the spoken lines were 2.6–6.9 s against 7–10 s shots (DESIGN.md Test 1). After, I reported the radio cut v2 as flowing without the silences or cut-offs, and in Test 2 no listener mentioned the pace.
- **Evidence:** DESIGN.md Test 1 (insights and changes); FAILURES F7; `pipeline/timeline.py`; storyboard.json (`hold_after_s`, `duration_s` only on s05).
- **Decision:** narration sets shot length; the brief says the same (Appendix B, "timing the narration first").
- **Caveat:** judged by listeners' comments, not a measurement of pause length.

## E9: Shorten the holds, not the narration, to get under 90 s *(logged afterwards)*

- **Date:** 2026-11-26
- **Hypothesis:** the 97.33 s radio cut can be brought under the brief's 90 s limit by shortening only the holds, with no TTS calls and without trimming any spoken line.
- **Change:** timing constants only: lead-in 0.3 → 0.2 s, default hold 1.2 → 0.6 s, s03 hold 3 → 1.5 s, s10 hold 2.5 → 1.5 s, s05 (planned silence) 5 → 3 s. The same cached narration, re-laid on the new timeline.
- **Result:** **97.33 s → 87.88 s** including the 3 s end card, with zero new Gemini calls (the daily TTS quota is 10).
- **Evidence:** FAILURES F10; runs.jsonl lines 20–28 (nine Gemini lines), with none added by the re-timing (the 87.88 s timeline is line 30).
- **Decision:** keep these holds. s03 and s10 keep the longest holds because the decision and the ending are where the film pauses.
- **Caveat:** several constants changed at once. They were tuned together to reach the limit and were not tested one at a time.

## E10: s04 keyframe re-prompt to put the figure farther away *(logged afterwards)*

- **Date:** 2026-11-26
- **Hypothesis:** adding "extreme wide landscape shot from far away: a tiny distant figure… the road stretching far ahead of her" to the s04 prompt makes her smaller in the frame and walking away, instead of close to the camera.
- **Change:** the s04 `keyframe.prompt` only (same seed 104, model, size and reference). The new wording was appended to the old prompt.
- **Result:** the first image showed her too close to the camera; I regenerated with the added wording and kept that second image among the ten accepted keyframes. Is she now far enough down the road? yes 
- **Evidence:** runs.jsonl s04 keyframe lines: line 43, key `54c0f2b710bc` (first prompt), and line 52, key `335ef8af7e0d` (second prompt, with reference); `outputs/keyframes/`.
- **Decision:** keep the second image. Only s04 regenerated; the other nine keyframes stayed cache hits (this is also the demo for the walkthrough).
- **Caveat:** one shot, one seed, judged by me.

## E11: Blind preference test, Gemini 3.8 Flash TTS vs Addis AI (ceiling work)

- **Date:** 2026-11-26
- **Hypothesis:** native Amharic listeners will prefer Addis AI, because it is an Amharic-specific model and E1 found its pronunciation clearer than Gemini's.
- **Change:** provider only. The same Amharic line(s) from Gemini 3.8 Flash TTS (voice Kore, the film's narration) and from Addis AI (voice `am-hamen`, my first narration), unlabelled, in random A/B order, sent privately to six native Amharic speakers (friends). Lines: Line1_A.wav and Line1_B.wav (s04)
Line2_A.wav and Line2_B.wav (s02).
- **Result:** **3 to 3.** The split follows what each listener paid attention to:
  - **Three preferred Gemini**: it sounded more like a native speaker. They said the Addis clip sounded foreign in places, "like a diaspora speaker".
  - **Three preferred Addis AI**: they liked its tone. It sounded more natural and closer to everyday speech, although they said its **pronunciation and enunciation were flawed**.
- **What it shows:** neither free provider reached native-speaker quality, and each fails differently. Gemini is the better speaker, Addis AI the better tone. This contradicts E1, where I alone judged Addis's pronunciation as more accurate, so one listener was not a safe basis for a decision.
- **Cost and latency:** Gemini was free (free tier, 10 TTS requests a day). Addis AI cost 3.45 ETB for 41.4 s of speech (about 5 ETB a minute, matching its list price); runs.jsonl lines 10–18. Latency: Addis AI 5.0–7.3 s per line (lines 10–18); Gemini Flash 6.74 s for the first call (line 20), the others show about 20–22 s because the logged time includes the 21 s rate-limit wait (FAILURES F14).
- **Evidence:** the six replies (screenshots kept privately; names removed); the clips' source files in outputs/narration/; runs.jsonl lines 10–18 (Addis) and lines 20–28 (Gemini).
- **Decision:** the film stays on **Gemini**. Its listeners' complaint (pronunciation) is the harder one to ignore for a spoken tribute, and Addis's clipped endings (F7) cannot be fixed in the time left. **Next time:** fix Addis's clipped endings, or try Addis's tone with Gemini's pronunciation.
- **Caveat:** six listeners, all friends of mine, so this is a small sample and not a measurement of preference in general.