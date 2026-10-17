"""2D shallow-water flow model (dynamic wave): water depth and velocity on the 30 m analysis grid through the storm.

Equations (depth-averaged 2D shallow water / Saint-Venant, conservative form):
    h_t + (hu)_x + (hv)_y = R
    (hu)_t + (hu^2 + g h^2 / 2)_x + (huv)_y = -g h z_x - g n^2 u |U| / h^(1/3)
    (hv)_t + (huv)_x + (hv^2 + g h^2 / 2)_y = -g h z_y - g n^2 v |U| / h^(1/3)

Numerics (finite volume, first-order Godunov type, explicit, unsplit):
- HLL approximate Riemann solver (Harten, Lax & van Leer 1983) with the transverse momentum upwinded by the mass flux
  (the contact wave of HLLC, Toro 2001);
- hydrostatic reconstruction with subcell bed limiting (Chen & Noelle 2017): well-balanced (still water stays still
  over any terrain), depth-positive, wetting and drying, and the full slope force for thin films running down steep
  hillsides (the original reconstruction of Audusse et al. 2004 caps it at g h^2 / 2 per cell);
- Manning friction solved implicitly (exact root of the implicit quadratic, as in Xia & Liang 2018), stable for thin
  films on steep slopes;
- adaptive time step at CFL 0.45 over the sum of x and y wave speeds (positivity of the unsplit scheme);
- free outflow at the grid edge (bed slope extended into the ghost cell, never above the edge cell); an inward flux
  becomes a wall, so no water enters through the edge.

Sources: rain on every cell (hourly intensity x the runoff coefficient C used by the rational method; minus the
storm-drain capacity in urban mode) and river inflow where reaches enter the grid. Compiled with numba.
"""
import heapq
import math
import time
from dataclasses import dataclass, field

import numpy as np
from numba import njit, prange

G = 9.81
H_DRY = 1e-6  # m: below this a cell holds no velocity
H_WET = 0.05  # m: flooded, as in the HAND map (flood.WET_M)
H_SHOW = 0.01  # m: frames store depth from 1 cm; thinner rain films are not drawn
H_CODE = 10.0  # m: depth coding range (sqrt scale, 8 bits)
U_CODE = 8.0  # m/s: velocity coding range (signed sqrt scale, 8 bits)
U_CAP = 25.0  # m/s: guard against spurious speeds in near-dry cells
CFL = 0.45
DT_MAX = 5.0

# Manning n by Dynamic World class (water, trees, grass, flooded_veg, crops, shrub_scrub, built, bare, snow_ice):
# Chow (1959) and the HEC-RAS 2D land-cover table; built-up is an area-averaged value for blocks of buildings.
MANNING_DW = [0.035, 0.10, 0.035, 0.07, 0.04, 0.06, 0.08, 0.03, 0.02]


@njit(cache=True, fastmath=True, inline="always")
def _flux(hl, ul, vl, zl, hr, ur, vr, zr):
    """Normal flux across one interface: (mass, momentum for the left cell, momentum for the right cell, transverse).

    The bed-slope source of each half cell is folded into its own momentum flux (Chen & Noelle 2017)."""
    wl = zl + hl
    wr = zr + hr
    zs = min(max(zl, zr), min(wl, wr))
    hls = max(0.0, min(wl - zs, hl))
    hrs = max(0.0, min(wr - zs, hr))
    fh = 0.0
    fu = 0.0
    fv = 0.0
    if hls > H_DRY or hrs > H_DRY:
        cl = math.sqrt(G * hls)
        cr = math.sqrt(G * hrs)
        if hls <= H_DRY:
            sl = ur - 2.0 * cr
            sr = ur + cr
        elif hrs <= H_DRY:
            sl = ul - cl
            sr = ul + 2.0 * cl
        else:
            sl = min(ul - cl, ur - cr)
            sr = max(ul + cl, ur + cr)
        ql = hls * ul
        qr = hrs * ur
        pl = ql * ul + 0.5 * G * hls * hls
        pr = qr * ur + 0.5 * G * hrs * hrs
        if sl >= 0.0:
            fh, fu = ql, pl
        elif sr <= 0.0:
            fh, fu = qr, pr
        else:
            fh = (sr * ql - sl * qr + sl * sr * (hrs - hls)) / (sr - sl)
            fu = (sr * pl - sl * pr + sl * sr * (qr - ql)) / (sr - sl)
        fv = fh * (vl if fh > 0.0 else vr)
    return fh, fu - 0.5 * G * (hls + hl) * (zl - zs), fu + 0.5 * G * (hr + hrs) * (zs - zr), fv


