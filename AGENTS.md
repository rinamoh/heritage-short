# AGENTS.md: rules for the coding agent

## Project
Heritage Short: turns storyboard.json into a 60–90 s vertical + horizontal film,
Amharic narration, English subtitles, ducked original score, AI end card.
The challenge brief is the source of truth; docs/references.md has supporting research.
Developer machine: Windows, PowerShell. Use pathlib for every path. No bash-only commands.

## Read first
- DESIGN.md: the story, audience, intent, the three looks, shot plan and narration. It explains WHY.
- storyboard.json: the machine-readable version of that plan. It decides WHAT gets generated.
- ETHICS.md: consent and licences. Never change it and never generate anything that contradicts it.

## Structure (do not invent other layouts)
- storyboard.json: THE contract. Every stage reads it. Never hard-code prompts, seeds or text.
- schema/storyboard.schema.json: validated before every run (python -m pipeline.validate).
- pipeline/common/: config.py (reads .env), log.py (runs.jsonl), cache.py, retry.py.
- pipeline/<stage>.py: keyframes, narration, shots, assemble. One stage per file.
- run.py: the one command. `python run.py` runs everything; `--stage X` runs one stage;
  `--export-kaggle-jobs` writes kaggle/jobs/.
- outputs/<stage>/: generated files, named by cache key.

## Character model
- character.base: description shared by every look (same woman: build, skin tone, hair).
- character.looks[]: id (L1, L2, L3), stage, clothing, carries, ref_image.
- Each shot has "look": one of the look ids, or null for shots with no person.
- She is never shown with a clear face: from behind, silhouette, or distance.
  Every person prompt must include "seen from behind, face not visible".

## Rules
1. Every model call goes through log.log_call() → one JSON line in runs.jsonl:
   ts (UTC ISO), stage, shot_id, provider, model, params, seed, latency_s,
   cost_usd_equiv, cache_hit, status, error.
2. Cache key = sha256 of the JSON of every input that affects the output (model, prompt,
   seed, params, sha256 of input files). File name = <shot_id>_<key[:12]>.<ext>.
   If the file exists: skip the call, log cache_hit=true.
3. Retries: 3 attempts with backoff (2 s, 4 s, 8 s). After the last failure, return a failed
   result; the stage uses its fallback. One failed shot never crashes the run.
4. Secrets only from .env via config.py. Never print or log keys.
5. datetime.now(timezone.utc). Type hints. Small functions. Plain synchronous code.

## Provider specifics (current as of Nov 2026: follow these, not memory)
- Gemini models available on this key (free tier): gemini-3.8-flash (text, 20 requests/day), gemini-3.8-flash-tts and
  gemini-3.8-flash-lite-tts (10 requests/day each, 3/min). gemini-3.8-flash-lite (text) is NOT available.
  ALWAYS create the client with genai.Client(api_key=..., http_options={"api_version": "v1beta"}): TTS returns 404 without it.
  Do NOT use gemini-2.5-flash-preview-tts: it rejects speech_metadata style annotations (400).
  Use exactly one Gemini API key. Never add key-rotation or multi-project logic (Google API terms §2(d)).
  The narration provider, model and voice are read from storyboard.json (voice.provider/model/name).
  Never retry a 429 quota error; retry only timeouts and 5xx. Wait at least 21 s between Gemini TTS calls.
- Addis AI TTS (Amharic): `pip install addisai`; `from addisai import AddisAI`; `AddisAI()` reads ADDIS_API_KEY.
  clip = client.voice.generate(voice_id=..., text=..., language="am", output_format="wav_44100",
  voice_settings={"speed":..,"stability":..,"similarity":..,"style":..}); clip.to_file(path); log clip.usage
  (credits_used, currency) as cost. List voices with client.voices.list(language="am"). Errors:
  InsufficientCreditsError, RateLimitError, APIError. One narration pass uses one provider and one voice; never mix.
- Gemini TTS: google-genai >= 2.25.0, client.interactions.create(model=VOICE_MODEL,
  input=[{"type":"user_input","content":[{"type":"text","text":TEXT,
  "annotations":[{"type":"speech_metadata","style":STYLE}]}]}],
  response_format={"type":"audio"},
  generation_config={"speech_config":[{"voice":VOICE}]}).
  Output: base64 WAV, 24 kHz mono 16-bit. The text is spoken verbatim; style goes only in
  speech_metadata.style. Language is detected from the text (Amharic is supported).
  If this call shape errors, read https://ai.google.dev/gemini-api/docs/speech-generation
  and log the difference in FAILURES.md.
- Cloudflare FLUX.2 klein 4B: POST
  https://api.cloudflare.com/client/v4/accounts/{ACCOUNT}/ai/run/@cf/black-forest-labs/flux-2-klein-4b
  Header: Authorization: Bearer {TOKEN}. Body: multipart/form-data with prompt and optional
  input_image_0..input_image_3 (binary images, each smaller than 512x512). Response: base64 image.
- FFmpeg: loudnorm MUST set I=-14:TP=-1 (defaults are -24/-2). Ducking with sidechaincompress
  MUST asplit the voice and amix it back with normalize=0. Use xfade for crossfades.
  H.264 + AAC, constant 24 fps, even dimensions. For the subtitles filter on Windows, run
  ffmpeg with cwd set to the SRT's folder and pass only the file name.
- Wan 2.2 TI2V-5B sizes: 1280*704 or 704*1280 (not 720). Image-to-video aspect follows the image.

## Working agreement with the developer
- Before a change that touches more than 2 files, state the plan in 3–5 bullets, then proceed.
- After writing code, summarise in plain English what each new file and function does.
- Python runs from the project venv (.venv). Any new package goes into requirements.txt.
- Never edit DESIGN.md, ETHICS.md or .env. The developer owns them.
- Never run `git commit` or `git push`. The developer reviews the changes and commits.
- When something fails, print the exact error and suggest a FAILURES.md entry:
  "## F<n>: <title>" with What broke / What I tried / What fixed it.
- When an experiment is run, suggest an EXPERIMENTS.md entry:
  Hypothesis / Change / Result / Evidence (runs.jsonl line numbers) / Decision.