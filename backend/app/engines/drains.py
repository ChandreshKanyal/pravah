"""S13.4 drain and culvert inspection priority (urban). Pure NumPy/Shapely.

priority = 0.4 * norm(log accumulation) + 0.3 * max(fsi, ponding) + 0.3 * norm(exposed people within 300 m),
then +0.3 for a field photo marked blocked (+0.15 partially blocked) and -0.2 for one marked clear.
"""
import numpy as np
from scipy.ndimage import maximum_filter, uniform_filter
from shapely.geometry import LineString, MultiLineString, Point

DRAIN_TYPES = {"drain", "canal", "ditch", "stream", "river"}
PHOTO_ADJ = {"blocked": 0.3, "partially_blocked": 0.15, "clear": -0.2}


def candidates(waterways, roads, spacing_m: float = 250.0) -> list[dict]:
    """Culverts, waterway x road crossings and points every `spacing_m` along drains. Inputs in the grid CRS."""
    out: list[dict] = []
    seen: set[tuple[int, int]] = set()

    def add(x, y, kind, wid, name):
        key = (int(x // 30), int(y // 30))
        if key not in seen:
            seen.add(key)
            nm = "" if name is None or str(name) in ("<NA>", "nan", "None") else str(name)  # OSM tags can be pd.NA
            out.append({"x": float(x), "y": float(y), "type": kind, "waterway_id": str(wid), "name": nm})

    for _, w in waterways.iterrows():
        g = w.geometry
        if g is None or g.is_empty:
            continue
        ww_tag = str(w.get("waterway"))
        kind = "culvert" if str(w.get("tunnel")) == "culvert" else (ww_tag if ww_tag not in ("<NA>", "nan", "None") else "drain")
        if kind not in DRAIN_TYPES and kind != "culvert":
            continue
        lines = list(g.geoms) if isinstance(g, MultiLineString) else [g] if isinstance(g, LineString) else [g.boundary]
        for ln in lines:
            if kind == "culvert":
                p = ln.interpolate(0.5, normalized=True)
                add(p.x, p.y, "culvert", w.get("osmid"), w.get("name"))
                continue
            for d in np.arange(spacing_m / 2, max(ln.length, 1.0), spacing_m):
                p = ln.interpolate(d)
                add(p.x, p.y, kind, w.get("osmid"), w.get("name"))
    if roads is not None and len(roads) and len(waterways):
        ww = waterways[waterways.geometry.notna()]
        idx = roads.sindex
        for _, w in ww.iterrows():
            for j in idx.query(w.geometry, predicate="intersects"):
                inter = w.geometry.intersection(roads.geometry.iloc[j])
                pts = [inter] if isinstance(inter, Point) else list(getattr(inter, "geoms", []))
                for p in pts:
                    if isinstance(p, Point):
                        add(p.x, p.y, "road crossing", w.get("osmid"), w.get("name"))
    return out


def priority(cands: list[dict], rows, cols, acc_cells: np.ndarray, fsi: np.ndarray, ponding_like: np.ndarray,
             exposed_pop_grid: np.ndarray, photo_condition: dict[str, str], cell: float = 30.0, top: int = 20) -> list[dict]:
    """Ranked drain points; `ponding_like` is 0..1 (fill fraction), `exposed_pop_grid` people in wet cells."""
    if not cands:
        return []
    r, c = np.asarray(rows, int), np.asarray(cols, int)
    acc = np.log1p(acc_cells[r, c])
    acc_n = (acc - acc.min()) / ((acc.max() - acc.min()) or 1.0)
    win = max(3, int(round(2 * 300 / cell)) | 1)  # ~600 m box ~ 300 m radius
    pop300 = uniform_filter(np.nan_to_num(exposed_pop_grid).astype(np.float64), size=win, mode="constant") * win * win
    pop = pop300[r, c]
    pop_n = pop / (pop.max() or 1.0)
    pond = maximum_filter(np.nan_to_num(ponding_like).astype(np.float64), size=3)[r, c]  # ponding within ~45 m
    haz = np.maximum(np.nan_to_num(fsi)[r, c], pond)
    score = 0.4 * acc_n + 0.3 * haz + 0.3 * pop_n
    rows_out = []
    for k, cd in enumerate(cands):
        cond = photo_condition.get(cd["waterway_id"])
        s = float(score[k] + PHOTO_ADJ.get(cond, 0.0))
        rows_out.append({**cd, "priority": round(s, 3), "photo_condition": cond, "exposed_people_300m": int(round(pop[k])),
                         "ponding": round(float(pond[k]), 2), "fsi": round(float(np.nan_to_num(fsi)[r[k], c[k]]), 2)})
    rows_out.sort(key=lambda d: -d["priority"])
    for i, d in enumerate(rows_out[:top], start=1):
        d["id"] = f"D{i}"
    return rows_out[:top]
