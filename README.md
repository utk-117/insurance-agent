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
.venv/bin/python -m unittest discover -s tests -v      # knowledge + JSON-parsing tests
.venv/bin/python data/knowledge/check_integrity.py     # knowledge-base cross references
```

## Deploy (Cloud Run, asia-south1)
```bash
gcloud auth login && gcloud config set project <PROJECT_ID>
printf '%s' "$SARVAM_API_KEY" | gcloud secrets create SARVAM_API_KEY --data-file=-
scripts/deploy.sh
```

## Milestones
- [x] M0 setup: adapters (Sarvam STT/TTS/LLM + Claude), smoke script, FastAPI hello + WS echo, Dockerfile, deploy script
- [x] M1 knowledge wiring: `app/agent/knowledge.py` + tests
- [ ] M2 text agent · M3 evals + swap test · M4 voice UI · M5 integrations · M6 ship
