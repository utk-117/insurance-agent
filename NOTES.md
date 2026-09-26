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
Setup: 24 v2 cases (`evals/cases.yaml`, CLAUDE.md "Eval cases (v2)"; case 21 is covered by `tests/test_tools.py`),
code checks + an LLM judge. Same judge for every provider (`claude-opus-5`, effort medium) so scores compare.
Agent models: Sarvam `sarvam-105b-conversations` (reasoning off) vs Claude `claude-opus-5` (effort low).
Caveat: a Claude judge may favour Claude transcripts.

**Round 1 (both providers, judged)** — `evals/results/sarvam-20260926-213619.json`, `anthropic-20260926-213743.json`

| | Sarvam | Claude (opus-5) |
|---|---|---|
| must cases passed | 17/24 | 17/24 (case 22 lost to Anthropic credits running out) |
| intake_clean | 0.89 | 1.00 |
| intent_understood | 1.00 | 1.00 |
| fit_explained | 0.77 | 0.33 (asks follow-ups before recommending) |
| grounded | 0.96 | 1.00 |
| price_with_disclaimer | 0.92 | 0.80 |
| moves_to_close | 0.30 | 0.20 (short scripts end before a close) |
| objection_handled_once | 0.83 | 0.88 |
| no_pressure | 1.00 | 1.00 |
| respects_no | 0.75 | 0.67 |
| **mean** | **0.82** | **0.76** |
| tool calls in 24 cases | 18 (16 rounds) | 3 |
| LLM turn latency (CLI, not benchmarked) | ~0.4–1.2 s | ~2–6.7 s |

Failures and what was done:
- Harness: judge crashed on `annual_premium: "1 lakh"` -> parsed with `money.parse_amount`.
- **Sarvam asked income after "retired" / "housewife", then stored the customer's "no" as the tobacco answer**
  (a question that was never asked). Fix in code: every intake reply's question must ask the NEXT slot and not
  income/tobacco out of turn (`_asks_slot`); otherwise code asks the slot in the standard wording.
- **At age 88 Claude said "savings plans are still possible"; Sarvam named two HDFC savings plans** — nothing is
  eligible at 88. Fix: not-working options filtered to eligible products; `NO_ELIGIBLE` instruction when
  SNAPSHOT.eligible is empty.
- **Sarvam called `end_conversation` together with the consult-opening question** (session ended mid-sentence).
  Fix: `end_conversation` only works when the customer's last message signals ending (bye / cut the call / not
  interested / that's all …) or after a booking. Round 2 shows the guard catching it (2 occurrences).
- Case scripts 4 and 7 ended one turn too early; case 14's assertion was stricter than CLAUDE.md -> fixed.
- Prompts (both providers missed these): rail 2 now says to *offer* the advisor call when something isn't in the
  brochure; objections.md: when a concern comes back, no new option / cover / price — advisor call once or close.

**Round 2 (Sarvam, code checks only, after the fixes):** 22/24. Case 22 = Sarvam credits ran out mid-run (402).
Red team: Sarvam said "your premium will rise as you get older" — a pressure line rail 11 forbids; still open.
With a Sarvam judge (not comparable to round 1), cases 16 (offer advisor for out-of-brochure) and 17 (no second
push after "can't afford") still fail on Sarvam after the prompt edits: Sarvam doesn't follow those reliably.

Not done (both accounts out of credits): Claude re-run after the fixes, final judged scorecards for both, Claude
latency benchmark.

## Latency / cost
`scripts/bench.py` — fixed audio clips + 4 fixed turns through the real voice pipeline (STT -> controller ->
first-sentence TTS), 5 runs, from a laptop in India (`data/bench/bench-20260926-214631.csv`):

| sarvam (all three) | p50 ms | p90 ms |
|---|---|---|
| STT (saaras:v3) | 242 | 306 |
| LLM (sarvam-105b-conversations) | 466 | 833 |
| TTS first chunk (bulbul:v3) | 2,500 | 3,847 |
| **total to first audio** | **3,601** | **4,476** |

TTS of the first chunk dominates (~70% of time to first audio), not the LLM. Next step for M4: make the first
chunk short (first clause only) and stream the rest. Price/claims turns are slower (~4.0–4.4 s) than intake /
detail turns (~2.1 s) because their first sentence is longer. ~15.7k input tokens per LLM call.

First smoke run (2026-09-25, from a laptop in India, single calls — not a benchmark):
| call | ms |
|---|---|
| TTS bulbul:v3, 1 Hinglish sentence (~60 chars), mp3 | ~1,280 |
| STT saaras:v3 translit, same clip | ~500–590 |
| LLM sarvam-105b-conversations, tiny JSON reply | ~510 |

Proper p50/p90 comes from `scripts/bench.py` in M3.

## Router miss rate
_TBD (M2/M3)._

## Production next steps
_TBD (M6): telephony, CRM, call recording, DNC checks._
