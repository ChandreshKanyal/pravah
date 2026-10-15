"""Gemini agents (S14). Engines compute; agents convert language to parameters, call tools and narrate.

ADK reads the Vertex AI settings from the environment, so set them from config before any agent is built.
"""
import os

from app.config import get_settings

_s = get_settings()
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "TRUE" if _s.google_genai_use_vertexai else "FALSE")
os.environ.setdefault("GOOGLE_CLOUD_PROJECT", _s.google_cloud_project)
os.environ.setdefault("GOOGLE_CLOUD_LOCATION", _s.google_cloud_location)
