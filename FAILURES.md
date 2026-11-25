# FAILURES.md

> Running log of real blockers: what broke, what I tried, what fixed it. Copy this into the repo's `FAILURES.md` once the repo exists. Fields marked `<confirm>` are details only you can fill in.

## F1: Antigravity CLI installer showed no progress

- **Date:** 2026-11-25
- **Stage:** setup (task 0.5, installing the coding agent)
- **What broke:** `irm https://antigravity.google/cli/install.ps1 | iex` ran in the VS Code terminal with no output and no progress for `<confirm: how long>`.
- **What I tried:**
  1. `Invoke-WebRequest -Uri "https://antigravity.google" -UseBasicParsing -TimeoutSec 10` returned `200 OK`. That showed the site was reachable, but not that the install script itself had downloaded or what it was doing.
  2. Split "download" from "run" so each step's output could be seen: `<confirm: which of these you ran: checked the script URL / saved the script to a file and read it / ran it with -File / just waited>`.
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