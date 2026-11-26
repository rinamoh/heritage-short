# ARCHITECTURE.md

How the Heritage Short pipeline is built: stages, the contract between them, caching, and what happens when a model or a quota fails. Checked against the code (`run.py`, `pipeline/*.py`) and `runs.jsonl` on 26 November 2026. Evidence is in brackets: a file and function, a `runs.jsonl` line number, `F<n>` (FAILURES.md) or `E<n>` (EXPERIMENTS.md).

## 1. The idea in one paragraph

One file, `storyboard.json`, says everything the film needs: audience, style block, the character's three looks, ten shots (picture prompt, seed, narration text, English subtitles, motion), the voice, and the music brief. Every stage reads it and writes files into `outputs/<stage>/`. Prompts, seeds and text live in the storyboard, not in code, so a run can be reproduced and one shot can be changed alone. The one command is `python run.py`; `python run.py --stage <name>` runs a single stage.

```
storyboard.json --validate--> schema/storyboard.schema.json   (before every command)
   |
   +-> keyframes  Cloudflare FLUX.2 klein 4B    -> outputs/refs/, outputs/keyframes/
   +-> narration  Gemini 3.8 Flash TTS, Kore    -> outputs/narration/*.wav + durations.json
   +-> music      ACE-Step on Colab (off-machine) -> outputs/music/music_<seed>.wav (imported)
   +-> shots      FFmpeg Ken Burns              -> outputs/shots/<shot>_<key>.mp4
   +-> film       FFmpeg                        -> outputs/final/film_9x16.mp4, film_16x9.mp4
timeline.py (shared): shot lengths, subtitle times, music cue times, from the real narration
every model or FFmpeg call -> runs.jsonl (one JSON line)
```

`python run.py` runs: validate, keyframes, narration, music (reuses the chosen cached score), shots, film, and stops at the first incomplete step [`run.py: run_full_pipeline`]. Separate stages: `refsheet`, `radio` (narration over a pad: the Test 1 cut), `music-plan`, `music-import`.

## 2. The contract: `storyboard.json` + JSON Schema

- **Top level:** `title`, `audience`, `intent`, `language`, `style_block`, `no_text_suffix`, `character` (`base`, `shot_suffix`, `refsheet`, `looks[]` L1, L2, L3, each with a `ref_image`), `voice`, `music` (`caption`, `bpm`, `key`, `duration_s`, `instrumental`, `seeds`, `cues[]`, `chosen`), `output` (`fps`, `ratios`, `end_card_s`, `end_card`), `shots[]`.
- **Per shot:** `id`, `beat`, `reason` (why the shot exists), `shot_size`, `look`, `narration.segments[].text_am`, `subtitle_en`, `keyframe` (`prompt`, `seed`), `motion` (`method`, `kb_direction`); optional `hold_after_s` (s03, s10) and `duration_s` (s05).
- **Validation:** `pipeline/validate.py` checks the file against the JSON Schema (draft 2020-12), then domain rules: every shot's `look` exists, subtitle lines are at most 42 characters, shot ids are unique, silent shots have `duration_s`. A bad storyboard stops the run before any model call.
- **Derived, not typed:** shot lengths, subtitle times and music cue times are computed by `timeline.py` from the narration, so they can't go stale when a line changes [F10].
- **Why one contract:** one stage can run alone, and the walkthrough changes one keyframe prompt to show only that shot regenerates.

## 3. Stages: input, output, provider

