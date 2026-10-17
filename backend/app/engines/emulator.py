"""AI emulator of the 2D flow model (pure NumPy/SciPy, no I/O).

The shallow-water model (engines/swe.py) takes about a minute per scenario. The emulator learns, per area, the map of
peak flood depth as a function of the storm from a space-filling set of model runs, and answers in milliseconds:

- Reduced-order model: peak depths (square-root transformed) of the cells that are ever wet are decomposed into
  principal patterns by SVD (proper orthogonal decomposition); a few patterns carry almost all the variance.
- Regression: the pattern weights are a smooth function of storm features (rain in excess of the storm-drain capacity,
  total and in the peak hour; total; duration; river level), learnt with radial-basis-function interpolation (thin-plate spline with smoothing) on standardised
  features.
- Validation: leave-one-out over the training runs. Each run is predicted by an emulator that never saw it and
  scored against the model: critical success index of the wet area (>= 5 cm) and depth error on wet cells.

Outside the trained range the emulator clamps the features to the range and says so; it never extrapolates silently.
"""
import numpy as np
from scipy.interpolate import RBFInterpolator

WET_M = 0.05
ENERGY = 0.999
MAX_MODES = 12
FEATURES = ["excess_mm", "excess_peak_mm_h", "total_mm", "duration_h", "river_offset_m"]


def features(rain_mm_h: list[float], river_offset_m: float = 0.0, drain_mm_h: float = 0.0) -> np.ndarray:
    """Storm features. Rain the drains carry away never floods a street, so the excess over the drain capacity (zero
    in river mode) leads; the total and duration still matter for river flow and soaking."""
    r = np.asarray(rain_mm_h, float)
    ex = np.clip(r - drain_mm_h, 0, None)
    return np.array([ex.sum(), ex.max(initial=0), r.sum(), len(r), river_offset_m], float)


class Emulator:
    def __init__(self, X: np.ndarray, Y: np.ndarray, shape: tuple[int, int], smoothing: float = 1e-3):
        """X: (n, f) storm features; Y: (n, H*W) peak depth (m) of each training run."""
        self.X, self.shape, self.smoothing = np.asarray(X, float), tuple(shape), smoothing
        Y = np.sqrt(np.clip(np.asarray(Y, np.float32), 0, None))
        self.idx = np.flatnonzero((Y >= np.sqrt(WET_M)).any(axis=0))  # cells wet in at least one run
        Yw = Y[:, self.idx].astype(np.float64)
        self.mean = Yw.mean(axis=0)
        U, S, Vt = np.linalg.svd(Yw - self.mean, full_matrices=False)
        e = np.cumsum(S**2) / max(float((S**2).sum()), 1e-12)
        self.k = int(min(MAX_MODES, np.searchsorted(e, ENERGY) + 1, len(S)))
        self.basis = Vt[: self.k]  # (k, cells)
        self.coef = U[:, : self.k] * S[: self.k]  # (n, k)
        self.energy = float(e[self.k - 1]) if len(e) else 1.0
        self.lo, self.hi = self.X.min(axis=0), self.X.max(axis=0)
        span = np.where(self.hi - self.lo > 1e-9, self.hi - self.lo, 1.0)
        self.scale = span
        self.active = _active(self.X, self.lo, self.scale)
        Z = self._z(self.X)
        self.rbf = RBFInterpolator(Z, self.coef, kernel="thin_plate_spline", smoothing=smoothing, degree=1)

    def _z(self, X: np.ndarray) -> np.ndarray:
        return ((np.atleast_2d(X) - self.lo) / self.scale)[:, self.active]

    def clamp(self, x: np.ndarray) -> tuple[np.ndarray, list[str]]:
        x = np.asarray(x, float).copy()
        out = [FEATURES[i] for i in range(len(x)) if self.active[i] and not (self.lo[i] - 1e-6 <= x[i] <= self.hi[i] + 1e-6)]
        return np.clip(x, self.lo, self.hi), out

    def predict(self, x: np.ndarray) -> np.ndarray:
        """Peak depth (m) on the full grid for storm features x (clamped to the trained range)."""
        x, _ = self.clamp(x)
        c = self.rbf(self._z(x))[0]
        s = np.clip(self.mean + c @ self.basis, 0, None)
        out = np.zeros(self.shape[0] * self.shape[1], np.float32)
        out[self.idx] = s**2
        return out.reshape(self.shape)

    # persistence: the SVD and training features are stored; the RBF is refitted on load (milliseconds)
    def state(self) -> dict:
        return {"X": self.X, "shape": np.array(self.shape), "idx": self.idx.astype(np.int32), "mean": self.mean.astype(np.float32),
                "basis": self.basis.astype(np.float32), "coef": self.coef, "energy": np.array(self.energy),
                "smoothing": np.array(self.smoothing)}

    @classmethod
    def from_state(cls, st: dict) -> "Emulator":
        em = cls.__new__(cls)
        em.X, em.shape, em.smoothing = np.asarray(st["X"], float), tuple(int(v) for v in st["shape"]), float(st["smoothing"])
        em.idx, em.mean, em.basis = np.asarray(st["idx"]), np.asarray(st["mean"], np.float64), np.asarray(st["basis"], np.float64)
        em.coef, em.energy, em.k = np.asarray(st["coef"], float), float(st["energy"]), int(np.asarray(st["basis"]).shape[0])
        em.lo, em.hi = em.X.min(axis=0), em.X.max(axis=0)
        em.scale = np.where(em.hi - em.lo > 1e-9, em.hi - em.lo, 1.0)
        em.active = _active(em.X, em.lo, em.scale)
        em.rbf = RBFInterpolator(em._z(em.X), em.coef, kernel="thin_plate_spline", smoothing=em.smoothing, degree=1)
        return em


