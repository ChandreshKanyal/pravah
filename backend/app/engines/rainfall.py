"""Rainfall, runoff and timing formulas (S3.2-S3.4, S5.6) and scenario series builders (S10.5). Pure functions."""
import math

import numpy as np

# Dynamic World label -> rational-method runoff coefficient (S3.2). Editable via config.
DW_RUNOFF_C = [1.00, 0.25, 0.35, 0.60, 0.45, 0.40, 0.85, 0.60, 0.50]
# 0 water, 1 trees, 2 grass, 3 flooded_veg, 4 crops, 5 shrub_scrub, 6 built, 7 bare, 8 snow_ice


def runoff_c(lc_class: np.ndarray, table: list[float] = DW_RUNOFF_C) -> np.ndarray:
    """C per cell; NaN where the class is unknown (-1)."""
    lut = np.asarray(table, dtype=np.float32)
    lc = np.asarray(lc_class)
    ok = (lc >= 0) & (lc < len(lut))
    return np.where(ok, lut[np.clip(lc, 0, len(lut) - 1)], np.nan).astype(np.float32)


def rational_q(C, i_mm_h, A_km2):
    """Peak discharge (m3/s) = 0.278 * C * i (mm/h) * A (km2)."""
    return 0.278 * np.asarray(C) * np.asarray(i_mm_h) * np.asarray(A_km2)


def kirpich_tc_min(L_m, S):
    return 0.0195 * np.asarray(L_m, dtype=float) ** 0.77 * np.asarray(S, dtype=float) ** -0.385


def hack_length_km(A_km2):
    return 1.27 * np.asarray(A_km2, dtype=float) ** 0.6


def tc_hours(A_loc_km2, S):
    """Time of concentration (h): Hack flow length + Kirpich, slope clamped to [0.005, 0.5]."""
    L_m = 1000 * hack_length_km(A_loc_km2)
    return kirpich_tc_min(L_m, np.clip(S, 0.005, 0.5)) / 60


def caine_threshold(D_h):
    """Caine (1980) global rainfall intensity-duration landslide threshold (mm/h)."""
    return 14.82 * np.asarray(D_h, dtype=float) ** -0.39


def distribute_total(total_mm: float, duration_h: int, hyetograph: str = "constant") -> list[float]:
    """Spread a rain total over H hours. triangular_front: peak at hour ceil(H/3), linear up and down."""
    H = max(1, int(duration_h))
    if hyetograph == "triangular_front" and H > 1:
        p = math.ceil(H / 3)
        t = np.arange(1, H + 1, dtype=float)
        w = np.where(t <= p, t / p, (H - t + 1) / (H - p + 1))
        return (w / w.sum() * total_mm).tolist()
    return [total_mm / H] * H


def manual_series(intensity_mm_h: float, duration_h: int, hyetograph: str = "constant") -> list[float]:
    """Hourly rain (mm/h) with total = intensity x duration."""
    return distribute_total(float(intensity_mm_h) * max(1, int(duration_h)), duration_h, hyetograph)


def wettest_window(values: list[float], duration_h: int) -> tuple[list[float], int]:
    """Consecutive `duration_h` values with the largest sum (zero-padded if short) and its start index."""
    v = np.asarray(values, dtype=float)
    H = max(1, int(duration_h))
    if len(v) < H:
        v = np.concatenate([v, np.zeros(H - len(v))])
    sums = np.convolve(v, np.ones(H), mode="valid")
    k = int(np.argmax(sums))
    return v[k:k + H].tolist(), k


def day_hours(hourly: list[dict], day: str) -> list[float]:
    """The 24 local hourly precipitation values for `day` (YYYY-MM-DD), zero where missing."""
    out = [0.0] * 24
    for h in hourly:
        if h["local_date"] == day:
            out[int(h["local_hour"]) % 24] = float(h["precip_mm"])
    return out


def worst_day_index(daily: list[dict], hourly: list[dict] | None = None) -> int:
    """Wettest day; with `hourly`, only days that still have hourly forecast values are eligible."""
    if not daily:
        return 0
    covered = {h["local_date"] for h in hourly} if hourly else None
    vals = [d["precip_mm"] if covered is None or d["date"] in covered else -1 for d in daily]
    return int(np.argmax(vals))
