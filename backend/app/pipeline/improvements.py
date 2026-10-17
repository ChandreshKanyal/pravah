"""Pre-monsoon improvements for an area: model-ranked maintenance spots, things open satellite imagery can actually see
(checked by Gemini vision), and waterlogging spots reported on the web (Gemini with Google Search, with citations).

Three steps so the area-preparation screen can show progress: `clogged` (drains, culverts, road low spots, channels,
new construction and bare ground), `congested` (single-exit roads) and `improvements` (web reports, image clips,
Gemini review, ranking). Output: improvements.json plus PNG clips under improvements/.

Imagery rules (SPEC S2): only Copernicus Sentinel-2 and Google Dynamic World (Earth Engine, open data) are analysed or
shown as evidence. Google Maps / Street View content is never sent to Gemini; the UI only links to it for a person to look.
"""
import hashlib
import io
import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from typing import Literal

import numpy as np
import requests
from affine import Affine
from pydantic import BaseModel, Field
from rasterio.features import rasterize

from app.engines import drains as drn
from app.engines import improvements as imp, profile as prof
from app.engines.grid import lonlat_to_rowcol, rowcol_to_lonlat, xy_to_rowcol
from app.services import firestore as fs
from app.services import storage

log = logging.getLogger(__name__)

STEPS = ["clogged", "congested", "improvements"]
ATTRIBUTION = "Contains modified Copernicus Sentinel data; land cover: Google Dynamic World (Earth Engine)"


def _status(aoi_id: str, step: str, state: str) -> None:
    try:
        fs.update_aoi(aoi_id, {f"status.{step}": state})
    except Exception as e:  # progress is cosmetic; never fail the job on it
        log.info("status write failed: %s", e)


def _ctx(aoi_id: str) -> dict:
    doc = fs.get_aoi(aoi_id) or {}
    grid = storage.load_grid(aoi_id)
    h = storage.load_layers(aoi_id, "hydro30")
    pop = storage.load_layers(aoi_id, "population")
    pop_total = np.nan_to_num(pop["pop30"]) + np.nan_to_num(pop.get("pop_unattributed", 0))
    return {"doc": doc, "bbox": tuple(doc["bbox"]), "urban": ((doc.get("meta") or {}).get("profile") or {}).get("urban", doc.get("mode") == "urban"), "name": doc.get("name") or "the area",
            "grid": grid, "hand": h["hand"], "upa": h["upa"], "stream": h["stream"].astype(bool), "ds": h["dist_stream_m"],
            "pop": pop_total.astype(np.float32),
            "rc2ll": lambda r, c: rowcol_to_lonlat(grid, r, c),
            "ll2rc": lambda lon, lat: tuple(int(v) for v in lonlat_to_rowcol(grid, lon, lat))}


def _candidates(aoi_id: str, grid, urban: bool) -> list[dict]:
    if storage.exists(aoi_id, "drain_candidates.json"):  # same candidates, computed at preparation (every area)
        return storage.get_json(aoi_id, "drain_candidates.json")
    if not (storage.exists(aoi_id, "waterways.parquet") and storage.exists(aoi_id, "edges_drive.parquet")):
        return []
    water = storage.load_gdf(aoi_id, "waterways.parquet").to_crs(grid.crs)
    roads = storage.load_gdf(aoi_id, "edges_drive.parquet").to_crs(grid.crs)
    cands = drn.candidates(water, roads) if len(water) else []
    for cd in cands:
        r, c = xy_to_rowcol(grid, cd["x"], cd["y"])
        r, c = int(np.clip(r, 0, grid.height - 1)), int(np.clip(c, 0, grid.width - 1))
        lon, lat = rowcol_to_lonlat(grid, r, c)
        cd.update(row=r, col=c, lon=round(float(lon), 6), lat=round(float(lat), 6))
    return cands


def _to_box(layer: np.ndarray, grid, bg) -> np.ndarray:
    """Sample a 30 m analysis-grid layer at the centres of the 10 m box grid (same CRS)."""
    rows, cols = np.indices((bg.height, bg.width))
    x = bg.x0 + (cols + 0.5) * bg.cell
    y = bg.y0 - (rows + 0.5) * bg.cell
    r = np.clip(((grid.y0 - y) / grid.cell).astype(int), 0, grid.height - 1)
    c = np.clip(((x - grid.x0) / grid.cell).astype(int), 0, grid.width - 1)
    return layer[r, c]


