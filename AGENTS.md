# Pravah: instructions for the coding agent

Pravah is a flood and landslide decision-support prototype for authorities, built for the
Google AI Builder Cup 2026. Deadline: Sun 18 Oct 2026, 12:00 IST. Speed matters; scope is fixed.

## Read before coding
- `docs/SPEC.md` is the build spec. Read §0 (how to use), §2 (non-negotiable rules), §3 (architecture), then only the stage you are working on.
- `docs/CONFIG.md` holds the cloud project values. The Cloud Console setup is already done.
- `docs/Pravah_Components_and_Google_Services.xlsx` is the component tracker (reference only).
- `docs/S0_PROMPT.md` is the first task.

## Rules
- Work on one stage at a time, in SPEC order. Stop at each stage's acceptance criteria and report. Do not start the next stage.
- Everything must run on Google AI (Gemini via Vertex AI, ADK) and deploy to Google Cloud (Cloud Run, Firebase Hosting). No other cloud.
- Google Maps is for display, forecast and geocoding only (SPEC §2). No scraping, caching or bulk use of Maps content.
- Never commit secrets. The server key lives in Secret Manager as `maps-server-key`.
- The output is a first draft for human review. Use the exact disclaimer string from SPEC §2 wherever advice is shown.
- Anything marked VERIFY: check current docs and tell the human what you found.
- If you need the human to run a command (login, deploy, picking a Gemini model), stop and give the exact command.
- Keep changes small and commit often with clear messages.

## Environment (Mac, Apple Silicon)
- Python: use uv with Python 3.12 (`uv venv --python 3.12 backend/.venv`, then `uv pip install ...`). Do not use Homebrew; it is the Intel version and cannot compile here.
- Node 24; npm global prefix is ~/.npm-global. gcloud and firebase are installed and logged in as chankarkalwayal@gmail.com. gcloud project is project-0fd9c4ae-bf90-452f-a80.

## Working notes (from the build so far)
- gcloud and firebase are not on PATH in agent shells: use `~/google-cloud-sdk/bin/gcloud` and `~/.npm-global/bin/firebase`.
- Never add AI attribution lines to commits.
- Agent-run deploys are blocked by the permission classifier; give the human the exact deploy commands.
- Current status, decisions and spec deviations live in `docs/PROGRESS.md` (read its hand-off section first).
- UI follows Material Design 3 (human request): use `frontend/src/components/m3.tsx` and the tokens in `frontend/src/styles.css`.
- Demo areas are cached; after engine changes re-run `backend/.venv/bin/python scripts/preprocess_demo_aoi.py all`.
