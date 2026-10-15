# S0 prompt: paste this into the coding agent as the first message

You are building the Pravah prototype. Work only on stage S0 (steps S0.9 to S0.13).

Read first, in this order:
1. AGENTS.md (standing rules).
2. docs/SPEC.md sections 0 (how to use), 2 (non-negotiable rules), 3 (architecture, repo layout, env vars), and stage S0.
3. docs/CONFIG.md (cloud values; the Cloud Console part of S0, steps S0.1 to S0.8, is already done).

Do:
- S0.9 Scaffold the repo exactly as in SPEC §3.5. Backend deps as listed in S0.9; pin versions after the first successful install.
- S0.10 Write scripts/list_models.py (google-genai, vertexai=True, project/location from env). STOP and show me the Gemini model names so I can pick GEMINI_MODEL_FAST and GEMINI_MODEL_PRO.
- S0.11 Implement GET /api/health: Earth Engine ping, one-line Gemini call, Firestore write+read of health/ping. Return ok only if all three pass.
- S0.12 Dockerfile and Cloud Run deploy to asia-south1 as the service account in CONFIG.md, with the flags from S0.12.
- S0.13 Firebase Hosting with the /api/** rewrite to Cloud Run, plus a "Hello Pravah" page showing the health result.

Rules:
- Follow SPEC §2. Google Maps is for display, forecast and geocoding only.
- Never commit keys or secrets. The server key is in Secret Manager as maps-server-key.
- Do not start S1 or anything beyond S0.
- Anything marked VERIFY: check the current docs and tell me what you found.
- If a command needs my gcloud login or a decision, stop and tell me exactly what to run.
- Before running anything that deploys, tell me what it will do.

Done when the deployed Firebase URL shows: ee ✓ vertex ✓ firestore ✓
