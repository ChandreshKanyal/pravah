# Pravah

Flood and landslide decision-support prototype (Google AI Builder Cup 2026).
Decision-support draft for human review, not a prediction or an order.

- Spec: `docs/SPEC.md` · Config: `docs/CONFIG.md` · Progress: `docs/PROGRESS.md`
- Backend: `uv venv --python 3.12 backend/.venv && uv pip install --python backend/.venv/bin/python -r backend/requirements.txt`
- Run: `cd backend && .venv/bin/uvicorn app.main:app --reload`
