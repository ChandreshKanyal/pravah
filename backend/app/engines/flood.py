"""HAND flood mapping with an hourly worst-case envelope (S3.1, S3.6-S3.8). Pure NumPy."""
import numpy as np

from app.engines.hydrology import src_stage
from app.engines.rainfall import areal_reduction_factor, rational_q

HAND_MAX_M = 30.0
PERM_WATER_OCC = 90.0  # gsw_occ above this is permanent water, not flood
WET_M = 0.05


def permanent_water(gsw_occ: np.ndarray) -> np.ndarray:
    return np.nan_to_num(gsw_occ) > PERM_WATER_OCC


def depth_from_stage(hand: np.ndarray, stage, perm: np.ndarray | None = None) -> np.ndarray:
    """depth = clip(stage - hand, 0) where hand < 30; permanent water -> NaN. `stage` may be a grid."""
    hand = np.asarray(hand, dtype=np.float32)
    d = np.clip(np.asarray(stage, dtype=np.float32) - hand, 0, None)
    d = np.where(np.nan_to_num(hand, nan=HAND_MAX_M) < HAND_MAX_M, d, 0).astype(np.float32)
    if perm is not None:
        d[perm] = np.nan
    return d


def hourly_envelope(rain_mm_h, tc_h, C, A_loc_km2, src: list[dict], river_offset_m: float = 0.0,
                    inflow_m3s=0.0, arf: bool = False) -> tuple[np.ndarray, np.ndarray]:
    """Stage h[r, t] and discharge Q[r, t] per reach and hour; stage never recedes (worst-case envelope).

    With `arf`, the point intensity is reduced to a catchment-average one (TP-29 areal reduction factor over the
    averaging window), as is standard when applying the rational method beyond a few km2.
    """
    i = np.asarray(rain_mm_h, dtype=float)
    H, R = len(i), len(src)
    tc = np.asarray(tc_h, dtype=float)
    cs = np.concatenate([[0.0], np.cumsum(i)])
    Q = np.zeros((R, H))
    h = np.zeros((R, H))
    prev = np.full(R, -np.inf)
    for t in range(1, H + 1):
        W = np.clip(np.round(tc), 1, t).astype(int)
        i_eff = (cs[t] - cs[t - W]) / W
        if arf:
            i_eff = i_eff * areal_reduction_factor(A_loc_km2, W)
        ramp = np.minimum(1.0, t / np.maximum(tc, 1e-6))
        q = rational_q(C, i_eff, A_loc_km2) * ramp + inflow_m3s
        stage = np.array([src_stage(src[r], q[r]) for r in range(R)]) + river_offset_m
        stage = np.maximum(stage, prev)
        Q[:, t - 1], h[:, t - 1], prev = q, stage, stage
    return h, Q


def depth_stack(h: np.ndarray, reach_id_30: np.ndarray, hand: np.ndarray, perm: np.ndarray | None = None) -> np.ndarray:
    """Depth per hour [H, rows, cols] from per-reach stage via a lookup on reach_id_30 (no loops over cells)."""
    rid = np.asarray(reach_id_30)
    has = rid >= 0
    safe = np.where(has, rid, 0)
    out = np.empty((h.shape[1],) + rid.shape, np.float32)
    for t in range(h.shape[1]):
        stage = np.where(has, h[safe, t], -np.inf)
        out[t] = depth_from_stage(hand, stage, perm)
    return out


def flooded_area_km2(depth: np.ndarray, cell: float = 30.0) -> float:
    return float(np.count_nonzero(np.nan_to_num(depth) > WET_M) * cell**2 / 1e6)
