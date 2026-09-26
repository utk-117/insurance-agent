# Insurance voice sales agent

Browser voice agent that pitches life insurance (10 products: SBI Life, ICICI Prudential Life, HDFC Life)
from the documents in `data/`. STT, TTS and LLM are swappable; default is Sarvam for all three.
See `CLAUDE.md` for the full design.

## Setup
```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env      # fill SARVAM_API_KEY (and ANTHROPIC_API_KEY for Claude)
```
Docker/Cloud Run uses Python 3.11; the code also runs on 3.9+.

## Run
```bash
.venv/bin/python scripts/smoke.py                      # one call each to TTS, STT, LLM(s), with latency
.venv/bin/uvicorn app.main:app --reload --port 8080    # http://localhost:8080  (/healthz, /ws/echo)
.venv/bin/python -m app.cli --name Rahul --phone 9876543210 --debug   # M2 text agent (type 'quit' to end)
.venv/bin/python -m unittest discover -s tests -v      # knowledge, intake, tools, controller (fake LLM), normalize
.venv/bin/python -m evals.run_evals --no-judge          # v2 eval cases, code checks only (add the judge by dropping the flag)
.venv/bin/python data/knowledge/check_integrity.py     # knowledge-base cross references
```

## Deploy (Cloud Run, asia-south1)
Live: https://insurance-voice-agent-877719973605.asia-south1.run.app (access code required; health: `/health`)
```bash
gcloud auth login && gcloud config set project <PROJECT_ID>
# once: secrets from .env (SARVAM_API_KEY, ACCESS_CODE, optional ANTHROPIC_API_KEY)
printf '%s' "$SARVAM_API_KEY" | gcloud secrets create SARVAM_API_KEY --data-file=-
scripts/deploy.sh
```
One-time project setup that the first deploy needed (new GCP project):
- `gcloud artifacts repositories create cloud-run-source-deploy --repository-format=docker --location=asia-south1`
- grant the default compute service account `roles/run.builder` (source builds) and
  `roles/secretmanager.secretAccessor` on each secret
- the org policy blocks `allUsers`, so the service is public via `--no-invoker-iam-check` (the access code guards it)

## Milestones
- [x] M0 setup: adapters (Sarvam STT/TTS/LLM + Claude), smoke script, FastAPI hello + WS echo, Dockerfile, deploy script
- [x] M1 knowledge wiring: `app/agent/knowledge.py` + tests
- [x] M2 text agent: `app/agent/controller.py` stage machine, CSV lead log (`data/leads.csv`), transcripts in `data/transcripts/`
- [x] M2b v2 redesign: phase controller (identity -> 5-slot intake in code -> `profile_snapshot()` -> consult with tools -> guarded close), `app/agent/intake.py`, `app/agent/tools.py`, tool calling for Sarvam + Claude
- [x] M3 evals + swap test (Sarvam vs Claude Haiku 4.5, judge scorecard, `scripts/bench.py`)
- [x] M4 voice web UI (push-to-talk, typed fallback without a mic, state + latency panel), deployed to Cloud Run
- [ ] M5 evals + swap test · M4 voice UI · M5 integrations · M6 ship
