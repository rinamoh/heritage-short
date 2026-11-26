# ETHICS.md

## 1. Consent

### Who the film is about
- **Subject:** my late grandmother, whom the family calls **Emaye**. She came to Addis Ababa from a small town in the south in the 1960s, at about 16, to continue her education.
- **How she appears:** only as an **invented, AI-generated figure**, always seen from behind, in silhouette or at a distance. **No clear face is ever shown.** **No photograph of her was used** as input to any model, and the figure isn't a reconstruction of her real appearance. Her life stages are shown through clothing: L1 day-to-day clothes, L2 school uniform, L3 a mother's dress with a head covering.
- **Voice:** she isn't voiced. The narration is a **stock Gemini TTS voice** (`Kore`, Gemini 3.8 Flash TTS) speaking as a grandchild. No voice was cloned or replicated, and no words are put in her mouth: the narration describes her in the third person.

### Who gave consent, and how
| Field | Record |
|---|---|
| Given by | The elders of my family (her children). Recorded by role only, to protect privacy. |
| Medium | Family group chat |
| Date | 2026-11-25 |
| Request 1 | I asked the elders for permission to make a short AI film about Emaye's journey to Addis Ababa for my training programme. They agreed. |
| Request 2: informed-consent follow-up | Sent to the same group on 2026-11-25: "To confirm: the film about Emaye is made with AI. An AI-generated figure (not her real face, never shown clearly) will represent her. The narration is a computer voice speaking as her grandchild. I will post it publicly with an AI label. I'll send you the final narration before posting. Is that okay?" The group agreed. |
| What they agreed to | (1) a short film about her life, made with AI; (2) an AI-generated figure representing her, never with a clear face; (3) a computer-voice narration speaking as her grandchild; (4) public posting with the platform's AI label switched on; (5) seeing the final narration before posting. |
| Evidence | Screenshots of both messages and the replies, kept privately by me. They're **not committed**, because they show phone numbers and family names. Available to the programme on request. |

### Reconfirmation of the final narration (promised in Request 2)
- Final narration (Amharic + English subtitles) sent to the family group on: *pending, task 5.5*. Reply: *pending*.

### Facts used in the film, and where they came from
All biographical facts in the narration were confirmed by the family elders on 2026-11-25:
- She came to Addis Ababa in the 1960s, at about 16.
- In her area, school didn't go beyond fifth grade.
- She made the journey on foot.
- She knew no one in the city.
- She finished middle school and started high school.
- She was often the only educated woman in the groups she was part of.

The town is deliberately not named.

### Other people in the film
- **None real.** The children and grandchildren implied in shots s09–s10 are invented and never shown with faces. They are represented by lamps, notebooks and study desks.

### Withdrawal
- If any family member asks, I'll take the post down and remove the film links from the repository.

## 2. Licences

| Component | Model / tool | Licence / terms | Notes |
|---|---|---|---|
| Keyframes | FLUX.2 [klein] **4B** on Cloudflare Workers AI | Apache 2.0 (model); Cloudflare terms (service) | 4B chosen deliberately: the 9B variant is non-commercial |
| Moving shots | Wan 2.2 TI2V-5B | Apache 2.0 | Wan claims no rights over generated content; responsibility for use is mine |
| Score | ACE-Step 1.5 | MIT | The brief states outputs may be used commercially. I couldn't confirm the training-data statement on the model pages I read; I'm relying on the brief for it. |
| Narration (film) | **Gemini 3.8 Flash TTS**, voice `Kore` | Gemini API terms: https://ai.google.dev/gemini-api/terms. Google doesn't claim ownership of generated content | Free tier; see §4 on data use |
| Narration (v1, not in the film) | Addis AI TTS, voice `am-hamen` | Addis AI Terms: check at addisassistant.com if Addis audio is used later | Used for v1 / Test 1 only, ~3.45 ETB |
| Subtitles / translation | Gemini 3.8 Flash | Gemini API terms | |
| Assembly | FFmpeg | LGPL/GPL (tool); no claim on output | |
| Coding agent | Antigravity CLI (until its weekly quota ran out, F6), then Claude Code (Sonnet 5.5) in VS Code | Google terms; Anthropic terms | Switch recorded in FAILURES F6 |

## 3. Labelling plan
- **AI end card** (3 s) at the end of both versions: "Made with AI", plus the models used.
- **Platform AI label** switched on when posting. Screenshot kept as evidence.
- **Watermarks and provenance metadata** (SynthID, C2PA) left intact. The pipeline never strips metadata.
- **Style:** described by qualities (palette, light, grain, painterly), never by naming a living artist.

## 4. Private data
- The town stays "a small town in the south". **No town name, family names or personal details** are sent to any model.
- No family photographs are uploaded to any endpoint.
- Free endpoints may use submitted data for training, which is why the prompts contain only generic descriptions.