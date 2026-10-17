"""One model for every area (replaces the river / urban mode switch, 17 Oct). Every area gets every hazard model; which
physics applies where is decided per cell and per channel from the data, never by a label or by AI:

- river flooding (HAND stage) only on reliable channels: not tidal (a channel at sea level is set by the sea, not by
  rain runoff) and not a one-cell stub (no cross-section for a rating curve); a channel whose stage hits the top of
  its rating curve in a run is dropped for that run;
- waterlogging (ponding above storm-drain capacity) only in hollows whose catchment is mostly built-up: that is where
  storm drains exist and where water standing in streets matters; in fields and forest the rain soaks in (runoff C);
- the flood depth is the deeper of the river and the waterlogging depth in each cell (compound flooding).

The profile below describes the area from the same data; it sets defaults (ground conditioning for the flow model,
3D height exaggeration) and words, and never switches a hazard off.
"""
import numpy as np

BUILT = 6                # Dynamic World class "built"
BUILT_HOLLOW = 0.3       # share of a hollow's catchment that must be built-up for it to waterlog
URBAN_SHARE = 0.3        # built-up share of the area that makes it a city
TIDAL_M = 1.5            # channels lying entirely this close to sea level are tidal
STEEP_DEG = 15.0


URBAN_DRAIN_KM2 = 100.0  # below this catchment, a mostly built-up channel is part of the storm-drain system
URBAN_DRAIN_BUILT = 0.5


def reliable_reaches(reaches: list[dict], built_share: np.ndarray | None = None) -> np.ndarray:
    """True for channels where rain-driven river stage (Manning rating curves on the 90 m HAND) is meaningful: not
    tidal, not a one-cell stub, and not an urban drainage channel (a nallah under 100 km2 draining mostly built-up
    land: engineered walls and beds the 90 m terrain cannot see; its overflow is street waterlogging, modelled with
    the drain capacity, so counting it again as river flooding would double it)."""
    tidal = np.array([max(r.get("e_up", 99) or 0, r.get("e_down", 99) or 0) <= TIDAL_M for r in reaches], bool)
    stub = np.array([len(r.get("cells", [])) <= 1 for r in reaches], bool)
    nallah = np.zeros(len(reaches), bool)
    if built_share is not None:
        a_up = np.array([r.get("A_up_km2", 0) or 0 for r in reaches], float)
        nallah = (a_up < URBAN_DRAIN_KM2) & (np.asarray(built_share) >= URBAN_DRAIN_BUILT)
    return ~(tidal | stub | nallah)


def built_hollows(pluvial: dict, lc_class: np.ndarray, share: float = BUILT_HOLLOW) -> np.ndarray:
    """Per depression (index 0 = none): True where at least `share` of the cells draining into it are built-up."""
    ws = np.asarray(pluvial["ws_label"]).ravel()
    n = len(pluvial["v_dep"])
    built = (np.asarray(lc_class).ravel() == BUILT).astype(float)
    cells = np.bincount(ws, minlength=n)[:n]
    b = np.bincount(ws, weights=built, minlength=n)[:n]
    ok = b / np.maximum(cells, 1) >= share
    ok[0] = False
    return ok