@njit(cache=True, fastmath=True, inline="always")
def _edge(h, un, ut, z, z_in, outward):
    """Free outflow through a grid edge: the ghost cell holds the edge cell's water on the bed slope extended outward,
    never higher than the edge cell, and moves outward only. An inward flux becomes a wall (no water enters).
    `outward` is +1 when leaving the grid means positive normal velocity. Returns (mass, momentum, transverse)."""
    zg = min(2.0 * z - z_in, z)
    if outward > 0:
        a = _flux(h, un, ut, z, h, max(un, 0.0), ut, zg)
        if a[0] < 0.0:
            return 0.0, 0.5 * G * h * h, 0.0
        return a[0], a[1], a[3]
    a = _flux(h, min(un, 0.0), ut, zg, h, un, ut, z)
    if a[0] > 0.0:
        return 0.0, 0.5 * G * h * h, 0.0
    return a[0], a[2], a[3]


@njit(parallel=True, cache=True, fastmath=True)
def _fluxes(h, u, v, z, FXh, FXuL, FXuR, FXv, FYh, FYvL, FYvR, FYu):
    ny, nx = h.shape
    for r in prange(ny):
        for i in range(nx + 1):
            if i == 0:
                e = _edge(h[r, 0], u[r, 0], v[r, 0], z[r, 0], z[r, 1], -1)
                FXh[r, i] = e[0]
                FXuL[r, i] = e[1]
                FXuR[r, i] = e[1]
                FXv[r, i] = e[2]
            elif i == nx:
                c = nx - 1
                e = _edge(h[r, c], u[r, c], v[r, c], z[r, c], z[r, c - 1], 1)
                FXh[r, i] = e[0]
                FXuL[r, i] = e[1]
                FXuR[r, i] = e[1]
                FXv[r, i] = e[2]
            else:
                a = _flux(h[r, i - 1], u[r, i - 1], v[r, i - 1], z[r, i - 1], h[r, i], u[r, i], v[r, i], z[r, i])
                FXh[r, i] = a[0]
                FXuL[r, i] = a[1]
                FXuR[r, i] = a[2]
                FXv[r, i] = a[3]
    # y runs down the rows (south); normal velocity v, transverse u
    for r in prange(ny + 1):
        for c in range(nx):
            if r == 0:
                e = _edge(h[0, c], v[0, c], u[0, c], z[0, c], z[1, c], -1)
                FYh[r, c] = e[0]
                FYvL[r, c] = e[1]
                FYvR[r, c] = e[1]
                FYu[r, c] = e[2]
            elif r == ny:
                k = ny - 1
                e = _edge(h[k, c], v[k, c], u[k, c], z[k, c], z[k - 1, c], 1)
                FYh[r, c] = e[0]
                FYvL[r, c] = e[1]
                FYvR[r, c] = e[1]
                FYu[r, c] = e[2]
            else:
                b = _flux(h[r - 1, c], v[r - 1, c], u[r - 1, c], z[r - 1, c], h[r, c], v[r, c], u[r, c], z[r, c])
                FYh[r, c] = b[0]
                FYvL[r, c] = b[1]
                FYvR[r, c] = b[2]
                FYu[r, c] = b[3]