def _channels(aoi_id: str, grid, bg) -> tuple[np.ndarray, np.ndarray]:
    """Mapped open channels wide enough to read at 10 m: OSM rivers and canals, and drains tagged >= 12 m wide."""
    shape = (bg.height, bg.width)
    if not storage.exists(aoi_id, "waterways.parquet"):
        return np.zeros(shape, bool), np.full(shape, "", object)
    ww = storage.load_gdf(aoi_id, "waterways.parquet").to_crs(grid.crs)
    width = np.array([float(re.sub(r"[^0-9.]", "", str(w)) or 0) if w is not None else 0 for w in ww.get("width", [None] * len(ww))])
    kind = ww["waterway"].astype(str).to_numpy()
    tunnel = ww["tunnel"].astype(str).to_numpy() if "tunnel" in ww else np.full(len(ww), "")
    keep = (np.isin(kind, ["river", "canal"]) | ((kind == "drain") & (width >= 12))) & ~np.isin(tunnel, ["culvert", "yes"])  # culverted: grass on top
    ww = ww[keep & ww.geometry.notna().to_numpy()]
    T = Affine(bg.cell, 0, bg.x0, 0, -bg.cell, bg.y0)
    # one pass for all channels (burn value = index + 1; later ways overwrite earlier ones where they cross): drawing each
    # way on its own full-size grid took minutes in a large city
    geoms = list(ww.geometry)
    if not geoms:
        return np.zeros(shape, bool), np.full(shape, "", object)
    idx = rasterize(((g, k + 1) for k, g in enumerate(geoms)), out_shape=shape, transform=T, all_touched=True, dtype="int32")
    mask = idx > 0
    nm = np.array([""] + [imp._nm(v) for v in ww.get("name", [None] * len(ww))], dtype=object)
    names = nm[idx]
    return mask, names


def step_clogged(aoi_id: str) -> None:
    """Drains, culverts and road low spots (model) plus channels, new construction and bare ground (imagery)."""
    from app.services import earth_engine as ees
    x = _ctx(aoi_id)
    grid, bbox, urban = x["grid"], x["bbox"], x["urban"]
    wtype: dict = {}
    if storage.exists(aoi_id, "waterways.parquet"):
        ww = storage.load_gdf(aoi_id, "waterways.parquet")
        wtype = {str(o): str(t) for o, t in zip(ww["osmid"], ww["waterway"])}
    items = imp.culverts(_candidates(aoi_id, grid, urban), x["hand"], x["upa"], x["pop"], grid.cell, bbox, urban, wtype)
    if storage.exists(aoi_id, "pluvial.npz"):  # every area; only built-up hollows (engines/profile.py)
        dist_road = storage.load_layers(aoi_id, "derived")["dist_road_m"]
        pl_ = storage.load_layers(aoi_id, "pluvial")
        use = prof.built_hollows(pl_, storage.load_layers(aoi_id, "landcover")["lc_class"])
        items += imp.low_spots(pl_, dist_road, x["pop"], x["rc2ll"], grid.cell, bbox, urban, use=use)
    notes: list[str] = []
    imagery: dict = {}
    try:
        L = ees.improvement_layers(grid, bbox)
        bg, arr = L["grid"], L["arrays"]
        bl = lambda r, c: rowcol_to_lonlat(bg, r, c)  # noqa: E731
        hand_b, ds_b = _to_box(x["hand"], grid, bg), _to_box(x["ds"], grid, bg)
        channel, names = _channels(aoi_id, grid, bg)
        items += imp.choked_channels(arr, channel, names, bl, L["recent"], urban)
        items += imp.new_construction(arr, hand_b, ds_b, bl, urban)
        items += imp.new_bare(arr, hand_b, ds_b, bl, urban)
        imagery = {"recent": list(L["recent"]), "early": list(L["early"]), "now": list(L["built_now_window"])}
        if not channel.any():
            notes.append("No mapped river or canal wide enough to check from space (narrow drains are not visible at 10 m).")
        elif not (imp.water_seen(channel, arr["water_occ"]) * channel >= imp.WATER_SEEN_PCT).any():
            notes.append("The mapped canals and streams here were never seen holding water from space (JRC, since 1984), so they are"
                         " too narrow to check at 10 m; check them on site before the rains.")
    except Exception as e:
        log.exception("improvement imagery failed")
        notes.append(f"Satellite checks unavailable this time ({e.__class__.__name__}); model-ranked items only.")
    storage.put_json(aoi_id, "improvements/_clogged.json", {"items": items, "notes": notes, "imagery": imagery})


