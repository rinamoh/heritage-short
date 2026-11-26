# ARCHITECTURE.md

How the Heritage Short pipeline is built: stages, the contract between them, caching, and what happens when a model or a quota fails. Evidence for each claim is in brackets: `AGENTS.md` (the rules the code is written to), `F<n>` (FAILURES.md), `E<n>` (EXPERIMENTS.md), or `runs.jsonl`.

## 1. The idea in one paragraph

One file, `storyboard.json`, says everything the film needs: audience, style block, the character's three looks, ten shots (picture prompt, seed, narration text, English subtitles, motion), the voice, and the music brief. Every stage reads it and writes files into `outputs/<stage>/`. Nothing is hard-coded in a stage: prompts, seeds and text live in the storyboard, so a run can be reproduced and one shot can be changed alone [AGENTS.md "Structure"]. The one command is `python run.py`; `python run.py --stage <name>` runs a single stage.

```
storyboard.json  --validate-->  schema/storyboard.schema.json
      |
      +--> keyframes  (Cloudflare FLUX.2 klein 4B)  --> outputs/refs/, outputs/keyframes/
      +--> narration  (Gemini 3.8 Flash TTS, Kore)  --> outputs/narration/*.wav, durations.json
      +--> timeline   (shared code: shot lengths, subtitle cue times)
      +--> music-plan / music-import  (ACE-Step on Colab, run off-machine) --> outputs/music/
      +--> shots      (FFmpeg Ken Burns over each keyframe)  --> outputs/shots/
      +--> film       (FFmpeg: cut, dissolve, duck, subtitles, end card, loudnorm)
                                                        --> outputs/final/film_9x16.mp4, film_16x9.mp4
every model call --> runs.jsonl (one JSON line)
```

## 2. The contract: `storyboard.json` + JSON Schema

- **Top level:** `title`, `audience`, `intent`, `language`, `style_block`, `character` (`base` description and `looks[]` L1, L2, L3 with `ref_image`), `voice` (`provider`, `model`, `name`, `style`, `settings`), `music` (`caption`, `bpm`, `key`, `duration_s`, `instrumental`, `seeds`, `cues[]`, `chosen`), `output` (`fps`, `ratios`, `end_card_s`), `shots[]`.
- **Per shot:** `id`, `beat`, `reason` (why the shot exists), `shot_size`, `look` (L1/L2/L3 or null), `narration.segments[].text_am`, `subtitle_en` (cues of at most two lines), `keyframe` (`prompt`, `seed`), `motion` (`method`, `prompt`, `seed`, `kb_direction`), and for silent shots `duration_s`; `hold_after_s` where the default hold is overridden (s03, s10).
- **Validation:** `python -m pipeline.validate` checks the file against `schema/storyboard.schema.json` and then domain rules (for example, silent shots must have `duration_s`). It runs before every stage, so a bad storyboard stops the run before any model call [AGENTS.md "Structure"; runs seen: "VALID: storyboard.json passed schema and domain checks (10 shots…)"].
- **Why one contract:** it is what lets a stage be rerun alone, and it is what the walkthrough changes live (one keyframe prompt) to show that only that shot regenerates.
- **Derived, not typed:** shot start times, shot lengths, subtitle times and the music cue times are computed by `pipeline/timeline.py` from the narration lengths, so they cannot go stale when a line changes. The cue times printed in the storyboard come from `run.py --stage music-plan` [F10; DESIGN.md "Music spotting"].

## 3. Stages: input, output, provider