| Stage | Writes | Provider and model |
|---|---|---|
| refsheet | `outputs/refs/<look>_<seed>.png`, 576×1024, 12 options | Cloudflare Workers AI, FLUX.2 klein 4B |
| keyframes | `outputs/keyframes/<shot>_<key12>.png`, 1088×1920, `index.json` | same; the look's reference is shrunk to 287×511 and sent as `input_image_0` |
| narration | `outputs/narration/<shot>_<key12>.wav`, `durations.json` | Gemini 3.8 Flash TTS, voice Kore (v1beta client). Addis AI path: `--provider addis` [F4] |
| music (off-machine) | `music_11/12/13.wav`, `runs_kaggle.jsonl` | ACE-Step 1.5 on a free Colab T4 [F11, F12] |
| music-import | merges the notebook log into `runs.jsonl`, sets `music.chosen` | local |
| shots | `outputs/shots/<shot>_<key12>.mp4` | FFmpeg zoompan |
| film | `outputs/final/film_9x16.mp4`, `film_16x9.mp4` | FFmpeg, Pillow (end card) |

ACE-Step needs a GPU the laptop lacks, so it runs in a notebook and `music-import` brings the files home. In a full run the music step only checks that the chosen WAV exists and logs a cache hit; it raises a clear error if not [`music.check_cached_music`].

**Timing rule** [`timeline.py`]: a narrated shot lasts `max(0.2 s + pauses + narration + hold, minimum)`, rounded up to a frame. Hold 0.6 s (1.5 s on s03, s10); minimum 3.0 s. Total 84.876 s + 3 s end card = **87.88 s** [`runs.jsonl` line 30]. The film stage warns outside 60–90 s.

**Shots.** The keyframe is upscaled 4× before zoompan so whole-pixel steps are invisible; zoom is capped at 1.12×; each clip runs 0.5 s past its shot so a dissolve doesn't shift the next shot. A Wan path exists in `shots.py` (a clip at `outputs/shots/wan/<shot>_<key>.mp4` is used if present, else `[FALLBACK]` to Ken Burns) and the end card's "Motion: Wan 2.2" line appears only if a Wan clip was used. **Wan was never run, and the repository has no code that makes a Wan clip**: `run.py --export-kaggle-jobs` is a stub that prints "not implemented yet".

**Film stage** [`assemble.py`]: dissolved join, then the 3 s end card. Narration on the timeline; score at 0.2 volume, faded out, ducked by `sidechaincompress` (threshold 0.02, ratio 6, attack 300 ms, release 1500 ms) with `asplit` + `amix normalize=0`. Two-pass `loudnorm` to −14 LUFS, −1 dBTP: pass 1 measured the mix at −15.43 LUFS (`runs.jsonl` lines 84–85), pass 2 ran in linear mode, and the exported films measure −14.0 LUFS with a true peak of −2.3 dBTP (the clean-clone run, §4). Subtitles from the real timing, burned in with libass (9:16 size 8, margin 54 ≈ 19% above bottom edge). 16:9 centres the 608×1080 picture over a blurred, enlarged copy. Both are H.264 CRF 18 + AAC 192 kbit/s, 24 fps constant (lines 86–87). The end card uses `C:/Windows/Fonts/arial.ttf` if present, else Pillow's default font.

## 4. Caching: a re-run regenerates only what changed

- **Key:** SHA-256 of JSON of model, prompt, seed, params and the SHA-256 of every input file [`common/cache.py`]; files are `<shot>_<key[:12]>.<ext>`.
  - Keyframes: prompt, seed, width, height, reference size cap and **the reference image's hash** [`keyframes.job_cache_key`].
  - Narration: text, model, provider, voice, style, settings, language [`narration.build_segment_key`]. A changed voice regenerates every line.
- If the file exists, the stage skips the call and logs `cache_hit: true`.
- **Clean-clone check (26 Nov, Windows, Python 3.14):** `python run.py` in a fresh clone without `.env` printed ten `[CACHED]` keyframes, `Planned Gemini TTS calls: 0`, nine `[CACHE]` narration lines, `[CACHED] music`, and then rebuilt the ten clips with FFmpeg (`outputs/shots/` is git-ignored, so the first run in a clone shows `[OK]`) and wrote both 87.88 s films. No model was called.
- **Evidence:** second `shots` run on the original machine: ten cache hits (lines 70–79); the narration re-laid on a new timing rule made **zero** TTS calls and cut the film from 97.33 s to 87.88 s (lines 29–30; F10). s04 passed through three keys while tuned (`54c0f2b710bc` line 43, `335ef8af7e0d` line 52, `14f5a1172e15` line 59); each is a separate file and `index.json` records the current one. Reference options whose inputs change are renamed `*_old_<key>.png` [`keyframes._set_aside_stale`].
- **Why it's required:** Gemini TTS allows 10 requests a day and a full pass is 9 [F13]; Cloudflare's free allowance is 10,000 neurons a day [COSTS.md].