def step_congested(aoi_id: str) -> None:
    x = _ctx(aoi_id)
    items: list[dict] = []
    if storage.exists(aoi_id, "G_drive.graphml"):
        G = storage.load_graph(aoi_id, "G_drive.graphml")
        items = imp.single_exits(G, x["hand"], x["stream"], x["pop"], x["ll2rc"], x["rc2ll"], x["bbox"], x["urban"])
    storage.put_json(aoi_id, "improvements/_congested.json", {"items": items})


# ---------- web reports (Gemini + Google Search) ----------
REPORT_PROMPT = """Search the web first (do not answer from memory). List specific places in or right next to {place} (bounding box west,south,east,north = {bbox}) that are
repeatedly reported as waterlogging or flooding spots when it rains: junctions, subways, underpasses, roads, colonies,
markets, bridges. Use municipal flooding-spot lists and news reports. Return JSON only:
[{{"place": "<specific name a map can find>", "what": "<= 25 words on what happens there and why, as reported",
"last_reported": "YYYY or YYYY-MM", "source_urls": ["..."]}}]
Only places with a source URL that names them. No general areas (a whole suburb or city). At most 10, most often reported first."""

GENERIC = {"road", "marg", "west", "east", "north", "south", "colony", "nagar", "station", "bridge", "area", "near", "stretch",
           "mumbai", "junction", "chowk", "market", "subway", "lane", "street", "main"}
PRECISE = {"route", "intersection", "point_of_interest", "establishment", "premise", "transit_station", "neighborhood",
           "sublocality_level_2", "sublocality_level_3", "train_station", "bus_station", "park", "natural_feature"}


def _geocode(q: str, bbox) -> dict | None:
    """Display-only position from the Maps Geocoding API, biased to the box; vague results (a whole locality) dropped."""
    from app.services.weather import maps_server_key
    w, s, e, n = bbox
    try:
        r = requests.get("https://maps.googleapis.com/maps/api/geocode/json", timeout=10,
                         params={"address": q, "bounds": f"{s},{w}|{n},{e}", "region": "in", "key": maps_server_key()})
        for res in r.json().get("results") or []:
            if PRECISE & set(res.get("types", [])):
                loc = res["geometry"]["location"]
                return {"lat": loc["lat"], "lng": loc["lng"], "formatted": res.get("formatted_address", "")}
    except Exception as ex:
        log.info("geocode failed for %s: %s", q, ex)
    return None


_web: dict = {}  # aoi_id -> Future of the web search, started when preparation starts
_web_pool = ThreadPoolExecutor(max_workers=2)


def _search(name: str, bbox) -> tuple[str, str, list]:
    from app.agents import historian
    return historian.search(name, [round(v, 4) for v in bbox], REPORT_PROMPT)


def prefetch_reported(aoi_id: str, name: str, bbox) -> None:
    """Start the web search (Gemini + Google Search, 60-115 s on 18 Oct, most of the fixes analysis) as soon as area
    preparation starts: it needs only the name and box, so it runs alongside the downloads and is usually done when
    the area is ready."""
    if aoi_id not in _web:
        _web[aoi_id] = _web_pool.submit(_search, name, bbox)


