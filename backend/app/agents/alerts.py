"""Public alert drafts in the Common Alerting Protocol (CAP 1.2), the format of NDMA's SACHET integrated alert system.

Gemini writes the headline, description, instruction and a 160-character SMS in English and Hindi from the run's facts
only (places, the move-before deadline, reachable shelters, closures); every number must be in the facts and the Hindi
must carry the same digits, else the template text is used. The alert area is the run's flooded extent at the worst hour
(inside the drawn area), as simplified CAP polygons. Severity, urgency and certainty follow CAP definitions from the
results. The message is always status "Draft": an authorised officer issues the real alert through SACHET or the
state's channel after review. Pravah never presents itself as the official sender.
"""
import io
import json
import logging
import re
import uuid
from datetime import datetime, timezone
from xml.etree import ElementTree as ET

import numpy as np
from pydantic import BaseModel, Field

from app.pipeline import facts as F
from app.services import gemini, storage

log = logging.getLogger(__name__)
CAP_NS = "urn:oasis:names:tc:emergency:cap:1.2"
_DIGITS = re.compile(r"\d+(?:\.\d+)?")


class CapText(BaseModel):
    headline: str = Field(description="<= 120 characters")
    description: str = Field(description="what is expected, where and when, 2-3 sentences")
    instruction: str = Field(description="what residents should do, where to go, which roads to avoid, 2-3 sentences")
    sms: str = Field(description="<= 160 characters, plain words, the action and the deadline")


class CapTexts(BaseModel):
    en: CapText
    hi: CapText


PROMPT = """Write a public flood alert for residents, from the FACTS only, in English and in Hindi (Devanagari, same
meaning, Western digits 0-9, the same numbers). Plain words a resident understands. Name the places at risk, the deadline
to move (from move_before; use the clock time if given), where to go (reachable shelters or assembly points by name) and
roads or bridges to avoid. Never say "safe" or "will flood"; say "expected" or "likely". No ids like C1 or S9. Only
numbers that appear in the facts. The SMS must be at most 160 characters.

FACTS:
{facts}
"""


def _numbers_ok(text: str, vals: list[float]) -> bool:
    return all(F._ok_number(n, vals) for n in F._numbers(text))


def _template(facts: dict, area_name: str) -> CapTexts:
    sc = facts.get("scenario", {})
    places = ", ".join(dict.fromkeys(c["place"] for c in facts.get("clusters", [])[:4] if c.get("place"))) or area_name
    sh = ", ".join(s["name"] for s in facts.get("shelters", [])[:3] if s.get("assigned"))
    when = sc.get("move_before") or "as soon as possible"
    en = CapText(headline=f"Flood alert (draft): {area_name}",
                 description=f"Heavy rain is expected to cause flooding in {places}. {sc.get('label', '')}".strip(),
                 instruction=f"Residents of {places} should move {when}{' to ' + sh if sh else ' to higher ground'}. Avoid flooded roads and river banks.",
                 sms=f"Flood alert {area_name}: move {when}{' to ' + sh.split(',')[0] if sh else ''}. Avoid river banks."[:160])
    hi = CapText(headline=f"बाढ़ चेतावनी (मसौदा): {area_name}", description=f"भारी वर्षा से {places} में बाढ़ की आशंका है।",
                 instruction=f"{places} के निवासी {when} ऊँचे स्थान या आश्रय में जाएँ। बाढ़ वाली सड़कों और नदी किनारों से दूर रहें।",
                 sms=f"बाढ़ चेतावनी {area_name}: {when} सुरक्षित ऊँचे स्थान पर जाएँ। नदी किनारे न जाएँ।"[:160])
    return CapTexts(en=en, hi=hi)


def alert_polygons(run: dict, area, max_polys: int = 5, min_depth_m: float = 0.1) -> list[list[tuple[float, float]]]:
    """Flooded extent at the worst hour inside the drawn area, as up to `max_polys` simplified rings of (lat, lon)."""
    import geopandas as gpd
    from rasterio.features import shapes
    from rasterio.transform import Affine
    from shapely.geometry import shape
    from shapely.ops import unary_union
    from scipy.ndimage import binary_dilation
    d = np.load(io.BytesIO(storage.get_run(run["run_id"], "depth.npz")))["depth"].astype(np.float32)
    worst = np.nan_to_num(d.max(axis=0))
    m = worst >= min_depth_m
    if area.aoi_mask is not None:
        m &= area.aoi_mask
    if not m.any():
        return []
    m = binary_dilation(m, iterations=2)
    g = area.grid
    tr = Affine(g.cell, 0, g.x0, 0, -g.cell, g.y0)
    geoms = [shape(s) for s, v in shapes(m.astype(np.uint8), mask=m, transform=tr) if v == 1]
    u = unary_union(geoms).buffer(60).simplify(40)
    polys = sorted(list(u.geoms) if hasattr(u, "geoms") else [u], key=lambda p: -p.area)[:max_polys]
    out = []
    for p in gpd.GeoSeries(polys, crs=g.crs).to_crs("EPSG:4326"):
        ring = [(round(y, 5), round(x, 5)) for x, y in p.exterior.coords]
        out.append(ring)
    return out


