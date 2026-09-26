# Notes

## Approach
- Voice pipeline is plain Python + HTTP (httpx / anthropic SDK); no voice-agent framework.
- Providers are chosen per kind by env var and registered in `app/adapters/base.py`.
- Every provider call logs one JSON line: `{"event":"provider_call","kind","provider","model","ms",...}`.
- LLM JSON robustness (`app/adapters/base.py`): strip fences / `<think>` blocks -> first balanced JSON object ->
  required-key check -> one repair retry -> `LLMParseError` (the controller then falls back to a safe reply).
  Parse failures are counted per provider in `PARSE_FAILURES` and logged as `llm_parse_failure`.

## Decisions
- **Sarvam LLM**: `sarvam-105b-conversations` (the docs name it for real-time voice workloads, 32K context) on
  `/v1/chat/completions`, `response_format: json_schema`, `reasoning_effort: null` (reasoning off, for latency).
  All three are env-overridable.
- **Sarvam STT**: `saaras:v3`, `mode=translit` — romanised output ("claim kaise milega") so the Hinglish keywords
  in `topic_router.json` match. Switch to `codemix` with `SARVAM_STT_MODE` if Devanagari is preferred.
- **Sarvam TTS**: `bulbul:v3`, speaker `priya` (the persona is Asha), mp3 output. v3 has no pitch/loudness/preprocessing.
- **Router keyword matching**: keywords of 4 characters or fewer ("war", "tax", "exit", "gift") need word
  boundaries (optional plural "s"); longer keywords match as substrings, as `topic_router.json` specifies. Without
  this, "war" matched "aware" and "exit" matched "existing". Done in code; no data files changed.
- **Shortlist**: an unknown `income_band` fails a hard `gate` (ICICI Assured Savings isn't pitched until the band
  is known to be 25L+). A `soft_gate` sorts the product below un-gated ones but never drops it. A volunteered
  `preferred_insurer` puts that insurer's products first and lifts the one-per-insurer rule. A bare insurer
  name in the transcript ("the HDFC one") resolves to that insurer's shortlisted product.
- **Claude**: `claude-opus-5`, `output_config.effort=low`, structured output via `output_config.format`,
  static system blocks marked `cache_control`.

## Challenges
- **Sarvam LLM misreads rupee amounts by 10x** (first v2 test session, 36 / self-employed / ₹1 crore income):
  the snapshot said `max_cover: 200000000` (₹20 crore, correct: 20x above 35) and the model said "2 crore". The
  customer asked for 30 crore; the model called the estimate tool correctly with 300000000 but *said* "3 crore",
  then on the next turn sent 30000000 ("30 crore" -> one zero short). Both directions of the number <-> words
  conversion were left to the model. Fix (`app/agent/money.py`): the model never sees a raw rupee integer —
  snapshot, tool results and quoted ranges are pre-formatted ("₹20 crore", "₹8.61 lakh – ₹13.45 lakh a year");
  tools take amounts in words ("30 crore") parsed by code; code reads the amount in the customer's message into
  the prompt (like callback times) and auto-corrects a tool amount that is off by 10x/100x from what the customer
  said; savings illustrations are scaled by code, not "multiply by 1.8". Replayed live: correct 20 crore / 30 crore.
- **"cut the call" took 3 LLM calls** (end_conversation with no words, end_conversation again, then a third call
  that said "The call has been ended"). Fix: `end_conversation` carries the `goodbye`; the loop stops as soon as it
  succeeds; a second end_conversation is a no-op. Now 1 call (~0.5 s): "Sure, cutting the call now. Have a nice day!"
- Sarvam credits: two full v1 eval runs (30 cases, ~11k input tokens per call, plus judge calls with reasoning)
  used up the account's credits. From then on every call returned HTTP 402 `insufficient_quota_error`, which
  showed up as parse fallbacks and failed cases late in the second run. Use `--no-judge` and `--only` for cheap runs.
- Local dev machine: the only Python 3.11 installed is an x86_64 build and the arm64 Mac has no Rosetta,
  so local dev uses the system Python 3.9 (code keeps `from __future__ import annotations`, no 3.10+ syntax).
  Docker uses 3.11.
- `.env` inline comments: python-dotenv reads `LLM_MODEL=   # comment` (empty value + comment) as the value
  "# comment", and Sarvam rejected it as a model name. All comments in `.env.example` are now on their own lines.
- Sarvam APIs matched the docs so far: `json_schema` response_format and `reasoning_effort: null` are accepted
  by `sarvam-105b-conversations`; saaras:v3 `translit` returns romanised Hindi with `language_code=hi-IN`.

## M2 findings (text agent, Sarvam LLM)
Scripted runs: English term plan -> callback, Hinglish savings -> "kal shaam 5 baje", wrong person, not interested,
premium asked twice + smoking + "buy now". All reached the right outcome and lead row.

