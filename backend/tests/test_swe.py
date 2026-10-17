"""2D shallow-water flow model (engines/swe.py): well-balancing, steady states, mass, edges, terrain conditioning."""
import numpy as np

from app.engines import swe


def _state(z, h):
    ny, nx = z.shape
    arrs = dict(hu=np.zeros_like(z), hv=np.zeros_like(z), u=np.zeros_like(z), v=np.zeros_like(z))
    F = [np.zeros((ny, nx + 1)) for _ in range(4)] + [np.zeros((ny + 1, nx)) for _ in range(4)]
    extra = [np.zeros_like(z), np.zeros_like(z), np.zeros_like(z), np.full_like(z, -1.0), np.zeros(ny), np.zeros(ny)]
    return arrs, F, extra


def test_lake_at_rest_stays_still_over_bumpy_terrain_with_islands():
    rng = np.random.default_rng(0)
    z = rng.random((30, 40)) * 2.0
    z[0, :] = z[-1, :] = z[:, 0] = z[:, -1] = 5.0  # closed basin
    h = np.maximum(0.0, 1.2 - z)
    h0 = h.copy()
    a, F, ex = _state(z, h)
    n2 = np.full_like(z, 0.03 ** 2)
    rate = np.zeros_like(z)
    for k in range(300):
        swe._fluxes(h, a["u"], a["v"], z, *F)
        swe._update(h, a["hu"], a["hv"], a["u"], a["v"], n2, rate, 0.5, 30.0, 30.0, k * 0.5, *F, *ex)
    assert np.abs(h - h0).max() < 1e-12
    assert max(np.abs(a["u"]).max(), np.abs(a["v"]).max()) < 1e-12


def _plane(S, n=0.05, i=50.0, L=2000.0, cell=20.0, hours=3):
    nx = int(L / cell)
    x = (np.arange(nx) + 0.5) * cell
    z = np.tile(S * (L - x), (4, 1))
    r = swe.simulate(z, cell, np.ones_like(z), np.full_like(z, n), [i] * hours, frame_s=3600)
    h = swe.decode_depth(r.frames[-1][0])[1]
    kin = (i / 3.6e6 * x * n / np.sqrt(S)) ** 0.6  # kinematic-wave steady depth (Manning)
    return h, kin, r


def test_rain_on_a_slope_reaches_the_manning_steady_depth_gentle_and_steep():
    for S in (0.05, 0.6):  # 5 % and 60 % (thin films on steep hillsides)
        h, kin, r = _plane(S)
        for k in (25, 50, 90, 99):
            assert abs(h[k] - kin[k]) <= 0.12 * kin[k] + 0.005, (S, k, h[k], kin[k])
        assert abs(r.stats["mass_balance_error"]) < 1e-10


def test_closed_bowl_keeps_all_rain_and_lets_nothing_in_through_the_edge():
    y, x = np.mgrid[0:40, 0:40]
    z = 0.002 * ((x - 19.5) ** 2 + (y - 19.5) ** 2)  # edges higher than the centre
    r = swe.simulate(z, 30.0, np.ones_like(z), np.full_like(z, 0.04), [40.0, 20.0], frame_s=1800)
    assert r.stats["volume_out_m3"] >= 0
    assert abs(r.stats["mass_balance_error"]) < 1e-10
    stored = swe.decode_depth(r.frames[-1][0]).sum() * 900
    assert stored > 0.9 * r.stats["volume_in_m3"]


def test_inflow_source_conserves_volume():
    z = np.tile(np.linspace(10, 0, 50), (10, 1))
    src = [{"rows": [5], "cols": [1], "q": [5.0, 5.0]}]
    r = swe.simulate(z, 30.0, np.zeros_like(z), np.full_like(z, 0.035), [0.0, 0.0], sources=src, frame_s=3600)
    # ramped over the first hour: 0.5 h + 1 h at full flow
    assert abs(r.stats["volume_in_m3"] - 5.0 * 5400) < 0.02 * 5.0 * 5400
    assert abs(r.stats["mass_balance_error"]) < 1e-10


