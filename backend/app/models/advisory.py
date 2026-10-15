from typing import Literal

from pydantic import BaseModel, Field

DISCLAIMER = ("Decision-support draft, not a prediction or an order. Pravah uses simplified, uncalibrated planning models "
              "(HAND flood mapping, rational-method runoff, susceptibility indices). Results are estimates for planning and "
              "must be reviewed by qualified officials before any action.")


class Recommendation(BaseModel):
    id: str = ""  # "R1"..; assigned after validation
    horizon: Literal["immediate", "seasonal", "structural"]
    priority: Literal["P1", "P2", "P3"]
    action: str  # imperative, <= 25 words
    location_label: str
    evidence_ids: list[str]  # MUST reference ids present in the facts JSON
    why: str  # <= 40 words, cites numbers from facts
    confidence: Literal["low", "medium", "high"]
    lonlat: list[float] | None = None  # filled from the first evidence item with a location (fly-to)


class RecDraft(BaseModel):
    horizon: Literal["immediate", "seasonal", "structural"]
    priority: Literal["P1", "P2", "P3"]
    action: str = Field(description="imperative, at most 25 words")
    location_label: str
    evidence_ids: list[str] = Field(description="ids that exist in the facts JSON")
    why: str = Field(description="at most 40 words; every number must appear in the cited facts")
    confidence: Literal["low", "medium", "high"]


class AdvisoryDraft(BaseModel):
    """What Gemini returns (response_schema); ids, disclaimer and provenance are added by the server."""
    headline: str = Field(description="at most 30 words")
    recommendations: list[RecDraft]
    limitations: list[str]


class Advisory(BaseModel):
    advisory_id: str
    run_id: str
    headline: str  # <= 30 words
    key_numbers: list[dict]  # {label, value, unit, evidence_id}
    recommendations: list[Recommendation]
    limitations: list[str]
    disclaimer: str = DISCLAIMER  # exact string from SPEC 2.4
    generated_by: Literal["gemini", "rules_fallback"]
    dropped: list[dict] = []  # recommendations removed by the validator, with the reason (audit trail)
    model: str = ""