What the code had to absorb (the stage machine is in code, so it must not trust the LLM blindly):
- **`intent` is unreliable on sarvam-105b-conversations**: "Yes, this is Rahul" came back as `question`,
  "Yes, that's right" as `answered`. Fix: yes/no regex fallback on the customer's words; CONFIRM_IDENTITY
  moves on for anything except wrong person / no / not interested.
- **The LLM runs ahead of the stage** (pitches during DISCOVERY/NEED_CHECK). Fix: `sync_with_reply` moves the
  stage to RECOMMEND when the reply names a shortlisted product; the prompt carries NEXT STEP goals so the reply
  can complete the current step and start the next in one turn.
- **Callback booking**: the LLM often leaves `callback_time_iso` null, and on the confirming "yes" it repeats the
  same time. Fix: callback detection in every post-identity stage, a fallback time parser (`parse_time_text`:
  tomorrow/kal/parso/weekdays, am/pm/subah/shaam/baje), and booking on yes when the time is unchanged. Before
  this fix the agent *said* "booked" while nothing was logged.
- **Wrong weekday** in read-backs ("Friday, 26th September" — it was a Saturday). Fix: 8-day calendar in context.
- **Language drift**: English customers got Hinglish replies (the stage examples are Hinglish). Fix: detected
  customer language passed as `LANGUAGE` in context.

Prompt tuning left for the human review (not changed; `prompts/*.md` untouched except the new `controller.md`):
- First "not interested" often gets a goodbye instead of the one soft retry (rail 7).
- Asks "male or female?" even when the customer's Hindi verb forms say so ("bol rahi hoon").
- NEED_CHECK sometimes asks "anything you'd like to know?" instead of playing the need back.
- RECOMMEND sometimes pitches two products at once, and repeats the insurer ("ICICI Prudential Life ICICI Pru …").
- CALLBACK sometimes says "scheduled" before the customer has confirmed the read-back.

Prompt size: ~11k input tokens per turn (cards ~6k + process + sections); LLM 0.6–1.6 s per turn.

## M2b — v2 redesign (intake in code, consult by the LLM)
- Flow: GREET -> CONFIRM_IDENTITY -> INTAKE (age, gender, employment, income, tobacco; order decided in code)
  -> `profile_snapshot()` (eligibility, max cover, price ranges; `data/knowledge/intake_rules.py`) -> CONSULT
  (free conversation, tools) -> CLOSE / WRAP_UP -> END. v1 stage machine and `prompts/stages.md` removed.
- Intake: code parses the customer's words **before** the LLM call (`app/agent/intake.py`: "80k per month",
  "12-15 lakh" -> midpoint, "housewife" -> not_working, Hindi verb forms -> gender), so the reply always asks the
  right next slot. The LLM's `extracted` only fills what code couldn't parse ("thirty"). If the LLM's extraction
  completes intake, a second call opens the consult so the reply doesn't ask a stale question.
- Tools (`app/agent/tools.py`): 9 tools, one registry, compact JSON with page/source refs. Errors come back to
  the model as `{"ok": false, "error": ...}`; nothing raises. Max 2 tool rounds per turn, then a no-tools call.
- Close guards in code: `book_callback` needs `customer_confirmed`, a future IST time within 14 days, **and** the
  agent's previous reply must contain the read-back (day + hour); `end_conversation` can't claim a callback/link
  that never happened; `share_purchase_link` errors while `purchase_url` is null.
- Snapshot + claims records are in the prompt from CONSULT on, so price / claims / "which plan" turns need no tool.
  The v1 topic router is now a prefetch: sections the customer's words name are preloaded for the product in focus.
- Prompt caching: static block = persona, rails, process knowledge, objection guide, need_fit, cards, output rules;
  dynamic block = phase guide, intake state, snapshot, claims, current turn (time, calendar, language, prefetch).
- Sarvam tool calling: `SARVAM_TOOL_MODE=native` (OpenAI-style `tools` on /v1/chat/completions) — **verified live**
  on `sarvam-105b-conversations`: parallel tool calls, `finish_reason: tool_calls`, valid JSON arguments. The JSON
  protocol (`prompts/tools_json.md`) stays as an automatic fallback if the API ever rejects tools. Tool-call error
  rate per provider is counted in `TOOL_ERRORS` and reported by the eval runner.
- Voice: a filler line ("Ek second, main check karti hoon") is spoken in the background when a tool round starts
  after the customer has already waited > 1.5 s.
- Lead log: v2 columns; an older `data/leads.csv` with v1 columns is moved aside, not mixed.

## M3 — evals + swap test (26 Sep 2026)
Setup: 24 v2 cases (`evals/cases.yaml`, CLAUDE.md "Eval cases (v2)"; case 21 is covered by `tests/test_tools.py`
TestCloseGuards), code checks + one LLM judge for every provider (`claude-opus-5`, effort medium) so scores
compare. Caveat: a Claude judge may favour Claude transcripts. Agent models: Sarvam `sarvam-105b-conversations`
(reasoning off) vs Claude `claude-haiku-4-5` (product owner's choice; Opus 5 was tried first: similar quality,
2–6.7 s per LLM turn).

