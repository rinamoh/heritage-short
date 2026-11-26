# FAILURES.md

>  Real blockers met while building this pipeline: what broke, what I tried, what fixed it.

## F1: Antigravity CLI installer showed no progress

- **Date:** 2026-11-25
- **Stage:** setup (task 0.5, installing the coding agent)
- **What broke:** `irm https://antigravity.google/cli/install.ps1 | iex` ran in the VS Code terminal with no output and no progress for `<several minutes>`.
- **What I tried:**
  1. `Invoke-WebRequest -Uri "https://antigravity.google" -UseBasicParsing -TimeoutSec 10` returned `200 OK`. That showed the site was reachable, but not that the install script itself had downloaded or what it was doing.
  2. Split "download" from "run" so each step's output could be seen: `just waited>`.
- **What fixed it:** the installer finished and printed:
  ` Antigravity CLI binary placed successfully at C:\Users\LENOVO\AppData\Local\agy\bin\agy.exe`,
  plus a warning that this folder was not on the active PATH (this led to F2).
- **Lesson:** `irm … | iex` downloads and runs a script in one step, so a silent hang doesn't tell you which part is stuck. Downloading to a file first lets you read the script and see its output.

## F2: `agy` "not recognized" after a successful install

- **Date:** 2026-11-25
- **Stage:** setup (task 0.5)
- **What broke:** after the install, `agy ==version` gave:
  `agy : The term 'agy' is not recognized as the name of a cmdlet, function, script file, or operable program.`
- **Cause (two parts):**
  1. **Stale PATH.** Windows finds commands by searching the folders on PATH. The installer saved `C:\Users\LENOVO\AppData\Local\agy\bin` to my user PATH, but a terminal reads PATH only once, when it starts. VS Code's terminals inherit their PATH from the VS Code process, so even a new terminal tab still had the old list.
  2. **Typo:** `==version` instead of `--version`. This wasn't the cause of the error (Windows never found `agy`), but it would have failed next.
- **What I tried:**
  1. Checked the saved user PATH: `[Environment]::GetEnvironmentVariable("Path","User") -split ";" | Select-String "agy"`. It printed the agy folder, so the installer had already saved it and no manual PATH edit was needed.
- **What fixed it:** closed **all** VS Code windows, reopened VS Code, opened a new terminal, and ran `agy --version`, which worked.
- **Lesson:** after installing a command-line tool on Windows, restart the whole app the terminal lives in (VS Code), not just the terminal tab.

## F3: Planned Gemini text model not available on the free tier

- **Date:** 2026-11-25
- **Stage:** setup (task 0.8, checking free-tier limits)
- **What broke:** the plan, following the brief's stack table, used `gemini-3.8-flash-lite` (Flash-Lite) for bulk text calls. That model wasn't available for this API key in AI Studio.
- **What I found instead (free tier, limits shown in AI Studio, 25 Nov):**

  | Model | Requests/min | Input tokens/min | Requests/day |
  |---|---|---|---|
  | Gemini 3.8 Flash | 5 | ≈250K (read from chart) | 20 |
  | Gemini 3.8 Flash TTS | 3 | 10K | 10 |
  | Gemini 3.8 Flash Lite TTS | 3 | 10K | 10 |

- **What I did:**
  1. All text calls (subtitles, translation) use Gemini 3.8 Flash instead of Flash-Lite.
  2. Narration uses Flash TTS; experiments use Flash Lite TTS. That doubles the daily TTS budget to 20 calls and gives a free model comparison.
  3. The pipeline doesn't retry quota (429) errors.
- **Lesson:** the brief warns that free tiers change. I checked the actual limits on day one rather than trusting the brief's table. 10 TTS requests/day turned caching from nice-to-have into necessary.

## F4: Gemini TTS `interactions.create` returned 404 without `v1beta`

- **Date:** 2026-11-26
- **Stage:** smoke test (`pipeline/smoke_test.py`)
- **What broke:** Calling `client.interactions.create(model="gemini-3.8-flash-lite-tts", ...)` with a default `genai.Client(api_key=...)` raised `NotFoundError: Error code: 404` stating the model is not found unless `api_version` is set to `'v1beta'`. Probing `gemini-2.5-flash-preview-tts` on `v1beta` also returned `BadRequestError: Error code: 400 - Speech annotations are not supported for model 'gemini-2.5-flash-preview-tts'`.
- **What I tried:**
  1. Checked `https://ai.google.dev/gemini-api/docs/speech-generation` and listed available models on the API key across `v1beta` and `v1alpha`.
  2. Confirmed `gemini-3.8-flash-lite-tts` and `gemini-2.5-flash-preview-tts` are both present on `v1beta`, and that the speech generation docs initialize `genai.Client(http_options={"api_version": "v1beta"})`.
