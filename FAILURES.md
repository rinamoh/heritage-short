# FAILURES.md


## F1: Antigravity CLI installer showed no progress

- **Date:** 2026-11-25
- **Stage:** setup (task 0.5, installing the coding agent)
- **What broke:** `irm https://antigravity.google/cli/install.ps1 | iex` ran in the VS Code terminal with no output and no progress for `<confirm: how long>`.
- **What I tried:**
  1. `Invoke-WebRequest -Uri "https://antigravity.google" -UseBasicParsing -TimeoutSec 10` returned `200 OK`. That showed the site was reachable, but not that the install script itself had downloaded or what it was doing.
  2. Split "download" from "run" so each step's output could be seen: `<confirm: which of these you ran: checked the script URL / saved the script to a file and read it / ran it with -File / just waited>`.
- **What fixed it:** the installer finished and printed:
  `✅ Antigravity CLI binary placed successfully at C:\Users\LENOVO\AppData\Local\agy\bin\agy.exe`,
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


## F4: Gemini TTS returned 404 until the API version was set to v1beta

- **Date:** 2026-11-26
- **Stage:** smoke test (task 0.27)
- **What broke:** `client.interactions.create(...)` for `gemini-3.8-flash-lite-tts` returned `404 NotFoundError` with the default `genai.Client(...)`.
- **What I tried:** the agent checked the Gemini speech-generation docs and listed the models available on this key under the `v1beta` and `v1alpha` API versions.
- **What fixed it:** `genai.Client(api_key=..., http_options={"api_version": "v1beta"})`. After that, `gemini-3.8-flash-lite-tts` returned a 2.82 s, 24 kHz mono 16-bit WAV (runs.jsonl line 6).
- **Lesson:** the docs' example didn't work as-is on this key; the API version had to be set explicitly. Every TTS call in the pipeline must use the v1beta client.

## F5: The fallback TTS model rejects style instructions

- **Date:** 2026-11-26
- **Stage:** smoke test (optional probe)
- **What broke:** `gemini-2.5-flash-preview-tts` (suggested in the cohort Slack as a quota fallback) exists on v1beta, but returned `400 BadRequestError: Speech annotations are not supported for model 'gemini-2.5-flash-preview-tts'` (runs.jsonl line 7).
- **What it means:** this model can't take the `speech_metadata.style` instruction ("warm, slow, unhurried…") the narration relies on. As a fallback it would produce narration in a different style mid-film.
- **Decision:** not used as a narration fallback. Addis AI is the fallback, or the primary if it wins the comparison.

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
- **Cause (cut-offs):** `<fill in after diagnosis: raw WAV already cut by the TTS / trimmed or faded by assemble.py>`. (See the update under F8: the Addis AI WAVs were already cut.)
- **What I tried:** `<fill in: listened to the raw WAVs; ffprobe durations vs durations.json; checked the trim/fade filters in assemble.py>`
- **What fixed it:** shot length is now driven by narration (narration + a short hold; s05 and the end of s10 hold longer). Cut-offs: narration switched to Gemini (see F8 update).
- **Lesson:** time the voice first, then the pictures. The brief says exactly this, and I learned it the hard way.

## F8: TTS repeated a word and restarted the sentence (s07)

