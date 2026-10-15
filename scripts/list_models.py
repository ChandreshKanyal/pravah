"""List Gemini models visible on Vertex AI. Usage:
  backend/.venv/bin/python scripts/list_models.py [location]
Project comes from GOOGLE_CLOUD_PROJECT, location from argv[1] or GOOGLE_CLOUD_LOCATION (default global).
Needs Application Default Credentials: gcloud auth application-default login
"""
import os
import sys

from google import genai

project = os.environ.get("GOOGLE_CLOUD_PROJECT", "project-0fd9c4ae-bf90-452f-a80")
location = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("GOOGLE_CLOUD_LOCATION", "global")

client = genai.Client(vertexai=True, project=project, location=location)
names = sorted(m.name for m in client.models.list() if "gemini" in (m.name or "").lower())
print(f"project={project} location={location} gemini_models={len(names)}")
for n in names:
    print(n)
