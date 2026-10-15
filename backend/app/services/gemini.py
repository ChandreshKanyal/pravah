from functools import lru_cache

from google import genai
from google.genai import types

from app.config import get_settings


@lru_cache
def get_client() -> genai.Client:
    s = get_settings()
    return genai.Client(vertexai=True, project=s.google_cloud_project, location=s.google_cloud_location)


def generate(prompt: str, tier: str = "fast") -> str:
    """tier 'fast' or 'pro': same model, different thinking level."""
    s = get_settings()
    model = s.gemini_model_pro if tier == "pro" else s.gemini_model_fast
    level = s.gemini_thinking_pro if tier == "pro" else s.gemini_thinking_fast
    r = get_client().models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(thinking_config=types.ThinkingConfig(thinking_level=level)),
    )
    return r.text or ""


def generate_json(contents, schema, tier: str = "fast", temperature: float = 0.2):
    """Structured output: returns an instance of the pydantic `schema` (raises on API or parse errors).
    `contents` may be a prompt string or a list of parts (e.g. an image part plus text)."""
    s = get_settings()
    model = s.gemini_model_pro if tier == "pro" else s.gemini_model_fast
    level = s.gemini_thinking_pro if tier == "pro" else s.gemini_thinking_fast
    r = get_client().models.generate_content(
        model=model,
        contents=contents,
        config=types.GenerateContentConfig(
            temperature=temperature, response_mime_type="application/json", response_schema=schema,
            thinking_config=types.ThinkingConfig(thinking_level=level)),
    )
    if r.parsed is not None:
        return r.parsed
    return schema.model_validate_json(r.text or "")


def model_name(tier: str = "fast") -> str:
    s = get_settings()
    return f"{s.gemini_model_pro if tier == 'pro' else s.gemini_model_fast} (thinking {s.gemini_thinking_pro if tier == 'pro' else s.gemini_thinking_fast})"
