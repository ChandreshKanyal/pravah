#!/usr/bin/env bash
# Builds backend/ with Cloud Build and deploys to Cloud Run (asia-south1). Costs a little; run deliberately.
set -euo pipefail
export PATH="$HOME/google-cloud-sdk/bin:$PATH"
PROJECT=project-0fd9c4ae-bf90-452f-a80
SA=pravah-backend@$PROJECT.iam.gserviceaccount.com
cd "$(dirname "$0")/../backend"
# 8 CPUs: the 2D flow model runs inside every scenario and splits the grid across cores (2 CPUs: Rudraprayag 249 s).
# MIN_INSTANCES=1 for demo day only (S17.3: Earth Engine init makes cold starts slow); default 0.
MIN="${MIN_INSTANCES:-0}"
WEB="https://$PROJECT.web.app,https://$PROJECT.firebaseapp.com"
# "^@^" switches the env-var separator to "@" so CORS_ORIGINS can contain commas
gcloud run deploy pravah-backend \
  --project "$PROJECT" --source . \
  --region asia-south1 --service-account "$SA" \
  --memory 8Gi --cpu 8 --timeout 900 --no-cpu-throttling --min-instances "$MIN" \
  --allow-unauthenticated \
  --set-env-vars "^@^GOOGLE_CLOUD_PROJECT=$PROJECT@GOOGLE_CLOUD_LOCATION=global@GOOGLE_GENAI_USE_VERTEXAI=TRUE@GEMINI_MODEL_FAST=gemini-3.8-flash@GEMINI_MODEL_PRO=gemini-3.8-flash@GEMINI_THINKING_FAST=LOW@GEMINI_THINKING_PRO=HIGH@EE_PROJECT=$PROJECT@GCS_BUCKET=pravah-dss-data-$PROJECT@CORS_ORIGINS=$WEB" \
  --set-secrets "MAPS_SERVER_KEY=maps-server-key:latest"