| Stage | Reads | Writes | Provider and model |
|---|---|---|---|
| validate | `storyboard.json`, schema | nothing (stops on error) | local |
| keyframes (refs, then shots) | `style_block`, `character`, `shots[].keyframe`, the look's reference image | `outputs/refs/L1_4.png`, `L2_1.png`, `L3_4.png` (chosen from 4 options each); `outputs/keyframes/<shot>_<key12>.png` (1088×1920) | Cloudflare Workers AI, FLUX.2 klein 4B. Reference passed as `input_image_0`, shrunk to fit the endpoint's 512×512 limit [AGENTS.md "Provider specifics"; E5] |
| narration | `voice`, `narration.segments`, style | one WAV per segment (24 kHz mono), `durations.json` (lengths, `clipped_end`) | Gemini 3.8 Flash TTS, voice Kore, style in `speech_metadata.style`, v1beta client [F4; AGENTS.md] |
| music-plan | timeline, `music` | printed cue block for the notebook | local |
| music (off-machine) | caption, bpm, key, duration, seeds 11/12/13 | `music_11.wav`, `music_12.wav`, `music_13.wav`, `runs_kaggle.jsonl` | ACE-Step 1.5 (`acestep-v15-turbo`, `acestep-5Hz-lm-1.7B`, 8 steps, shift 3.0) on a free Google Colab T4, provider tag `colab-t4` [E4; F11; F12] |
| music-import | the three WAVs, `runs_kaggle.jsonl` | merges the notebook's log lines into `runs.jsonl` without duplicates; checks lengths; sets `music.chosen` (11) | local |
| shots | keyframes, `motion` | `outputs/shots/<shot>.mp4`: slow pan and zoom, zoom at most 1.12×, direction from `kb_direction`, image upscaled first to avoid jitter | FFmpeg (zoompan) |
| film | shots, narration, chosen music, subtitles | `outputs/final/film_9x16.mp4` and `film_16x9.mp4` | FFmpeg, Pillow (end card) |

**Why music runs off-machine:** ACE-Step needs a GPU the developer's laptop does not have, so the notebook (`kaggle/music_acestep.ipynb`, written to run on Kaggle or Colab) produces files and a log, and `music-import` brings them home. The pipeline treats the three WAVs as inputs it can verify rather than outputs it can regenerate; the film uses whichever seed `music.chosen` names.

