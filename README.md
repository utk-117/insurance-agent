# Asha — life-insurance voice sales agent

A browser voice agent that sells life insurance from 10 plans by **SBI Life, ICICI Prudential Life and HDFC Life**,
for a fictional advisory brand. It speaks first, confirms who it's talking to, asks 5 intake questions, works out
eligibility, maximum cover and indicative premiums **in code**, then runs a free sales conversation around what the
customer actually wants — answering on cover, price, claims and the buying process **only from the brochures and
data in `data/`** — and closes with an advisor callback (the main goal), a purchase link sent by message, or a
polite goodbye. Every outcome is logged to a Google Sheet.

- **Live demo:** https://insurance-voice-agent-877719973605.asia-south1.run.app (access code required)
- Voice pipeline built from scratch (no Pipecat / LiveKit / Vapi; no LangChain): plain Python, FastAPI, WebSockets.
- STT, TTS and LLM are swappable by env var. Default: **Sarvam for all three** (Saaras v3, Bulbul v3,
  Sarvam-105B); Claude (Haiku 4.5) is the alternative LLM.
- Design and rules: [`CLAUDE.md`](CLAUDE.md). Results, latency, cost and lessons: [`NOTES.md`](NOTES.md).

## Using the demo
1. Open the link in Chrome, enter your name, phone and the access code, press **Start call**. Asha speaks first.
2. **Hold the button (or the space bar) while you talk**, release to send. English, Hindi or Hinglish.
   No microphone? Type your replies in the box — Asha still speaks.
3. The side panel shows the conversation stage, your profile, eligible plans with indicative price ranges, and
   the latency of every turn.

## How it works
```
browser (push-to-talk) --WS--> FastAPI --> STT (Sarvam Saaras) --> controller --> TTS (Sarvam Bulbul) --> browser
                                              |
      GREET -> CONFIRM_IDENTITY -> INTAKE (5 slots, decided in code) -> profile_snapshot()
      -> CONSULT (LLM + 9 tools: product sections, premium estimate, savings illustration, claims record,
         compare, process info, book_callback, send_purchase_link, end_conversation)
      -> CLOSE / WRAP_UP (code-guarded tools) -> lead row -> Google Sheet + CSV
```
- **Deterministic where it must be:** intake order, eligibility, max cover (25x income up to 35, 20x above),
  price ranges, amounts (the LLM only ever sees "₹20 crore", never raw integers), callback checks (confirmed,
  read back, future, within 14 days, 9 AM–9 PM IST), never saying the phone number.
- **The LLM runs the sales conversation:** it infers what the customer wants, picks eligible plans, explains why,
  handles doubts and objections, and moves to a close — using tools for detail.
- Agent reply -> text normalised for speech (lakh/crore, %, dates) -> split so the first chunk is short -> TTS
  chunks in parallel -> streamed to the browser in order.

| Path | What |
|---|---|
| `app/main.py`, `app/pipeline.py` | session API + WebSocket; one voice turn (STT -> agent -> TTS) with timings |
| `app/agent/controller.py` | phase controller, prompt assembly, tool loop |
| `app/agent/intake.py`, `money.py`, `tools.py`, `knowledge.py` | intake parsing, amounts in words, tools, data access |
| `app/adapters/` | Sarvam STT / TTS / LLM, Claude LLM — one file each, registered in `base.py` |
| `prompts/` | all prompt text (persona + rails, phase guides, objections, judge) |
| `data/knowledge/` | cards, eligibility, brochure sections, pricing examples, claims records (prebuilt) |
| `evals/`, `scripts/bench.py`, `scripts/bench_live.py` | eval cases + LLM judge; latency benchmarks |

## Setup (local)
```bash
python3.11 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env    # SARVAM_API_KEY, ACCESS_CODE; optional ANTHROPIC_API_KEY, SHEET_ID
```
ffmpeg is only needed if the browser's audio format is rejected by STT (the Docker image includes it).

## Run
```bash
.venv/bin/uvicorn app.main:app --port 8080                           # web app: http://localhost:8080
.venv/bin/python -m app.cli --name Rahul --phone 9876543210 --debug  # same agent, typed, in the terminal
.venv/bin/python scripts/smoke.py                                    # one call each to STT, TTS, LLM
```
Switch the LLM with `LLM_PROVIDER=anthropic` (default model `claude-haiku-4-5`; override with `LLM_MODEL`).

## Test, evaluate, benchmark
```bash
.venv/bin/python -m unittest discover -s tests                       # unit tests (no network)
.venv/bin/python data/knowledge/check_integrity.py                   # knowledge-base cross references
.venv/bin/python -m evals.run_evals --llm sarvam                     # 24 scripted conversations + LLM judge
.venv/bin/python -m evals.run_evals --llm anthropic --no-judge       # swap test, code checks only (cheap)
.venv/bin/python scripts/bench.py --llm sarvam --llm anthropic -n 5  # local latency per stage
.venv/bin/python scripts/bench_live.py -n 5                          # time to first audio on the live service
```

## Deploy (Google Cloud Run, Mumbai)
```bash
gcloud auth login && gcloud config set project <PROJECT_ID>
printf '%s' "$SARVAM_API_KEY" | gcloud secrets create SARVAM_API_KEY --data-file=-   # once; also ACCESS_CODE,
scripts/deploy.sh                                                                     # optional ANTHROPIC_API_KEY
```
`SHEET_ID` is read from `.env`; share that Google Sheet (Editor) with the Cloud Run service account
(`<project-number>-compute@developer.gserviceaccount.com`) — no key file needed.
One-time setup a new project needed: the Artifact Registry repo `cloud-run-source-deploy` (asia-south1),
`roles/run.builder` for the default compute service account, Secret Manager access for it, and the Sheets API.
Organisation policy blocks `allUsers`, so the service is public via `--no-invoker-iam-check`; the access code
guards it. Health check: `/health`.

## Milestones
- [x] M0 setup
- [x] M1 knowledge wiring
- [x] M2 text agent
- [x] M2b v2 redesign (intake in code, consult with tools)
- [x] M3 evals + swap test (Sarvam vs Claude, judge scorecard, benchmarks)
- [x] M4 voice web UI, deployed
- [x] M5 Google Sheets, purchase link by message, latency panel
- [x] M6 ship