def area_profile(slope_deg: np.ndarray, lc_class: np.ndarray, mask: np.ndarray | None, reaches: list[dict],
                 hollows_ok: np.ndarray | None = None, reach_ok: np.ndarray | None = None) -> dict:
    """What kind of place this is and which hazards the data says can occur, with a one-line description."""
    m = np.ones(np.shape(slope_deg), bool) if mask is None else np.asarray(mask, bool)
    s = np.nan_to_num(np.asarray(slope_deg, float))[m]
    lc = np.asarray(lc_class)[m]
    built = float((lc == BUILT).mean()) if lc.size else 0.0
    p50, p90 = (float(x) for x in np.percentile(s, [50, 90])) if s.size else (0.0, 0.0)
    steep = float((s >= STEEP_DEG).mean()) if s.size else 0.0
    ok = (reach_ok if reach_ok is not None else reliable_reaches(reaches)) if reaches else np.zeros(0, bool)
    a_up = max((r.get("A_up_km2", 0) for r, k in zip(reaches, ok) if k), default=0.0)
    nallahs = int(len(reaches) - ok.sum()) if reaches else 0
    tidal = bool(reaches) and bool((~ok).any()) and any(max(r.get("e_up", 99) or 0, r.get("e_down", 99) or 0) <= TIDAL_M for r in reaches)
    urban, hilly, flat = built >= URBAN_SHARE, p90 >= STEEP_DEG, p50 < 3.0
    hazards = []
    if ok.any():
        hazards.append("river")
    if hollows_ok is not None and hollows_ok.any():
        hazards.append("waterlogging")
    river = ("a major river" if a_up >= 1000 else "a river" if a_up >= 50 else "streams") if ok.any() else None
    place = "Dense city" if built >= 0.6 else "Town" if urban else "Hill area" if hilly else "Rural area"
    head = f"{place}{' on ' + river if river else ''}{' with steep slopes' if hilly and place != 'Hill area' else ''}"
    words = {"river": "river flooding", "waterlogging": "waterlogging"}
    line = head + (" · " + ", ".join(words[h] for h in hazards) if hazards else "")
    if urban and not ok.any() and reaches:
        line += " · channels act as storm drains"
    if tidal:
        line += " · tides not modelled"
    return {"built_share": round(built, 3), "slope_p50": round(p50, 1), "slope_p90": round(p90, 1),
            "steep_share": round(steep, 3), "largest_river_km2": round(float(a_up), 1), "tidal": tidal,
            "urban": urban, "hilly": hilly, "flat": flat, "hazards": hazards, "channels_river_physics": int(ok.sum()),
            "channels_other": nallahs, "summary": line}


def _hr(d: np.ndarray, v: np.ndarray) -> np.ndarray:
    """Flood hazard rating to people (DEFRA/EA FD2321): depth x (speed + 0.5) + 0.5 debris factor above 25 cm."""
    return d * (v + 0.5) + np.where(d > 0.25, 0.5, 0.0)


def evac_depths(reaches: list[dict], reach_id: np.ndarray, still: np.ndarray | None, n: float = 0.04,
                hr_ordinary: float = 0.75, hr_fragile: float = 0.65) -> tuple[np.ndarray, np.ndarray]:
    """Depth (m) at which people in a cell are in danger, for ordinary and fragile buildings, from one physical rule
    for every area: the FD2321 hazard rating reaches "danger for some" (0.75; 0.65 for fragile structures). River
    water moves at the Manning speed of its channel, v = R^(2/3) S^(1/2) / n with R ~ depth; standing water (street
    waterlogging) has v = 0, which gives the 0.5 m / 0.3 m still-water thresholds. Moving river water reaches danger
    at about 0.26-0.3 m (the debris term starts at 25 cm). Replaces "any wet building moves" (5 cm), which was set
    for Himalayan torrents and moved most of Kurla for ankle-deep, slow water."""
    d = np.arange(0.01, 3.0, 0.01)

    def first(v: np.ndarray, thr: float) -> float:
        k = np.flatnonzero(_hr(d, v) >= thr)
        return float(d[k[0]]) if len(k) else 3.0

    S = np.array([max(float(r.get("S") or 0.001), 0.001) for r in reaches] or [0.001])
    v = (d[None, :] ** (2 / 3)) * np.sqrt(S[:, None]) / n
    ordn = np.array([first(v[i], hr_ordinary) for i in range(len(S))])
    frag = np.array([first(v[i], hr_fragile) for i in range(len(S))])
    still_o, still_f = first(np.zeros_like(d), hr_ordinary), first(np.zeros_like(d), hr_fragile)
    rid = np.asarray(reach_id)
    safe = np.clip(rid, 0, len(S) - 1)
    o = np.where(rid >= 0, ordn[safe], still_o).astype(np.float32)
    f = np.where(rid >= 0, frag[safe], still_f).astype(np.float32)
    if still is not None:
        o = np.where(still, still_o, o)
        f = np.where(still, still_f, f)
    return o, f