def reported(x: dict, aoi_id: str) -> tuple[list[dict], list[dict], str]:
    fut = _web.pop(aoi_id, None)
    try:
        text, entry, sources = fut.result() if fut else _search(x["name"], x["bbox"])
    except Exception as e:  # noqa: BLE001  the early search failed: try once more now
        log.info("early web search failed (%s); searching again", e)
        text, entry, sources = _search(x["name"], x["bbox"])
    m = re.search(r"\[.*\]", text or "", re.S)
    try:
        raw = json.loads(m.group(0)) if m else []
    except json.JSONDecodeError:
        raw = []
    out = []
    pl = storage.load_layers(aoi_id, "pluvial") if storage.exists(aoi_id, "pluvial.npz") else None
    # a link counts only if its site is among the pages Google Search returned to the model (grounding chunks name the
    # site); a URL the model wrote from memory could be invented
    sites = {re.sub(r"^www\.", "", (s.get("title") or "").lower().strip()) for s in sources if s.get("title")}

    def grounded(u: str) -> bool:
        host = re.sub(r"^www\.", "", re.sub(r"^https?://", "", u.lower()).split("/")[0])
        return any(host == d or host.endswith("." + d) for d in sites if "." in d)

    def opens(u: str, place: str) -> bool:
        """Otherwise the page must open and name the place (a distinctive word of it)."""
        words = [w for w in re.findall(r"[a-z]{4,}", place.lower()) if w not in GENERIC]
        try:
            r = requests.get(u, timeout=8, headers={"user-agent": "Mozilla/5.0 (Pravah citation check)"})
            return r.status_code == 200 and (not words or any(w in r.text.lower() for w in words))
        except Exception:
            return False

    def links(it: dict) -> list[str]:
        cand = [u for u in (it.get("source_urls") or []) if isinstance(u, str) and u.startswith("http")][:4]
        return [u for u in cand if grounded(u) or opens(u, str(it.get("place", "")))][:3]

    raw = raw if isinstance(raw, list) else []
    with ThreadPoolExecutor(max_workers=6) as ex:
        checked = list(ex.map(links, raw))
    for it, urls in zip(raw, checked):
        place = str(it.get("place", ""))[:80]
        if not urls or not place:
            continue
        g = _geocode(f"{place}, {x['name']}", x["bbox"])
        if not g or not imp.in_box(g["lng"], g["lat"], x["bbox"]):
            continue
        r, c = x["ll2rc"](g["lng"], g["lat"])
        hand = float(np.nan_to_num(x["hand"][r, c], nan=99))
        hollow = pl is not None and float(np.max(pl["dep_depth"][max(0, r - 3):r + 4, max(0, c - 3):c + 4])) >= 0.2
        agrees = hand <= 3 or hollow
        why = [f"Reported: {str(it.get('what', ''))[:200]}" + (f" (last reported {it['last_reported']})" if it.get("last_reported") else ""),
               ("Our terrain model agrees: " + ("a hollow in the road surface nearby" if hollow else f"low ground, about {hand:.1f} m above the drainage"))
               if agrees else "Our terrain model shows no low ground here, so the cause is more likely blocked or undersized drains"]
        item = imp._item("reported", g["lng"], g["lat"], 1.0 if agrees else 0.7, why,
                         "Clean the drains and inlets around this spot before the next heavy rain and keep a pump and traffic diversion ready.",
                         x["urban"], place=place, basis="web", numbers={"hand_m": round(hand, 1), "model_agrees": agrees},
                         confidence="medium")
        item["sources"] = [{"title": "", "uri": u} for u in urls]
        out.append(item)
    return imp.dedupe(out, 150)[:8], sources[:12], entry


# ---------- image clips and Gemini vision review ----------
class Review(BaseModel):
    centre: Literal["channel with open water", "channel with vegetation or silt", "road or railway", "fields or crops",
                    "buildings", "trees", "bare ground", "other"] = Field(description="What is inside the ring now (in the most recent image), judged from the wider view first")
    channel_visible: bool = Field(description="True only if a distinct channel (a continuous strip with banks, wider than about 20 m) passes through the ring")
    verdict: Literal["visible", "not_visible", "unclear"]
    seen: str = Field(description="What is at the centre of the images, at most 30 words, only what the pixels show")


