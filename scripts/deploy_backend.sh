#!/usr/bin/env bash
# Builds backend/ with Cloud Build and deploys to Cloud Run (asia-south1). Costs a little; run deliberately.
set -euo pipefail
export PATH="$HOME/google-cloud-sdk/bin:$PATH"
PROJECT=project-0fd9c4ae-bf90-452f-a80
SA=pravah-backend@$PROJECT.iam.gserviceaccount.com
cd "$(dirname "$0")/../backend"
gcloud run deploy pravah-backend \
  --project "$PROJECT" --source . \
  --region asia-south1 --service-account "$SA" \
  --memory 4Gi --cpu 2 --timeout 900 --no-cpu-throttling \
  --allow-unauthenticated \
  --set-env-vars "GOOGLE_CLOUD_PROJECT=$PROJECT,GOOGLE_CLOUD_LOCATION=global,GOOGLE_GENAI_USE_VERTEXAI=TRUE,GEMINI_MODEL_FAST=gemini-3.8-flash,GEMINI_MODEL_PRO=gemini-3.8-flash,GEMINI_THINKING_FAST=LOW,GEMINI_THINKING_PRO=HIGH,EE_PROJECT=$PROJECT,GCS_BUCKET=pravah-dss-data-$PROJECT" \
  --set-secrets "MAPS_SERVER_KEY=maps-server-key:latest"
