from functools import lru_cache

from google import genai
from google.genai import types

from app.config import get_settings

# Vertex AI answers 429 RESOURCE_EXHAUSTED when many calls arrive together (seen live 18 Oct: the fixes list's image
# reviews) and the odd 5xx: retried with exponential back-off and jitter (2, 4, 8 s) instead of failing the step
RETRY = types.HttpRetryOptions(attempts=4, initial_delay=2.0, max_delay=20.0, exp_base=2.0, jitter=1.0,
                               http_status_codes=[408, 429, 500, 502, 503, 504])


@lru_cache
def get_client() -> genai.Client:
    s = get_settings()
    # 120 s per request: a hung call must fail over to the deterministic fallbacks instead of blocking a job
    return genai.Client(vertexai=True, project=s.google_cloud_project, location=s.google_cloud_location,
                        http_options=types.HttpOptions(timeout=120_000, retry_options=RETRY))


def adk_model(name: str | None = None):
    """The model for an ADK agent, with the same retries (ADK builds its own client from a bare model name)."""
    from google.adk.models.google_llm import Gemini
    return Gemini(model=name or get_settings().gemini_model_fast, retry_options=RETRY)


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