REVIEW_PROMPT = """You are checking satellite evidence for a pre-monsoon maintenance list used by district officials.
The images are Sentinel-2, 10 m per pixel; each caption says how wide it is. The point in question is inside the ring at
the centre of every image. Look at the wider view first to see what the place is (a river, a canal, a road, fields, a
town), then at the close-ups.
{captions}
Claim to check: {claim}
At 10 m per pixel nothing narrower than about 20 m can be seen (no drains, rubbish piles, vehicles or people), so judge
only what the pixels can show. A straight green line through farmland is usually a tree-lined road, canal bank or field
edge, not weeds in a channel. Answer "visible" only if the images clearly show the claim at the centre, "not_visible"
if they contradict it (open dark water where vegetation is claimed, a road or fields where a channel is claimed, or no
change between before and after), and "unclear" otherwise. Do not guess causes you cannot see."""


def _ring(png: bytes) -> bytes:
    from PIL import Image, ImageDraw
    im = Image.open(io.BytesIO(png)).convert("RGB")
    d = ImageDraw.Draw(im)
    w, h = im.size
    r = max(10, w // 16)
    for k, col in ((3, (0, 0, 0)), (1, (255, 255, 255))):
        d.ellipse([w / 2 - r - k, h / 2 - r - k, w / 2 + r + k, h / 2 + r + k], outline=col, width=2)
    buf = io.BytesIO()
    im.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def _clips(aoi_id: str, it: dict, imagery: dict) -> list[tuple[str, str, bytes]]:
    """(key, caption, png) clips for an imagery item."""
    from app.services import earth_engine as ees
    lon, lat = it["lon"], it["lat"]
    base = hashlib.sha1(f"{it['category']}{lon}{lat}".encode()).hexdigest()[:10]
    out = []
    # a 2 km view first (what the place is: river, canal, road, fields), then 600 m close-ups; 600 m alone made a
    # tree-lined road or field edge look like a green channel, to Gemini and to people
    if it["category"] == "choked_channel":
        win = tuple(imagery["recent"][:2])
        out.append((f"{base}_wide", f"Wider view, about 2 km across, {win[0]} to {win[1]}", ees.s2_chip(lon, lat, win, half_m=1000, px=500)))
        out.append((f"{base}_rgb", "Close-up, about 600 m across, true colour", ees.s2_chip(lon, lat, win)))
        out.append((f"{base}_fcc", "Close-up, false colour (vegetation shows red)", ees.s2_chip(lon, lat, win, false_colour=True)))
    else:
        before = ("2016-11-01", "2017-05-31")
        y = date.today().year if date.today().month >= 6 else date.today().year - 1
        after = (f"{y - 1}-11-01", f"{y}-05-31")
        out.append((f"{base}_wide", f"Wider view, about 2 km across, dry season {after[0][:4]}–{after[1][:4]}", ees.s2_chip(lon, lat, after, half_m=1000, px=500, l1c=True)))
        out.append((f"{base}_before", f"Before: dry season {before[0][:4]}–{before[1][:4]}, about 600 m across", ees.s2_chip(lon, lat, before, l1c=True)))
        out.append((f"{base}_after", f"After: dry season {after[0][:4]}–{after[1][:4]}, about 600 m across", ees.s2_chip(lon, lat, after, l1c=True)))
    res = []
    for key, cap, png in out:
        png = _ring(png)
        storage.put_bytes(aoi_id, f"improvements/{key}.png", png, "image/png")
        res.append((key, cap, png))
    return res


def _review(it: dict, clips: list[tuple[str, str, bytes]]) -> Review | None:
    from google.genai import types
    from app.services import gemini
    caps = "\n".join(f"Image {i + 1}: {c}" for i, (_, c, _) in enumerate(clips))
    claim = it["why"][0]
    if it["category"] == "choked_channel":
        claim += (". The vegetation must be on the surface of the open channel itself; green banks, grass or trees beside it,"
                  " or a channel that is covered or runs underground here, do not count")
    elif it["category"] == "encroachment":
        claim += ". The 'after' image must show new buildings, paving or fill at the centre that are absent in the 'before' image"
    elif it["category"] == "bare_ground":
        claim += ". The 'after' image must show bare earth, debris or muck at the centre that is absent in the 'before' image"
    parts = [types.Part.from_bytes(data=png, mime_type="image/png") for _, _, png in clips]
    parts.append(types.Part(text=REVIEW_PROMPT.format(captions=caps, claim=claim)))
    try:
        return gemini.generate_json(parts, Review, tier="fast", temperature=0.0)
    except Exception as e:
        log.info("gemini review failed: %s", e)
        return None


def step_finish(aoi_id: str) -> dict:
    from app.services import gemini
    x = _ctx(aoi_id)
    cl = storage.get_json(aoi_id, "improvements/_clogged.json") if storage.exists(aoi_id, "improvements/_clogged.json") else {"items": [], "notes": [], "imagery": {}}
    co = storage.get_json(aoi_id, "improvements/_congested.json") if storage.exists(aoi_id, "improvements/_congested.json") else {"items": []}
    items, notes, imagery = cl["items"] + co["items"], list(cl.get("notes", [])), cl.get("imagery", {})
    sources, entry = [], ""
    try:
        rep, sources, entry = reported(x, aoi_id)
        items += rep
        if not rep:
            notes.append("No specific waterlogging spots inside the box were found in web reports.")
    except Exception as e:
        log.exception("reported spots failed")
        notes.append(f"Web search for reported spots unavailable this time ({e.__class__.__name__}).")

    def check(it: dict) -> dict | None:
        if it["basis"] != "imagery" or not imagery:
            return it
        try:
            clips = _clips(aoi_id, it, imagery)
        except Exception as e:
            log.info("clip failed: %s", e)
            return it
        it["images"] = [{"key": k, "caption": c, "url": f"/api/aoi/{aoi_id}/improvements/img/{k}.png"} for k, c, _ in clips]
        rv = _review(it, clips)
        if rv is None:
            return it
        it["ai"] = {"verdict": rv.verdict, "seen": rv.seen[:240], "centre": rv.centre, "model": gemini.model_name("fast")}
        # keep only what Gemini confirms; "unsure" leads were mostly false (tree rows, roads, fields), and a crew sent
        # on a false lead costs more than a missed one, which the site walk still finds. A channel lead also needs a
        # channel Gemini can see at the centre.
        if rv.verdict != "visible":
            return None
        # and what is at the centre now must be what the claim says is there
        need = {"choked_channel": {"channel with vegetation or silt"}, "encroachment": {"buildings", "bare ground", "road or railway"},
                "bare_ground": {"bare ground"}}.get(it["category"])
        if need and rv.centre not in need:
            return None
        if it["category"] == "choked_channel" and not rv.channel_visible:
            return None
        it["confidence"] = "medium"
        return it

    with ThreadPoolExecutor(max_workers=8) as ex:  # each lead: 3 Earth Engine clips + one Gemini review
        checked = list(ex.map(check, items))
    dropped = sum(1 for c in checked if c is None)
    items = imp.rank([c for c in checked if c is not None])
    if dropped:
        notes.append(f"Gemini dropped {dropped} satellite lead{'s' if dropped > 1 else ''} it could not confirm from the images.")
    counts: dict[str, int] = {}
    for it in items:
        counts[it["category"]] = counts.get(it["category"], 0) + 1
    out = {"aoi_id": aoi_id, "generated_at": datetime.now(timezone.utc).isoformat(), "items": items, "counts": counts,
           "notes": notes, "imagery": imagery, "attribution": ATTRIBUTION, "sources": sources, "search_entry_point": entry,
           "categories": {k: v["title"] for k, v in imp.CATS.items()}}
    storage.put_json(aoi_id, "improvements.json", out)
    return out


RUNNING: set[str] = set()  # areas whose improvements are being computed in this process


def start(aoi_id: str) -> bool:
    """Compute in a background thread (once per area at a time). False if already running."""
    import threading
    if aoi_id in RUNNING:
        return False
    RUNNING.add(aoi_id)

    def job():
        try:
            build(aoi_id)
        except Exception:
            log.exception("improvements failed for %s", aoi_id)
        finally:
            RUNNING.discard(aoi_id)
    threading.Thread(target=job, daemon=True).start()
    return True


def build(aoi_id: str) -> dict:
    """All three steps (for areas prepared before this feature, or a refresh), with status updates."""
    for name, fn in (("clogged", step_clogged), ("congested", step_congested), ("improvements", step_finish)):
        _status(aoi_id, name, "running")
        try:
            res = fn(aoi_id)
            _status(aoi_id, name, "ready")
        except Exception:
            log.exception("improvements %s failed", name)
            _status(aoi_id, name, "error")
            raise
    return res