@njit(parallel=True, cache=True, fastmath=True)
def _update(h, hu, hv, u, v, n2, rate, dt, dx, dy, t, FXh, FXuL, FXuR, FXv, FYh, FYvL, FYvR, FYu,
            hmax, vmax, hrmax, t_arr, smax_row, clip_row):
    ny, nx = h.shape
    for r in prange(ny):
        smax = 0.0
        clip = 0.0
        for c in range(nx):
            hn = h[r, c] - dt / dx * (FXh[r, c + 1] - FXh[r, c]) - dt / dy * (FYh[r + 1, c] - FYh[r, c]) + dt * rate[r, c]
            qx = hu[r, c] - dt / dx * (FXuL[r, c + 1] - FXuR[r, c]) - dt / dy * (FYu[r + 1, c] - FYu[r, c])
            qy = hv[r, c] - dt / dx * (FXv[r, c + 1] - FXv[r, c]) - dt / dy * (FYvL[r + 1, c] - FYvR[r, c])
            if hn <= H_DRY:
                if hn < 0.0:
                    clip -= hn
                    hn = 0.0
                qx = 0.0
                qy = 0.0
            else:
                m = math.sqrt(qx * qx + qy * qy)
                if m > 0.0:  # implicit Manning: |q|' = 2|q| / (1 + sqrt(1 + 4 a |q|)), a = dt g n^2 / h^(7/3)
                    a = dt * G * n2[r, c] / (hn * hn * np.cbrt(hn))
                    k = 2.0 / (1.0 + math.sqrt(1.0 + 4.0 * a * m))
                    qx *= k
                    qy *= k
            h[r, c] = hn
            uu = 0.0
            vv = 0.0
            if hn > H_DRY:
                uu = qx / hn
                vv = qy / hn
                sp = math.sqrt(uu * uu + vv * vv)
                if sp > U_CAP:
                    uu *= U_CAP / sp
                    vv *= U_CAP / sp
                    qx = uu * hn
                    qy = vv * hn
                c0 = math.sqrt(G * hn)
                s = (abs(uu) + c0) / dx + (abs(vv) + c0) / dy
                if s > smax:
                    smax = s
                if hn > hmax[r, c]:
                    hmax[r, c] = hn
                if hn >= H_WET:
                    if sp > vmax[r, c]:
                        vmax[r, c] = sp
                    # flood hazard rating HR = d (v + 0.5) + DF (DEFRA/EA FD2321), debris factor 0.5 above 0.25 m
                    hr = hn * (min(sp, U_CAP) + 0.5) + (0.5 if hn > 0.25 else 0.0)
                    if hr > hrmax[r, c]:
                        hrmax[r, c] = hr
                    if t_arr[r, c] < 0.0:
                        t_arr[r, c] = t
            hu[r, c] = qx
            hv[r, c] = qy
            u[r, c] = uu
            v[r, c] = vv
        smax_row[r] = smax
        clip_row[r] = clip


@dataclass
class FlowResult:
    frame_s: int
    frames: list[np.ndarray]  # each uint8 [3, rows, cols]: depth code, east velocity code, north velocity code
    hmax: np.ndarray  # m
    vmax: np.ndarray  # m/s where depth >= 5 cm
    hazard: np.ndarray  # max hazard rating (FD2321)
    t_arrival_s: np.ndarray  # first time depth >= 5 cm, -1 never
    stats: dict = field(default_factory=dict)


def encode_frame(h: np.ndarray, u: np.ndarray, v_south: np.ndarray) -> np.ndarray:
    """8-bit planes: depth sqrt-coded from 1 cm (0 = dry), velocities signed-sqrt-coded (128 = still), v north-up."""
    show = h >= H_SHOW
    d = np.where(show, np.clip(np.rint(255 * np.sqrt(np.clip(h, 0, H_CODE) / H_CODE)), 1, 255), 0).astype(np.uint8)

    def vel(x):
        s = np.sign(x) * np.sqrt(np.clip(np.abs(x), 0, U_CODE) / U_CODE)
        return np.where(show, np.clip(np.rint(128 + 127 * s), 1, 255), 128).astype(np.uint8)

    return np.stack([d, vel(u), vel(-v_south)])


def decode_depth(code: np.ndarray) -> np.ndarray:
    return H_CODE * (code.astype(np.float32) / 255) ** 2