def test_condition_removes_every_face_connected_pit_and_keeps_valley_gradient():
    y, x = np.mgrid[0:30, 0:30]
    z = 100.0 - 2.0 * x + 0.5 * np.abs(y - 15)  # valley draining west->east... downhill to the east
    z[15, 20] += 25.0  # a false dam across the valley floor
    w, st = swe.condition(z)
    p = np.pad(w, 1, mode="edge")
    c = p[1:-1, 1:-1]
    pits = (c < p[:-2, 1:-1]) & (c < p[2:, 1:-1]) & (c < p[1:-1, :-2]) & (c < p[1:-1, 2:])
    assert not pits[1:-1, 1:-1].any()
    assert st["filled_cells"] == 0 and st["carved_cells"] > 0
    assert (w <= z + 1e-6).all()  # carving only lowers


def test_frame_coding_round_trip_and_downscale_keeps_volume():
    h = np.array([[0.0, 0.005, 0.02], [0.5, 2.0, 9.0]])
    u = np.array([[0.0, 0.0, 1.0], [-2.0, 0.5, 7.5]])
    f = swe.encode_frame(h, u, -u)
    d = swe.decode_depth(f[0])
    assert d[0, 0] == 0 and d[0, 1] == 0  # below 1 cm is not drawn
    assert np.allclose(d[1], h[1], rtol=0.03)
    assert np.allclose(swe.decode_velocity(f[1])[1], u[1], rtol=0.05, atol=0.02)
    rng = np.random.default_rng(1)
    zf = rng.random((8, 8)) * 3
    coarse = np.zeros((4, 4))
    coarse[1, 2] = 1.5
    fc = swe.encode_frame(coarse, np.zeros((4, 4)), np.zeros((4, 4)))
    fine = swe.downscale_frame(fc, zf, 2)
    v_coarse = swe.decode_depth(fc[0]).sum() * 4
    assert abs(swe.decode_depth(fine[0]).sum() - v_coarse) < 0.05 * v_coarse


def test_emulator_reproduces_a_monotone_flood_and_finds_thresholds():
    from app.engines import emulator as em
    y, x = np.mgrid[0:20, 0:30]
    z = 0.05 * x + 0.02 * np.abs(y - 10)  # a valley: water spreads up the sides as rain grows
    def truth(P, H, off=0.0):
        level = 0.004 * P + 0.2 * (P / H) ** 0.5 / 3 + 0.1 * off
        return np.clip(level - z, 0, None).astype(np.float32)
    rng = np.random.default_rng(3)
    X, Y = [], []
    for _ in range(30):  # noqa: B007
        H = int(rng.choice([1, 2, 3, 6])); P = float(rng.uniform(20, 300)); off = float(rng.uniform(0, 2))
        rain = [P / H] * H
        X.append(em.features(rain, off)); Y.append(truth(P, H, off).ravel())
    X, Y = np.array(X), np.array(Y)
    model = em.Emulator(X, Y, z.shape)
    s = em.score(model.predict(em.features([50.0] * 3, 1.0)), truth(150, 3, 1.0))
    assert s["csi"] > 0.9 and s["mae_m"] < 0.05
    loo = em.leave_one_out(X, Y, z.shape)
    assert np.median([r["csi"] for r in loo]) > 0.9
    # threshold: smallest 3 h total that wets cell (10, 20) to 0.1 m is monotone and inside the range
    P = em.threshold_mm(model, lambda h: h[10, 20] >= 0.1, 3, lambda P, H: [P / H] * H)
    p_true = next(q for q in np.arange(5, 400, 1.0) if truth(q, 3)[10, 20] >= 0.1)
    assert P is not None and abs(P - p_true) <= 0.25 * p_true
    st = em.Emulator.from_state(model.state())
    assert np.allclose(st.predict(X[0]), model.predict(X[0]), atol=1e-5)


def test_model_runs_on_after_the_rain_so_late_arriving_water_counts():
    z = np.tile(np.linspace(30, 0, 60), (6, 1))  # a long slope: water from the top reaches the bottom after the rain
    kw = dict(cell=30.0, runoff_c=np.ones_like(z), manning=np.full_like(z, 0.05), rain_mm_h=[40.0], frame_s=1800)
    short = swe.simulate(z, **kw)
    long = swe.simulate(z, **kw, tail_h=2)
    assert len(long.frames) == len(short.frames) + 4  # 2 extra hours at 30-minute frames
    assert long.hmax[:, -3:].max() >= short.hmax[:, -3:].max()  # the foot of the slope peaks no lower, usually later
    assert abs(long.stats["mass_balance_error"]) < 1e-10