**Final run** — `evals/results/sarvam-20260926-215809.json`, `anthropic-20260926-215932.json`

| | Sarvam 105B | Claude Haiku 4.5 |
|---|---|---|
| must cases passed | **22/24** (23/24 after the consult-opening fix; 17 is flaky) | 18/24 |
| intake_clean | 0.95 | 0.95 |
| intent_understood | 1.00 | 1.00 |
| fit_explained | 0.86 | 0.38 (keeps asking follow-ups instead of recommending) |
| grounded | 0.96 | 0.96 |
| price_with_disclaimer | 0.64 | 0.17 (drops the indicative / underwriting disclaimer) |
| moves_to_close | 0.47 | 0.22 |
| objection_handled_once | 0.88 | 0.86 |
| no_pressure | 1.00 | 1.00 |
| respects_no | 0.67 | 0.67 |
| **scorecard mean** | **0.83** | **0.69** |
| tool calls in 24 cases (tool errors) | 17 (1: min-cover guard) | 2 (0) |
| LLM p50 / p90 per turn (bench) | 484 / 766 ms | 2,100 / 2,424 ms |

Open failures:
- Sarvam case 17 (too expensive, twice): after the second refusal it sometimes re-pitches a lower cover in words.
  Code blocks the pricing tools after two refusals and the prompt says advisor-call-once-or-close; it passes on
  some runs and fails on others.
- Haiku: case 20 (never calls `book_callback` — keeps re-confirming), case 22 (asks for a cover amount instead
  of sharing the page), 9 and 17 (no disclaimer; a made-up monthly figure), 10 and 16 (no advisor offer).
  Haiku uses tools very rarely (2 calls in 24 cases). Tool-use tuning for Haiku or `claude-sonnet-5` would be the
  next step if Claude is needed.
**Recommendation: keep Sarvam as the default LLM** — better scorecard, more reliable tool use, and ~4x faster.

What the eval runs found and fixed (all in code unless marked):
- Claude adapter: strict structured-output schemas (additionalProperties false, nullable enum -> anyOf); Haiku
  skips `effort` (not supported on Haiku 4.5).
- **Sarvam asked a housewife for income and stored her next "no" as the tobacco answer** -> every intake question
  must ask the next slot (`_asks_slot`), else code asks it in the standard wording.
- **At age 88 both models suggested savings plans** (none eligible) -> not-working options filtered to eligible
  products; `NO_ELIGIBLE` instruction.
- **Sarvam hung up while asking the consult-opening question** -> `end_conversation` needs an end signal from the
  customer (or a completed booking).
- Blended price ranges ("₹11,500–18,500" across two plans) -> snapshot carries a code-computed "across eligible
  term plans" range with a ready "say" line.
- Rounded, multi-year claims answers -> CLAIMS RECORD / get_claims_record give one ready sentence per insurer for
  the latest FY (by amount + by number + "as per IRDAI data").
- Second "no" in intake ignored (model labelled it "answered") -> not-interested phrases count in code; first no
  gets a fixed soft-retry line, second no a fixed goodbye.
- Pushing after two refusals -> code blocks pricing tools and adds a RESPECT_NO instruction.
- Prompts (said at the time): rail 2 offers the advisor for out-of-brochure questions; rail 11 names the
  "premiums rise as you get older" line; objections.md no second push; phases.md CONSULT: use the "say" lines,
  offer the advisor when something isn't covered; CONSULT_OPEN: no more profile questions.
- Evals: judge crash on worded amounts; case scripts 4 / 7 one turn short; Hinglish prefix answers the new gender
  confirmation; case 14 matched to CLAUDE.md; case 17's second assertion aligned to objections.md.

## Latency / cost
`scripts/bench.py` — fixed audio clips + 4 fixed turns through the real voice pipeline (STT -> controller ->
first-sentence TTS), 5 runs per LLM, STT/TTS = Sarvam, from a laptop in India
(`data/bench/bench-20260926-220412.csv`):

| ms (p50 / p90) | Sarvam LLM | Claude Haiku 4.5 LLM |
|---|---|---|
| STT (saaras:v3) | 244 / 332 | 328 / 386 |
| LLM | 484 / 766 | 2,100 / 2,424 |
| TTS first chunk (bulbul:v3) | 2,140 / 3,757 | 2,087 / 3,722 |
| **total to first audio** | **2,856 / 4,684** | **4,522 / 6,164** |

TTS of the first chunk is the biggest stage for Sarvam (~75% of time to first audio). Next step for M4: make
the first spoken chunk short (first clause only) so audio starts sooner. ~16k input tokens per LLM call
(Claude: ~10.6k of them served from the prompt cache).

## Router miss rate
_TBD (M2/M3)._

## Production next steps
_TBD (M6): telephony, CRM, call recording, DNC checks._
