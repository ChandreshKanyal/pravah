"""Storm-drain design capacity for an area's city, found by Gemini with Google Search (17 Oct). This is the most
uncertain number in the waterlogging model (25 mm/h default, Mumbai's historical standard), and it is local knowledge
that terrain data cannot give. The finding is only a suggestion: it needs a cited source and a person's confirmation
before any run uses it, and the run records the value it used."""
import json
import re

import requests

from app.agents import historian
from app.services import firestore as fs, places, storage

PROMPT = """Using web search (not memory), find the design capacity of the storm-water drainage network of the city or
municipality that contains {place} (bounding box {bbox}), in millimetres of rain per hour. Prefer official sources:
the municipal corporation, the state government, the CPHEEO manual, CAG or court reports, or news quoting officials.
If the network is being upgraded, give the capacity of the existing network today and the planned value separately.
Reply with JSON only:
{{"city": "...", "mm_h": <the EXISTING network's design capacity in mm/h, as stated by a source>, "planned_mm_h": <planned
upgrade in mm/h or null>, "basis": "one sentence on what the source says", "source_urls": ["https://..."],
"confidence": "high" | "medium" | "low"}}
mm_h must be filled whenever a source states the existing design capacity (for example "designed for 25 mm per hour"
gives 25). Use null only when no source states a number. Give the URLs of the pages that state it."""


def _place(aoi_id: str, doc: dict) -> str:
    names = []
    if doc.get("name") and not doc["name"].lower().startswith(("unnamed", "area ")):
        names.append(doc["name"])
    try:
        names += [p["name"] for p in places.area_places(aoi_id, storage.load_grid(aoi_id))[:4] if p.get("name")]
    except Exception:  # places are a hint only
        pass
    return ", ".join(dict.fromkeys(names)) or "this place"


def _opens(url: str, city: str) -> bool:
    """The page opens and mentions the city and drainage."""
    if not url.startswith("http"):
        return False
    try:
        r = requests.get(url, timeout=8, headers={"User-Agent": "Mozilla/5.0 (Pravah source check)"})
        t = r.text.lower() if r.ok else ""
    except requests.RequestException:
        return False
    word = (city.split()[0] if city else "").lower()
    return bool(t) and (not word or word in t) and ("drain" in t)


def lookup(aoi_id: str) -> dict:
    """Two independent searches: a figure is offered only when they agree within 20% (answers vary between calls:
    Guwahati came back as 7 and as 30 mm/h). Disagreement is reported with both figures for a person to check."""
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(2) as ex:
        a, b = ex.map(lambda _: _once(aoi_id), range(2))
    if a["found"] and b["found"]:
        lo, hi = sorted([a["mm_h"], b["mm_h"]])
        if hi > 1.2 * lo:
            return {**a, "found": False, "mm_h": None, "candidates": [a, b],
                    "note": f"Searches disagree ({lo:g} vs {hi:g} mm/h); check the sources before entering a value."}
        return {**a, "sources": (a["sources"] + [x for x in b["sources"] if x not in a["sources"]])[:6], "agreed": 2}
    return a if a["found"] else b if b["found"] else a


def _once(aoi_id: str) -> dict:
    """{found, city, mm_h, planned_mm_h, basis, confidence, sources, search_entry_point} (nothing is saved)."""
    doc = fs.get_aoi(aoi_id) or {}
    w, s, e, n = doc.get("bbox") or (0, 0, 0, 0)
    text, entry, sources = historian.search(_place(aoi_id, doc), f"{w:.3f},{s:.3f},{e:.3f},{n:.3f}", PROMPT)
    m = re.search(r"\{.*\}", text or "", re.S)
    try:
        d = json.loads(m.group(0)) if m else {}
    except json.JSONDecodeError:
        d = {}
    v = d.get("mm_h")
    city = d.get("city") or ""
    # a figure counts only with a source: a page Google Search returned (grounding), or a URL the model gave that opens
    # and names the city (grounding metadata is sometimes empty; a URL from memory could be invented)
    urls = [u for u in (d.get("source_urls") or [])[:5] if isinstance(u, str)]
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(5) as ex:  # each check can wait 8 s; one after another that was up to 40 s
        opens = list(ex.map(lambda u: _opens(u, city), urls))
    checked = [{"uri": u, "title": re.sub(r"^https?://(www\.)?", "", u).split("/")[0]} for u, ok in zip(urls, opens) if ok]
    srcs = (sources or []) + [c for c in checked if c["uri"] not in {x.get("uri") for x in sources or []}]
    ok = isinstance(v, (int, float)) and 5 <= v <= 150 and bool(srcs)
    return {"found": ok, "city": city, "mm_h": float(v) if ok else None,
            "planned_mm_h": d.get("planned_mm_h") if isinstance(d.get("planned_mm_h"), (int, float)) else None,
            "basis": d.get("basis") or "", "confidence": d.get("confidence") or "low",
            "sources": srcs[:6], "search_entry_point": entry,
            "note": "" if ok else "No sourced figure found; the default (25 mm/h) stays."}
