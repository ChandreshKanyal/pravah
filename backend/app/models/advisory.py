from typing import Literal

from pydantic import BaseModel, Field

DISCLAIMER = ("Decision-support draft, not a prediction or an order. Pravah uses simplified, uncalibrated planning models "
              "(HAND flood mapping, rational-method runoff, susceptibility indices). Results are estimates for planning and "
              "must be reviewed by qualified officials before any action.")


# Indian district response departments (Incident Response System line departments); every action gets one owner
DEPARTMENTS = ("District Magistrate / DDMA", "SDM / Tehsildar (Revenue)", "Police", "SDRF / NDRF", "PWD (roads and bridges)",
               "Health (CMO, 108 ambulance)", "Municipal body (drains, water-logging)", "Irrigation / Flood control",
               "Education (school shelters)", "Block Development Officer", "Fire and Emergency Services",
               "Border Roads Organisation")
Department = Literal["District Magistrate / DDMA", "SDM / Tehsildar (Revenue)", "Police", "SDRF / NDRF",
                     "PWD (roads and bridges)", "Health (CMO, 108 ambulance)", "Municipal body (drains, water-logging)",
                     "Irrigation / Flood control", "Education (school shelters)", "Block Development Officer",
                     "Fire and Emergency Services", "Border Roads Organisation"]


# fixed Hindi terms (hand-checked) for departments and headline figures; free text is translated by Gemini
DEPARTMENTS_HI = {
    "District Magistrate / DDMA": "ज़िलाधिकारी / DDMA", "SDM / Tehsildar (Revenue)": "SDM / तहसीलदार (राजस्व)", "Police": "पुलिस",
    "SDRF / NDRF": "SDRF / NDRF", "PWD (roads and bridges)": "लोक निर्माण विभाग (सड़क व पुल)",
    "Health (CMO, 108 ambulance)": "स्वास्थ्य (CMO, 108 एम्बुलेंस)", "Municipal body (drains, water-logging)": "नगर निकाय (नाले, जलभराव)",
    "Irrigation / Flood control": "सिंचाई / बाढ़ नियंत्रण", "Education (school shelters)": "शिक्षा (स्कूल आश्रय)",
    "Block Development Officer": "खंड विकास अधिकारी", "Fire and Emergency Services": "अग्निशमन एवं आपात सेवाएँ",
    "Border Roads Organisation": "सीमा सड़क संगठन (BRO)"}
KEY_LABELS_HI = {"K7": "जिन लोगों को हटाना है", "K3": "जिन्हें आश्रय स्थल नहीं मिल रहा", "K4": "बंद होने वाले पुल",
                 "K1": "बाढ़ के पानी में लोग (अधिकतम)", "K6": "भूस्खलन-संवेदनशील ढलानों पर लोग", "K2": "उच्च/गंभीर जोखिम वाले भवन",
                 "K5": "सबसे बुरे घंटे में बाढ़ क्षेत्र"}


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
    owner: str = ""  # responsible department (DEPARTMENTS)
    act_by_hour: int | None = None  # deadline = start of this scenario hour (1 = before the rain starts)
    act_by: str = ""  # human deadline: "before hour 4 (03:00)", "before the monsoon", ...


class RecDraft(BaseModel):
    horizon: Literal["immediate", "seasonal", "structural"]
    priority: Literal["P1", "P2", "P3"]
    action: str = Field(description="imperative, at most 25 words")
    location_label: str
    evidence_ids: list[str] = Field(description="ids that exist in the facts JSON")
    why: str = Field(description="at most 40 words; every number must appear in the cited facts")
    confidence: Literal["low", "medium", "high"]
    owner: Department = Field(description="the one department responsible for this action")


class AdvisoryDraft(BaseModel):
    """What Gemini returns (response_schema); ids, disclaimer and provenance are added by the server."""
    headline: str = Field(description="situation summary for the District Magistrate, at most 40 words, place names not ids")
    recommendations: list[RecDraft]
    limitations: list[str]


class Advisory(BaseModel):
    advisory_id: str
    run_id: str
    headline: str  # bottom line (deterministic): who moves, from where, by when, shelter gap
    summary: str = ""  # Gemini's situation summary (validated numbers), shown under the headline
    key_numbers: list[dict]  # {label, value, unit, evidence_id, rounded, range, note}
    recommendations: list[Recommendation]
    limitations: list[str]
    disclaimer: str = DISCLAIMER  # exact string from SPEC 2.4
    generated_by: Literal["gemini", "rules_fallback"]
    dropped: list[dict] = []  # recommendations removed by the validator, with the reason (audit trail)
    model: str = ""
    start_local: str | None = None  # clock time of hour 1, when the scenario comes from a forecast
    evac_window_h: int | None = None
    breakdown: dict = {}  # people who need to move by reason
    supplies: list[dict] = []  # {item, quantity, unit, basis} for the central estimate and the high end
    supply_days: int = 3
    version: int = 1
    review: dict = {}  # {state: draft|reviewed|approved, by, role, at, note}
