# Pravah: cloud config values (from S0 setup, 15 Oct 2026)

Hand this to the coding agents. Nothing here is a secret: the browser key is
referrer-restricted and the server key lives only in Secret Manager.

| Setting | Value |
|---|---|
| GCP project ID (`GOOGLE_CLOUD_PROJECT`, `EE_PROJECT`) | `project-0fd9c4ae-bf90-452f-a80` |
| Project number | `265255051442` |
| Region | `asia-south1` |
| Service account | `pravah-backend@project-0fd9c4ae-bf90-452f-a80.iam.gserviceaccount.com` |
| GCS bucket (`GCS_BUCKET`) | `pravah-dss-data-project-0fd9c4ae-bf90-452f-a80` |
| Firestore | `(default)`, Native mode, `asia-south1` |
| Server key secret name | `maps-server-key` (Secret Manager) |
| Browser key (`VITE_GOOGLE_MAPS_API_KEY`) | `AIzaSyAjSk75kDH5TYNN9yPvXKnkwBSh8SY_Rnc` |
| Map ID (`VITE_MAP_ID`) | `75bfaebed3e13b2e41422807` |
| Earth Engine | noncommercial, individual, Community tier |

## Done in S0 (Cloud Console / Cloud Shell)
S0.1 project and billing, S0.2 APIs, S0.3 Earth Engine, S0.4 service account,
S0.5 bucket and Firestore, S0.6 both API keys, S0.7 Map ID, S0.8 budget (₹9,000 alerts).

## Still open
- Browser key allows only `http://localhost:5173/*` and `http://localhost:4173/*`.
  After the first Firebase deploy, add the `*.web.app` and `*.firebaseapp.com` URLs.
- Pick `GEMINI_MODEL_FAST` / `GEMINI_MODEL_PRO` from `scripts/list_models.py` (S0.10).
- Next: S0.9 repo scaffold, S0.11 `/api/health`, S0.12 Cloud Run deploy, S0.13 Firebase Hosting.