def cap_levels(run: dict, facts: dict) -> dict:
    people = int(run.get("people_to_evacuate") or 0)
    mb = facts.get("scenario", {}).get("move_before_hour")
    severity = "Extreme" if people >= 1000 else "Severe" if people >= 100 else "Moderate" if people > 0 else "Minor"
    urgency = "Immediate" if mb is not None and mb <= 2 else "Expected"
    src = (run.get("params") or {}).get("rain_source")
    certainty = "Likely" if src == "forecast" else "Possible"  # worst cases, records and IMD presets are what-ifs
    return {"severity": severity, "urgency": urgency, "certainty": certainty}


def draft(run: dict, area, area_name: str) -> dict:
    facts = F.build_facts(run)
    vals = F._fact_numbers(list(facts.get("key_numbers", [])) + list(F.fact_index(facts).values()), facts) + list(range(0, 25))
    texts, by = None, "template"
    try:
        t: CapTexts = gemini.generate_json(PROMPT.format(facts=json.dumps(facts, separators=(",", ":"), ensure_ascii=False)), CapTexts,
                                           tier="fast", temperature=0.2)
        ok = all(_numbers_ok(getattr(t.en, k), vals) for k in ("headline", "description", "instruction", "sms"))
        same = all(sorted(_DIGITS.findall(getattr(t.en, k))) == sorted(_DIGITS.findall(getattr(t.hi, k))) for k in ("description", "instruction", "sms"))
        if ok and same:
            t.en.sms, t.hi.sms = t.en.sms[:160], t.hi.sms[:160]
            texts, by = t, "gemini"
        else:
            log.info("alert text rejected: numbers ok=%s, Hindi digits same=%s", ok, same)
    except Exception as e:  # noqa: BLE001
        log.warning("alert text fell back to the template: %s", e)
    texts = texts or _template(facts, area_name)
    polys = alert_polygons(run, area)
    places = list(dict.fromkeys(c["place"] for c in facts.get("clusters", []) if c.get("place")))[:8]
    return {"run_id": run["run_id"], "created_at": datetime.now(timezone.utc).isoformat(), "by": by,
            "model": gemini.model_name("fast") if by == "gemini" else None, "texts": texts.model_dump(), "polygons": polys,
            "area_desc": ", ".join(places) or area_name, **cap_levels(run, facts), "identifier": f"pravah-{run['run_id']}-{uuid.uuid4().hex[:6]}"}


def cap_xml(a: dict, area_name: str) -> bytes:
    """CAP 1.2 document (status Draft) with one info block per language."""
    ET.register_namespace("", CAP_NS)
    q = lambda t: f"{{{CAP_NS}}}{t}"  # noqa: E731
    root = ET.Element(q("alert"))
    for k, v in (("identifier", a["identifier"]), ("sender", "pravah-decision-support@draft.invalid"),
                 ("sent", datetime.fromisoformat(a["created_at"]).replace(microsecond=0).isoformat()), ("status", "Draft"),
                 ("msgType", "Alert"), ("scope", "Public"),
                 ("note", "Draft generated by the Pravah decision-support prototype from a model scenario. Not an official alert: "
                          "review, edit and issue only through SACHET or the authorised state channel.")):
        ET.SubElement(root, q(k)).text = v
    for lang, code in (("en", "en-IN"), ("hi", "hi-IN")):
        t = a["texts"][lang]
        info = ET.SubElement(root, q("info"))
        for k, v in (("language", code), ("category", "Met"), ("event", "Flood" if lang == "en" else "बाढ़"),
                     ("responseType", "Evacuate"), ("urgency", a["urgency"]), ("severity", a["severity"]), ("certainty", a["certainty"]),
                     ("senderName", f"Pravah draft for {area_name} (not an official alert)"), ("headline", t["headline"]),
                     ("description", t["description"]), ("instruction", t["instruction"])):
            ET.SubElement(info, q(k)).text = v
        p = ET.SubElement(info, q("parameter"))
        ET.SubElement(p, q("valueName")).text = "SMS"
        ET.SubElement(p, q("value")).text = t["sms"]
        ar = ET.SubElement(info, q("area"))
        ET.SubElement(ar, q("areaDesc")).text = a["area_desc"]
        for ring in a["polygons"]:
            ET.SubElement(ar, q("polygon")).text = " ".join(f"{la},{lo}" for la, lo in ring)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)
