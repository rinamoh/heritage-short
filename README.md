# The Heritage Short: a tribute to my grandmother, "Emaye"

An 88-second vertical film made with open and free-tier AI models: Amharic narration with English subtitles, a generated score, and Ken Burns motion over generated keyframes. The film is a tribute to my grandmother. The family has seen it and approved it, and no real person's face or voice is generated. It is labelled as AI-made on the end card and in the post.

- **Film (vertical 9:16):** `<paste link>`
- **Film (horizontal 16:9):** `<paste link>`
- **Walkthrough (≤ 5 min):** `<paste link>`
- **Public post:** `<paste link>`
- **Report:** `<paste link>`

## Run it: one command

```
python run.py
```

This validates `storyboard.json`, then runs keyframes, narration, music, shots and film, and writes `outputs/final/film_9x16.mp4` and `outputs/final/film_16x9.mp4`. Anything already generated is read from the cache, so on this repository it makes **no model calls** and only rebuilds the video clips and the final edit with FFmpeg. Verified on 26 Nov in a fresh clone with no `.env`: 0 planned Gemini calls, both films written at 87.88 s, −14.0 LUFS. Installed versions in that test: google-genai 3.6.1, Pillow 13.0.0, addisai 0.14.0.

### Set-up (first time only)

1. **Python 3.10 or newer** (tested on 3.14, Windows) and **FFmpeg** (with `ffprobe`) on your PATH. Check with `python --version` and `ffmpeg -version`.
2. Create and activate a virtual environment, then install: `python -m venv .venv`, `.venv\Scripts\Activate.ps1` (Windows) or `source .venv/bin/activate`, then `pip install -r requirements.txt`.
3. Create a file named `.env` in the repository root. It is only needed if you want to regenerate something (an empty cache); the cached run needs no keys:

```
GEMINI_API_KEY=...
CLOUDFLARE_ACCOUNT_ID=...
CLOUDFLARE_API_TOKEN=...
ADDIS_API_KEY=...        # only for --provider addis
```

`.env` is git-ignored. Never commit it.

## Run one stage, or change one shot

```
python run.py --stage keyframes            # all ten keyframes (cached ones are skipped)
python run.py --stage keyframes --shot s04 # one shot
python run.py --stage narration            # one WAV per line; aborts before calling if more than 9 Gemini calls are needed
python run.py --stage shots
python run.py --stage film
python run.py --stage refsheet             # the reference-image options (separate; pick one in storyboard.json)
python run.py --stage keyframes --shot s04 --no-ref   # experiment E5: one shot without the reference image
python -m pipeline.validate                # check storyboard.json against the schema
```

**To change one shot:** edit its `keyframe.prompt` (or a narration line) in `storyboard.json`, then run `python run.py`. Only the changed shot calls a model: its keyframe gets a new cache key, its clip is rebuilt and the film is re-cut. Every other shot is logged as `cache_hit: true` in `runs.jsonl`. Gemini TTS allows only 10 requests a day: see `COSTS.md`.

## What is in the repository

| Path | What it is |
|---|---|
| `storyboard.json` | The single contract: every prompt, seed, narration line, subtitle and timing rule |
| `schema/storyboard.schema.json` | JSON Schema for the storyboard |
| `run.py` | The one command and the stage switches |
| `pipeline/` | `keyframes.py`, `narration.py`, `music.py`, `shots.py`, `assemble.py` (film), `timeline.py`, `validate.py`, and `common/` (config, cache, retry, logging, FFmpeg) |
| `kaggle/music_acestep.ipynb` | The score notebook (ran on a free Colab T4) |
| `outputs/` | Generated and cached files: `refs/`, `keyframes/`, `narration/`, `music/`, `final/` |
| `runs.jsonl` | One line per model or FFmpeg call: time, model, parameters, seed, latency, cost, cache hit, status |
| `AGENTS.md` | The rules the coding agent worked to |

## Documents

| File | Read it for |
|---|---|
| `ARCHITECTURE.md` | How the pipeline works: stages, contract, caching, failures |
| `DESIGN.md` | Audience, storyboard reasons, two listening tests and what they changed |
| `EXPERIMENTS.md` | Eleven experiments with hypothesis, result and decision |
| `FAILURES.md` | Fourteen real blockers and what fixed them |
| `COSTS.md` | Latency, GPU minutes and list-price equivalents per stage |
| `ETHICS.md` | Consent, labelling, licences, what is and is not AI |

## Models used

FLUX.2 klein 4B (Cloudflare Workers AI) for images; Gemini 3.8 Flash TTS (voice Kore) for narration; ACE-Step 1.5 for the score. The motion is FFmpeg Ken Burns; Wan 2.2 is not used. Licences are in `ETHICS.md`.

## Known limits

- The score is generated in a notebook and imported, not by `python run.py`; the repository contains the chosen track.
- Gemini TTS is limited to 10 requests a day, so regenerating all narration needs a full day's quota.
- Some native listeners found the Amharic narration slightly foreign in places (`DESIGN.md`, `EXPERIMENTS.md` E7 and E11).
- Developed and tested on Windows; the end card prefers Arial from `C:/Windows/Fonts`.