def simulate(dem: np.ndarray, cell: float, runoff_c: np.ndarray, manning: np.ndarray, rain_mm_h, drain_mm_h: float | np.ndarray = 0.0,
             sources: list[dict] | None = None, frame_s: int = 300, progress=None, tail_h: float = 0.0) -> FlowResult:
    """Run the storm on the grid. `sources`: [{rows, cols, q: [m3/s per hour]}] inflows spread over their cells.
    Rain beyond the series is zero; the run lasts len(rain_mm_h) + tail_h hours (the tail lets water from uphill arrive
    after the rain stops, where the peak often comes). Frames every `frame_s` seconds, frame 0 dry."""
    z = np.asarray(dem, np.float64)
    if np.isnan(z).any():  # holes take the nearest valid height
        from scipy import ndimage
        idx = ndimage.distance_transform_edt(np.isnan(z), return_distances=False, return_indices=True)
        z = z[tuple(idx)]
    ny, nx = z.shape
    dx = dy = float(cell)
    rain = np.asarray(rain_mm_h, float)
    T = (len(rain) + max(0.0, float(tail_h))) * 3600.0
    C = np.clip(np.nan_to_num(np.asarray(runoff_c, np.float64), nan=0.5), 0.0, 1.0)
    n2 = np.asarray(manning, np.float64) ** 2
    h, hu, hv, u, v = (np.zeros((ny, nx)) for _ in range(5))
    FXh, FXuL, FXuR, FXv = (np.zeros((ny, nx + 1)) for _ in range(4))
    FYh, FYvL, FYvR, FYu = (np.zeros((ny + 1, nx)) for _ in range(4))
    hmax, vmax, hrmax = np.zeros((ny, nx)), np.zeros((ny, nx)), np.zeros((ny, nx))
    t_arr = np.full((ny, nx), -1.0)
    smax_row, clip_row = np.zeros(ny), np.zeros(ny)
    src_cells = [(np.asarray(s["rows"]), np.asarray(s["cols"]), np.asarray(s["q"], float)) for s in (sources or [])]

    def rate_at(hour: int, t: float) -> np.ndarray:
        i = rain[hour] if hour < len(rain) else 0.0
        out = C * np.maximum(0.0, i - drain_mm_h) / 3.6e6  # drain capacity: a number, or a grid (built-up cells only)
        for rr, cc, q in src_cells:
            qh = q[min(hour, len(q) - 1)] * min(1.0, t / 3600.0)  # ramp the inflow in over the first hour
            out[rr, cc] += qh / (len(rr) * dx * dy)
        return out

    frames = [encode_frame(h, u, v)]
    t, steps, dt, clipped, v_out = 0.0, 0, 1.0, 0.0, 0.0
    v_in = 0.0
    next_frame = float(frame_s)
    wall = time.time()
    hour = -1
    rate = None
    while t < T - 1e-9:
        hr_now = int(t // 3600)
        if hr_now != hour or (t < 3600 and src_cells):
            hour = hr_now
            rate = rate_at(hour, t)
        s = smax_row.max()
        dt = min(DT_MAX, CFL / s if s > 0 else DT_MAX, next_frame - t, (hour + 1) * 3600.0 - t)
        _fluxes(h, u, v, z, FXh, FXuL, FXuR, FXv, FYh, FYvL, FYvR, FYu)
        v_out += dt * dy * (FXh[:, nx].sum() - FXh[:, 0].sum()) + dt * dx * (FYh[ny, :].sum() - FYh[0, :].sum())
        v_in += dt * rate.sum() * dx * dy
        t += dt
        _update(h, hu, hv, u, v, n2, rate, dt, dx, dy, t, FXh, FXuL, FXuR, FXv, FYh, FYvL, FYvR, FYu,
                hmax, vmax, hrmax, t_arr, smax_row, clip_row)
        clipped += clip_row.sum() * dx * dy
        steps += 1
        if t >= next_frame - 1e-6:
            frames.append(encode_frame(h, u, v))
            next_frame += frame_s
            if progress:
                progress(min(1.0, t / T))
    stored = float(h.sum() * dx * dy)
    err = (v_in - v_out - stored + clipped) / v_in if v_in > 0 else 0.0
    stats = {"steps": steps, "wall_s": round(time.time() - wall, 1), "cells": int(nx * ny), "cell_m": cell,
             "volume_in_m3": round(v_in), "volume_out_m3": round(v_out), "volume_stored_m3": round(stored),
             "mass_balance_error": float(f"{err:.2e}"), "mean_dt_s": round(T / max(steps, 1), 2)}
    return FlowResult(frame_s=frame_s, frames=frames, hmax=hmax.astype(np.float32), vmax=vmax.astype(np.float32),
                      hazard=hrmax.astype(np.float32), t_arrival_s=t_arr.astype(np.float32), stats=stats)


# FD2321 hazard classes: low (caution), danger for some (children, elderly), danger for most, danger for all
HAZARD_EDGES = [0.75, 1.25, 2.0]


@njit(cache=True)
def _breach(z, eps, max_cut):
    """4-connected Priority-Flood from the grid edge with carving (hybrid breaching, Lindsay 2016): a cell found below the cell that
    reached it is a pit; the path back to the first lower ground is cut as a straight descent from the pit bottom to
    that ground (keeping the valley gradient), unless the cut would be deeper than `max_cut`, in which case the pit is
    filled (Barnes et al. 2014 epsilon fill)."""
    ny, nx = z.shape
    w = z.copy()
    closed = np.zeros((ny, nx), np.bool_)
    parent = np.full(ny * nx, -1, np.int64)
    path = np.empty(ny * nx, np.int64)
    heap = [(0.0, np.int64(0))]
    heap.pop()
    for r in range(ny):
        for c in range(nx):
            if r == 0 or c == 0 or r == ny - 1 or c == nx - 1:
                closed[r, c] = True
                heapq.heappush(heap, (w[r, c], np.int64(r * nx + c)))
    cut_cells = 0
    filled_cells = 0
    while len(heap) > 0:
        zc, i = heapq.heappop(heap)
        r, c = i // nx, i % nx
        for nb in range(4):  # 4-connected: the flow model exchanges water across cell faces only
            rr = r + (nb == 0) - (nb == 1)
            cc = c + (nb == 2) - (nb == 3)
            if rr < 0 or cc < 0 or rr >= ny or cc >= nx or closed[rr, cc]:
                continue
            closed[rr, cc] = True
            j = rr * nx + cc
            parent[j] = i
            z0 = w[rr, cc]
            if z0 <= w[r, c]:
                k = 0
                p = i
                while p >= 0 and w[p // nx, p % nx] >= z0 - eps * (k + 1):
                    path[k] = p
                    k += 1
                    p = parent[p]
                z1 = w[p // nx, p % nx] if p >= 0 else z0 - eps * (k + 1)
                need = 0.0
                for m in range(k):
                    q = path[m]
                    zt = z0 - (z0 - z1) * (m + 1) / (k + 1)
                    if w[q // nx, q % nx] - zt > need:
                        need = w[q // nx, q % nx] - zt
                if need <= max_cut:
                    for m in range(k):
                        q = path[m]
                        zt = z0 - (z0 - z1) * (m + 1) / (k + 1)
                        if zt < w[q // nx, q % nx]:
                            w[q // nx, q % nx] = zt
                            cut_cells += 1
                else:
                    w[rr, cc] = w[r, c] + eps
                    filled_cells += 1
            heapq.heappush(heap, (w[rr, cc], np.int64(j)))
    return w, cut_cells, filled_cells


def condition(dem: np.ndarray, max_cut_m: float = 50.0) -> tuple[np.ndarray, dict]:
    """Hydrologically conditioned DEM for flow in hilly areas: every cell drains to the grid edge."""
    z = np.asarray(dem, np.float64)
    if np.isnan(z).any():
        from scipy import ndimage
        idx = ndimage.distance_transform_edt(np.isnan(z), return_distances=False, return_indices=True)
        z = z[tuple(idx)]
    w, cut, filled = _breach(z, 1e-3, max_cut_m)
    return w.astype(np.float32), {"carved_cells": int(cut), "filled_cells": int(filled),
                                  "max_lowered_m": round(float((z - w).max()), 1), "max_raised_m": round(float((w - z).max()), 1)}


def coarsen(a: np.ndarray, k: int) -> np.ndarray:
    """Block mean by k (edges padded by repetition so the coarse grid covers the whole area)."""
    if k == 1:
        return np.asarray(a, np.float64)
    ny, nx = a.shape
    a = np.pad(np.asarray(a, np.float64), ((0, (-ny) % k), (0, (-nx) % k)), mode="edge")
    return a.reshape(a.shape[0] // k, k, a.shape[1] // k, k).mean(axis=(1, 3))


def decode_velocity(code: np.ndarray) -> np.ndarray:
    s = (code.astype(np.float32) - 128) / 127
    return np.sign(s) * s * s * U_CODE


def downscale_frame(frame: np.ndarray, z: np.ndarray, k: int) -> np.ndarray:
    """Coarse-model frame -> analysis grid, volume-conserving: each model cell's water fills its k x k sub-cells of the
    fine ground from the lowest up (so it runs in the channels, not as a sheet over a 60 m slope); velocity is the
    model cell's."""
    if k == 1:
        return frame
    ny, nx = z.shape
    zp = np.pad(np.asarray(z, np.float64), ((0, (-ny) % k), (0, (-nx) % k)), mode="edge")
    by, bx = zp.shape[0] // k, zp.shape[1] // k
    zb = zp.reshape(by, k, bx, k).transpose(0, 2, 1, 3).reshape(by, bx, k * k)
    zs = np.sort(zb, axis=-1)
    cs = np.cumsum(zs, axis=-1)
    vol = decode_depth(frame[0]).astype(np.float64)[:by, :bx] * (k * k)  # m x fine-cell area
    j = np.arange(1, k * k + 1)
    lev = (vol[..., None] + cs) / j  # level if water covers the j lowest sub-cells
    nxt = np.concatenate([zs[..., 1:], np.full(zs.shape[:-1] + (1,), np.inf)], axis=-1)
    first = np.argmax(lev <= nxt, axis=-1)
    level = np.take_along_axis(lev, first[..., None], axis=-1)[..., 0]
    level = np.where(vol > 0, level, -np.inf)
    rep = lambda a: np.repeat(np.repeat(a, k, 0), k, 1)[:ny, :nx]  # noqa: E731
    h = np.maximum(rep(level) - np.asarray(z, np.float64), 0.0)
    u = rep(decode_velocity(frame[1])[:by, :bx])
    v = rep(decode_velocity(frame[2])[:by, :bx])
    return encode_frame(h, u, -v)
