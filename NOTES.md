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

## Latency / cost
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
