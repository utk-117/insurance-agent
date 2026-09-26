#!/usr/bin/env bash
# Deploy to Cloud Run, Mumbai. Needs: gcloud auth login; gcloud config set project <id>.
# Secrets: create once with  gcloud secrets create SARVAM_API_KEY --data-file=-   (etc.)
set -euo pipefail
SERVICE=${SERVICE:-insurance-voice-agent}
REGION=asia-south1

# create once from .env:  printf %s "$VALUE" | gcloud secrets create NAME --data-file=-
SECRETS="SARVAM_API_KEY=SARVAM_API_KEY:latest,ACCESS_CODE=ACCESS_CODE:latest"
if gcloud secrets describe ANTHROPIC_API_KEY >/dev/null 2>&1; then SECRETS="$SECRETS,ANTHROPIC_API_KEY=ANTHROPIC_API_KEY:latest"; fi

# SHEET_ID (not secret) from the environment or .env; the service account needs Editor access to that Sheet
SHEET_ID=${SHEET_ID:-$(grep '^SHEET_ID=' .env 2>/dev/null | cut -d= -f2-)}

gcloud run deploy "$SERVICE" --quiet \
  --source . \
  --region "$REGION" \
  --no-invoker-iam-check \
  --min-instances=1 --max-instances=2 \
  --session-affinity \
  --timeout=900 \
  --concurrency=20 \
  --cpu=1 --memory=1Gi \
  --set-env-vars "STT_PROVIDER=${STT_PROVIDER:-sarvam},TTS_PROVIDER=${TTS_PROVIDER:-sarvam},LLM_PROVIDER=${LLM_PROVIDER:-sarvam},BRAND_NAME=${BRAND_NAME:-Suraksha Advisory},SHEET_ID=${SHEET_ID}" \
  --set-secrets "$SECRETS"

gcloud run services describe "$SERVICE" --region "$REGION" --format='value(status.url)'