def _active(X: np.ndarray, lo: np.ndarray, scale: np.ndarray) -> np.ndarray:
    """Features used by the regression: ones that vary (river level never varies in a city) and are not a copy of an
    earlier one (with no drains, rain in excess of the drains is the rain itself)."""
    Z = (X - lo) / scale
    act = (X.max(axis=0) - X.min(axis=0)) > 1e-9
    for j in range(X.shape[1]):
        if act[j] and any(act[i] and np.allclose(Z[:, i], Z[:, j], atol=1e-9) for i in range(j)):
            act[j] = False
    return act


def score(pred: np.ndarray, truth: np.ndarray, mask: np.ndarray | None = None) -> dict:
    """CSI of the wet area (>= 5 cm), and mean absolute / RMS depth error on cells wet in either map."""
    m = np.ones(truth.shape, bool) if mask is None else mask
    a, b = (pred >= WET_M) & m, (truth >= WET_M) & m
    inter, union = int((a & b).sum()), int((a | b).sum())
    u = a | b
    err = (pred - truth)[u]
    return {"csi": inter / union if union else 1.0, "mae_m": float(np.abs(err).mean()) if err.size else 0.0,
            "rmse_m": float(np.sqrt((err**2).mean())) if err.size else 0.0, "wet_cells": int(b.sum())}


def leave_one_out(X: np.ndarray, Y: np.ndarray, shape, mask: np.ndarray | None = None) -> list[dict]:
    out = []
    for i in range(len(X)):
        keep = np.arange(len(X)) != i
        em = Emulator(X[keep], Y[keep], shape)
        s = score(em.predict(X[i]), Y[i].reshape(shape), mask)
        _, outside = em.clamp(X[i])
        out.append({**s, "outside_range": outside})
    return out


def threshold_mm(em: Emulator, depth_at, duration_h: int, shape_fn, river_offset_m: float = 0.0,
                 lo: float = 5.0, hi: float | None = None, tol: float = 2.0, drain_mm_h: float = 0.0) -> float | None:
    """Smallest storm total (mm in `duration_h` hours) for which depth_at(peak depth grid) is True, by bisection on the
    emulator (the response grows with rain); None if not reached within the trained range."""
    hi = hi if hi is not None else float(em.hi[2])
    f = lambda P: bool(depth_at(em.predict(features(shape_fn(P, duration_h), river_offset_m, drain_mm_h))))  # noqa: E731
    if not f(hi):
        return None
    if f(lo):
        return lo
    while hi - lo > tol:
        mid = 0.5 * (lo + hi)
        lo, hi = (lo, mid) if f(mid) else (mid, hi)
    return hi