- **Date:** 2026-11-26
- **Stage:** narration → Test 1
- **What broke:** Addis AI read "ማታ ማታ፣ …" by repeating "ማታ" and restarting the sentence. The family also said "በኩራዝ … ታጠና" read as studying *with* a kuraz rather than *helped by* its light.
- **What I did:** reworded to "በየምሽቱ፣ በኩራዝ ብርሃን ታግዛ፣ ላለመበለጥ ታጠና ነበር።" (no repeated word, correct meaning); see E3.
- **Lesson:** a deliberately repeated word ("ማታ ማታ") can trip a TTS model. Prefer one unambiguous word.
- **Update (F7 resolved by provider switch, 2026-11-26):** Part 1 diagnosis: **cause (a)**. The Addis AI WAVs were already cut (s03 ends mid-"ች" with a rising ~4 kHz hiss in the last 30 ms; s08 and s09 suspect; WAV headers intact; assemble.py doesn't trim). Rather than spend the remaining time probing workarounds (format, trailing text), narration was **switched to Gemini 3.8 Flash TTS**, whose smoke sample wasn't clipped. An automatic `clipped_end` check (last 30 ms above −45 dBFS) now runs on every narration file.

## F9: The Gemini SDK would have retried quota errors on its own

- **Date:** 2026-11-26
- **Stage:** narration (switch to Gemini TTS)
- **What broke:** nothing yet. It was caught before it cost anything. Reading the installed `google-genai` code showed that `interactions.create` retries 408/409/429/5xx up to 4 more times by default. With a 10-requests/day TTS quota, one quota error could have used up the rest of the day's calls.
- **What I tried:** checked the SDK's retry settings, then tested against a local fake server that returns 429.
- **What fixed it:** `http_options` with `retry_options` set to `attempts=1`, so a 429 now sends exactly one request. The pipeline's own retry logic never retries 429s (AGENTS.md rule).
- **Lesson:** a library's defaults can break your own rules. "Never retry a 429" had to be enforced at the SDK level too, not just in my code.

## F10: Radio cut with Gemini narration was 97.33 s, over the 90 s limit

- **Date:** 2026-11-26
- **Stage:** radio cut v2 (after the switch to Gemini)
- **What broke:** with narration-driven timing the radio cut came to **97.33 s** including the 3 s end card. The brief's limit is 90 s.
- **What I tried:** shortened only the holds, not the narration (a narration line is never trimmed, and re-recording would have used Gemini's 10-a-day quota): lead-in 0.3 → 0.2 s, default hold 1.2 → 0.6 s, s03 hold 3 → 1.5 s, s10 hold 2.5 → 1.5 s, s05 (planned silence) 5 → 3 s.
- **What fixed it:** the same cached narration re-laid on the new timeline gave **87.88 s** with the end card, with zero TTS calls.
- **Lesson:** a timing rule changes the total length. Check the total against the brief's limit every time the rule changes, not only when a line changes.

## F11: Kaggle GPU queue never started

- **Date:** 2026-11-26
- **Stage:** music (Block 3A), Kaggle notebook with a T4 GPU
- **What broke:** the notebook didn't start: "Waiting for the next available notebook. Your position in the queue is 564." `<fill in: the time you joined the queue>`
- **What I tried:** waited `<N>` min; the queue position only moved from 564 to 545.
- **What fixed it:** switched to **Google Colab's** free T4. The notebook was changed to run on both platforms (an `OUT_DIR` detected at runtime; provider logged as `colab-t4`), uploaded to Colab, and run there (see F12 for the GPU problem on Colab). It produced `music_11.wav`, `music_12.wav`, `music_13.wav` and `runs_kaggle.jsonl`, now in `outputs/music/`. The queued Kaggle session was stopped so it wouldn't run a duplicate job.
- **Lesson:** the brief says the binding constraint is GPU time and queueing, not money. Launch GPU jobs as early as possible, and keep a second free GPU provider (Colab) ready.

## F12: Colab: "Failed to assign a backend, no backend with GPU available"

- **Date:** 2026-11-26
- **Stage:** music (Block 3A, step 3.C4–3.C5), Google Colab
- **What broke:** Connect hung for several minutes, then Colab showed: "Failed to assign a backend. No backend with GPU available. Would you like to use a runtime with no accelerator?"
- **What it means:** free-tier GPUs on Colab aren't guaranteed. At that moment none was free for my account. It isn't a fault in the notebook.
- **What I tried:** did **not** accept the no-accelerator (CPU) runtime: ACE-Step's language model plus diffusion model is built for a T4, and 3 tracks of 88 s on a CPU wasn't realistic in the time left. `<confirm: what you actually did, in order, e.g. disconnected and deleted the runtime / reloaded the page / tried an Incognito window with one account / waited N min and retried>`.
- **What fixed it:** `<confirm: what finally got a GPU, and how long it took>`. After that the first cell printed the GPU name (`<confirm: Tesla T4>`).
- **Lesson:** a free GPU is a queue by another name. Keep two GPU providers (Kaggle and Colab) and a time limit after which you stop retrying.

## F13: Gemini TTS daily quota was spent after the reset, leaving one request for Test 2

- **Date:** 2026-11-26
- **Stage:** narration, Test 2 change (s04 and s06 sound like a foreigner speaking Amharic)
- **What broke:** the plan assumed a fresh 10-request TTS quota "on Thursday after the reset" for re-recording. The full 9-line narration pass had already been run on Thursday itself: `runs.jsonl` shows nine Flash TTS calls (s01, s02, s03, s04, s06, s07, s08, s09, s10) between **08:44:51 and 08:47:40 UTC**. Google's rate-limit documentation says daily request quotas reset at **midnight Pacific time**, which is 08:00 UTC in late November (UTC−8). The calls are therefore on today's quota, and **at most one Flash TTS request remains** until 08:00 UTC on 27 November (11:00 EAT), after the 23:59 EAT deadline. Two lines (s04, s06) need re-recording.
- **What I checked:** counted today's Gemini TTS calls in `runs.jsonl` (command in COSTS.md); read the quota-reset statement in the Gemini API rate-limits page.
- **What I did:** option (b) as a test, then (c). I generated s04 and s06 on `gemini-3.8-flash-lite-tts`, which has its own 10-a-day quota, with the same text, voice and style. I judged the s04 audio much better, but both clips were about 3 s long, shorter than the film's Flash lines. Using them would have shortened both shots, moved the music cues against the picture, and needed a per-shot model setting in the pipeline (the film reads one model for all lines). The Flash quota still had one request, but with the deadline near I stopped and **kept the original Flash narration**, documenting the accent on s04 and s06 as a known weakness (DESIGN.md, Test 2). I did not check whether the Lite clips were complete or why they were shorter.
- **What I did not do:** a second API key or project to multiply the quota. Google's API terms forbid attempting to circumvent the documented limits (see the plan's decision table), and the code would sit in the repository that is graded.
- **Lesson:** a daily quota has a reset time, so a plan that says "tomorrow" needs the reset in the plan's own timezone. I recorded the reset time only after spending the day's calls.