## 5. Logging: `runs.jsonl`

Every model call and FFmpeg step goes through `log.log_call()`, appending one line: `ts` (UTC), `stage`, `shot_id`, `provider`, `model`, `params`, `seed`, `latency_s`, `cost_usd_equiv`, `cache_hit`, `status`, `error`. Cache hits are logged. Cloudflare errors have the account id and token masked. The Colab notebook writes the same fields plus `gpu_minutes`, merged by `music-import` (lines 44–46). **Known limit:** for Gemini TTS, `latency_s` includes the 21 s rate-limit wait inside the timed call, so only the first call shows true latency (line 20: 6.74 s; the rest ≈ 20–22 s) [F14].

## 6. Failure handling

| Failure | What the code does | Evidence |
|---|---|---|
| Timeout / 5xx | up to 3 attempts, 2 s, 4 s, 8 s backoff; then a failed result is returned, not an exception, so one bad shot doesn't crash the run | `common/retry.py` |
| **Quota (429)** | **never retried.** Cloudflare: `[STOP]`, finished images stay cached. Gemini: stop and list missing segments. The Gemini client uses `retry_options attempts=1` because the SDK would silently resend 429s | `retry.py`; `narration.GEMINI_HTTP_OPTIONS`; F9 |
| Too many Gemini calls | counts the segments to generate before any call; aborts above 9 (`--allow-calls N` overrides); calls kept 21 s apart | `narration.guard_gemini_calls` |
| Cut-off sentence | measures the last 30 ms of every WAV against −45 dBFS, logs `clipped_end`; caught Addis AI's clipped endings; all nine Gemini lines are `false` | F7, F8; lines 20–28 |
| Film length | warns outside 60–90 s | F10 |
| Missing keyframe / score | clear message naming the stage to run | `keyframes.py`, `music.py` |
| No GPU | music is outside the pipeline; Kaggle never started so the same notebook ran on Colab | F11, F12 |
| No video model | every shot falls back to Ken Burns | `shots.render_shots` |
| Wrong API shape | known-bad choices written into AGENTS.md | F4, F5 |

## 7. Secrets and safety

Keys are read only from `.env` via `common/config.py`; `.env` is git-ignored; keys are never printed or logged. One Gemini key, no rotation to dodge a quota. Reference images must be generated files inside `outputs/refs/`, so a family photograph can't be sent by mistake [`keyframes.reference_path`]. Consent and licences: ETHICS.md.

## 8. Limitations

- **No generated motion.** Ken Burns over keyframes only; Wan 2.2 was not run (T4 has 16 GB, GPU access was scarce, the brief accepts Ken Burns, F11/F12).
- **Music isn't regenerated by `python run.py`.** It is made in a notebook and imported; a clean clone uses the committed WAV.
- **An empty cache needs about a day of quota:** nine Gemini TTS requests (of 10/day) plus Cloudflare keyframes. With the committed `outputs/` it makes no model calls.
- **Developed on Windows** (end-card font path).
- **One voice.** Native listeners found Gemini's Amharic foreign in places; six listeners split 3–3 with Addis AI [DESIGN Test 2; E7; E11].
- **Quota timing is Google's:** Gemini daily quotas reset at midnight Pacific (08:00 UTC = 11:00 EAT in November); Cloudflare's at 00:00 UTC [Cloudflare pricing page].