### The film stage in detail
- **Timeline:** each shot lasts 0.2 s lead-in + its narration + a hold (0.6 s default; 1.5 s for s03 and s10; s05 is 3 s of planned silence). The film is **87.88 s** including the 3 s end card, inside the 60–90 s limit. The radio stage warns when the total leaves that range [F10; AGENTS.md rule 0].
- **Picture:** each keyframe becomes a Ken Burns clip, joined with 0.5 s dissolves. The dissolve overlap is compensated so narration still starts where the timeline says.
- **Sound:** the voice is the spine. Music is ducked with `sidechaincompress` (threshold 0.02, ratio 6, attack 300 ms, release 1500 ms: the brief's starting values), with the voice split by `asplit` and mixed back with `amix normalize=0` so it stays audible. Music level 0.2, fading out over the last 3 s. Final loudness: two-pass `loudnorm` to −14 LUFS, true peak −1 dB; the test export measured −13.9 LUFS and −1.9 dBTP [AGENTS.md "Provider specifics"; assembly report of 26 Nov].
- **Subtitles:** the SRT is built from the narration segments' real timing (silence detection finds the actual pauses in s08 and s10), burned in at most two lines, clear of the bottom 15% of the vertical frame.
- **End card:** 3 s, drawn in code, "Made with AI" and the models used, present in both exports.
- **Two ratios from one pass:** 9:16 is the primary; 16:9 places the same picture over a blurred enlargement of itself, so no second set of keyframes is needed. Both are H.264 + AAC at 24 fps and under 100 MB.

## 4. Caching: a re-run regenerates only what changed

- **Key:** `sha256` of the JSON of every input that changes the output: model, prompt, seed, size, parameters, and the sha256 of any input file (the look's reference image for keyframes). The file is named `<shot_id>_<key[:12]>.<ext>` [AGENTS.md rule 2].
- **Behaviour:** if that file exists, the stage skips the call and logs `cache_hit: true`. If not, it calls the model and logs the call.
- **What this means in practice:**
  - Changing one shot's keyframe prompt changes only that shot's key. s04 passed through three keys while it was being tuned (`54c0f2b710bc`, `335ef8af7e0d`, `14f5a1172e15`), each a separate file; the other nine shots stayed cache hits [runs.jsonl; E6].
  - Narration is cached per segment. Re-laying the existing narration on a new timing rule cost **zero** TTS calls and took the film from 97.33 s to 87.88 s [F10].
  - Changing the voice or its settings re-records every segment, because one voice must cover the whole film (a mixed-voice film is rejected as a rule).
  - To redo a line without changing its text, delete its WAV; otherwise the cache returns the same file.
- **Cheap stages are rebuilt, not cached:** Ken Burns clips and the final edit are made by FFmpeg from cached files with no model call and no quota.
- **Why caching is a hard requirement here:** Gemini TTS allows 10 requests a day and a full narration pass is 9; Cloudflare gives a daily neuron allowance (about 318 neurons per 1088×1920 keyframe, derived from runs.jsonl `cost_usd_equiv` at $0.011 per 1,000 neurons, against 10,000 free per day). A pipeline that regenerates everything cannot be run twice in a day [F3; F13].

## 5. Logging: `runs.jsonl`

Every model call goes through one function, `log.log_call()`, which appends one JSON line: `ts` (UTC), `stage`, `shot_id`, `provider`, `model`, `params`, `seed`, `latency_s`, `cost_usd_equiv`, `cache_hit`, `status`, `error` [AGENTS.md rule 1]. Cache hits are logged too. The Colab notebook writes its own log (`runs_kaggle.jsonl`) with GPU seconds, and `music-import` merges it, so the music appears in the same file [E4: lines 44–46]. `COSTS.md` is computed from this file.

## 6. Failure handling

| Failure | What the pipeline does | Evidence |
|---|---|---|
| Transient error (timeout, 5xx) | Up to 3 attempts with 2 s, 4 s, 8 s backoff; after the last, the stage returns a failed result and uses its fallback. One failed shot never crashes the run | AGENTS.md rule 3 |
| **Daily quota (HTTP 429)** | **Never retried**: one request, then a clean stop with a log line. The Gemini SDK retries 429s four times by default, so the pipeline sets `retry_options attempts=1` | F9 |
| Quota guard | The narration stage aborts above 9 Gemini calls in a run and waits 21 s between calls (3 per minute) | narration report of 26 Nov; AGENTS.md |
| Model returns a clipped sentence | `check_clipped_end` measures the last 30 ms of every WAV (above −45 dBFS means cut off). It caught Addis AI's cut-off endings, which led to the provider switch | F7, F8, E1 revision |
| Output too long | The radio stage prints the total and warns outside 60–90 s; holds, not narration, are what get shortened | F10 |
| Stale audio | `build_timeline` stops if a WAV no longer matches the storyboard text | narration report of 26 Nov |
| GPU unavailable | The music job is separate from the pipeline; when Kaggle never left its queue it ran on Colab with the same notebook; the pipeline only needs the imported files | F11, F12 |
| Moving-video model unavailable | Every shot has a Ken Burns fallback (`motion.method: kenburns`); the film does not depend on a GPU | F11, F12; brief, "The path" |
| Wrong model/API shape | Known-bad choices are written into AGENTS.md so the coding agent cannot reintroduce them (v1beta client; no `gemini-2.5-flash-preview-tts`; one Gemini key only) | F4, F5 |
| Coding agent quota | Long pipeline commands are run by the developer; the agent only writes code | F6 |

## 7. Secrets and safety

API keys are read only from `.env` through `config.py`; they are never printed or logged, and `.env` is in `.gitignore` [AGENTS.md rule 4]. One Gemini key is used; no code rotates keys or projects to get around a quota [plan decision table; AGENTS.md]. Consent and licences are in `ETHICS.md`.

## 8. Limitations, stated plainly

- **No generated motion.** The film uses Ken Burns moves over keyframes. Wan 2.2 image-to-video was not run: the T4 has 16 GB and the official command expects 24 GB; GPU access was already the project's scarcest resource (Kaggle never started, F11; Colab first had no GPU, F12); and the brief accepts a slow pan and zoom as a fallback. The family reaction to the Ken Burns film (DESIGN.md, Test 2) did not ask for motion. The storyboard already allows `motion.method: "wan"` and the plan describes a jobs export for it, but that path was never run, so it is untested.
- **Music is not regenerated by `python run.py`.** It is generated in a notebook and imported. A clean clone uses the committed WAV for the chosen seed.
- **A clean clone with an empty cache needs three keys and about a day of quota:** nine Gemini TTS requests (the whole daily allowance of 10) plus Cloudflare keyframes. With the committed `outputs/` it makes no model calls.
- **One voice, one provider per pass.** The narration is a stock synthetic voice with a style instruction, not a native speaker; native listeners found two places where it sounds foreign (DESIGN.md, Test 2; F13).
- **Quota timing is Google's, not ours.** Daily quotas reset at midnight Pacific time (08:00 UTC in November), which is 11:00 in East Africa.