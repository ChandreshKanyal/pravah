# Pravah progress

| Stage | Status | Date-time (IST) | What works | Deviations from spec | Open questions | What the human must do |
|---|---|---|---|---|---|---|
| S0.9 scaffold | done | 2026-10-15 | Repo layout per SPEC §3.5, venv (py3.12), deps installed and pinned in `backend/requirements.txt`, config + CORS app stub | Frontend `src/` dirs only; Vite app comes in S0.13 | | |
| S0.10 list models | done | 2026-10-15 | `scripts/list_models.py` runs on Vertex (global), lists 30 Gemini models | One model (`gemini-3.8-flash`) with thinking levels, per human (see Decisions) | | |
| S0.11 health | done | 2026-10-15 | `GET /api/health` returns ok with ee, vertex, firestore all true locally; unit test passes | | | |
| S0.12 Cloud Run | done | 2026-10-15 | Deployed `pravah-backend` (asia-south1); `https://pravah-backend-265255051442.asia-south1.run.app/api/health` returns ok, ee, vertex, firestore all true | Needed IAM roles on default compute SA for Cloud Build (human granted); service is public | | |
| S0.13 Firebase | done | 2026-10-15 23:30 | `https://project-0fd9c4ae-bf90-452f-a80.web.app` serves Hello Pravah; `/api/health` via rewrite returns ok, ee, vertex, firestore all true | Deploy run by human (agent deploys blocked by permission classifier) | | Done: browser key referrers now include web.app and firebaseapp.com |

## Decisions
- `pravah/` has its own git repo (`git init` inside it); the parent home directory is also a git repo, left untouched.
- gcloud/firebase are not on PATH; commands use `~/google-cloud-sdk/bin` and `~/.npm-global/bin`.
- Frontend env var is `VITE_GOOGLE_MAPS_API_KEY` (per CONFIG.md), not SPEC §3.6's `VITE_MAPS_BROWSER_KEY`.
- Budget is ₹9,000 alerts (CONFIG.md), not the $100 in S0.8.
- Dependencies: unpinned list in `backend/requirements.in`, pinned freeze in `backend/requirements.txt`.
- D1 (human): use only `gemini-3.8-flash`. FAST = thinking LOW, PRO = thinking HIGH. Verified on Vertex (global): LOW, MEDIUM, HIGH work; MINIMAL is rejected (400). Env vars: `GEMINI_MODEL_FAST/PRO` both `gemini-3.8-flash`, plus `GEMINI_THINKING_FAST/PRO`.
- Cloud Build needed `cloudbuild.builds.builder`, `storage.objectViewer`, `artifactregistry.writer`, `logging.logWriter` on `265255051442-compute@developer.gserviceaccount.com` (granted by the human).