- **What fixed it:** Passing `http_options={"api_version": "v1beta"}` to `genai.Client(...)` in `pipeline/smoke_test.py` fixed `gemini-3.8-flash-lite-tts` (`outputs/narration/smoke_gemini.wav`, 24 kHz mono 16-bit WAV, 2.82 s). `gemini-2.5-flash-preview-tts` does not support `speech_metadata` annotations via `interactions.create` and remains excluded from primary TTS use.
- **Lesson:** Gemini TTS via `client.interactions.create` requires `http_options={"api_version": "v1beta"}` on `genai.Client` in `google-genai>=2.25.0`.

## F5: No usable Gemini fallback for narration, so Addis AI added as a second provider

- **Date:** 2026-11-26
- **Stage:** smoke test → narration planning
- **What broke:** Gemini TTS is capped at 10 requests/day per model on the free tier (F3), and the suggested fallback `gemini-2.5-flash-preview-tts` rejects style annotations (F4), so it would change the narration's style mid-film.
- **What I considered:** creating extra Google Cloud projects to multiply the free quota (suggested in the cohort Slack). Rejected: Google's API Terms §2(d) say users agree to the documented limits and will not attempt to circumvent them.
- **What I did:** added Addis AI (Amharic-specific TTS, about 5 ETB/min, $3.17 free credit) as a second provider behind the same narration stage. The provider is chosen by experiment E1 (same lines from both), and each full narration pass uses one provider only.

## F6: Coding agent hit its weekly quota mid-run

- **Date:** 2026-11-26
- **Stage:** narration (task 1.8), while Antigravity CLI was running `run.py --stage narration`
- **What broke:** `agy` stopped with `⚠ Individual quota reached. Please upgrade your subscription to increase your limits. Resets in 165h30m52s.` That's about 7 days, after the challenge deadline. The narration run it had started may not have finished.
- **What I tried:**
  1. Checked `runs.jsonl` (lines 10–18) and `outputs/narration/`: the narration run had **finished before the quota stopped the agent**. All 9 spoken shots were generated by Addis AI (`am-hamen`), 41.4 s of speech in total, costing 3.45 ETB.
  2. Tried installing OpenCode (`npm install -g opencode-ai`): the command produced no output, so I abandoned it.
  3. Considered a second Antigravity account. Rejected: it would be getting around a usage limit, the same reason as the extra-keys decision in F5.
- **What fixed it:** switched to **Claude Code in VS Code**. It's paid, which the brief allows (it names Claude Code as a professional tool; free agents are only described as sufficient). The repo's `CLAUDE.md` imports `AGENTS.md` (`@AGENTS.md`), so the same rules apply to it.
- **Lesson:** the brief warns that free agent quotas are weekly. One long agent session (many prompts plus waiting on runs) can use up the whole week. Run long pipeline commands myself in the terminal, and use the agent only to write and fix code.

## F7: Radio cut: sentences cut off, and long silences between lines

- **Date:** 2026-11-26
- **Stage:** radio cut (task 1.13) → Test 1
- **What broke:** family listeners (Test 1) heard sentences **cut off before they finished** (s03 especially), and an **unsettling silence after every line**, as if the story stopped.
- **Cause (silences):** shot lengths (7–10 s) were planned before the narration existed. The spoken lines are 2.6–6.9 s (41.4 s in total, runs.jsonl lines 10–18), leaving 3–5 s of near-silence in each shot.
- **Cause (cut-offs):** `<fill in after diagnosis: raw WAV already cut by the TTS / trimmed or faded by assemble.py>`.
- **What I tried:** `<fill in: listened to the raw WAVs; ffprobe durations vs durations.json; checked the trim/fade filters in assemble.py>`
- **What fixed it:** shot length is now driven by narration (narration + ≈1.2 s hold; s05 and the end of s10 hold longer). `<fill in the cut-off fix>`.
- **Lesson:** time the voice first, then the pictures. The brief says exactly this, and I learned it the hard way.

## F8: TTS repeated a word and restarted the sentence (s07)

- **Date:** 2026-11-26
- **Stage:** narration → Test 1
- **What broke:** Addis AI read "ማታ ማታ፣ …" by repeating "ማታ" and restarting the sentence. The family also said "በኩራዝ … ታጠና" read as studying *with* a kuraz rather than *helped by* its light.
- **What I did:** reworded to "በየምሽቱ፣ በኩራዝ ብርሃን ታግዛ፣ ላለመበለጥ ታጠና ነበር።" (no repeated word, correct meaning); see E3.
- **Lesson:** a deliberately repeated word ("ማታ ማታ") can trip a TTS model. Prefer one unambiguous word.