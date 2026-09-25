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
- Sarvam API quirks: _to be filled as found (run `scripts/smoke.py`)._

## Latency / cost
_TBD (M3 bench, M6)._

## Router miss rate
_TBD (M2/M3)._

## Production next steps
_TBD (M6): telephony, CRM, call recording, DNC checks._
