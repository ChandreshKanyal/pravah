import numpy as np
import pytest

from app.engines.flood import depth_from_stage, depth_stack, flooded_area_km2, hourly_envelope
from app.engines.hydrology import SRC_STAGES
from app.engines.rainfall import caine_threshold, hack_length_km, kirpich_tc_min, manual_series, rational_q, runoff_c


def test_t1_rational_q():
    assert rational_q(0.5, 50, 50) == pytest.approx(347.5)


def test_t2_kirpich():
    assert kirpich_tc_min(10_000, 0.05) == pytest.approx(74.29, abs=0.01)


def test_t3_hack():
    assert hack_length_km(50) == pytest.approx(13.28, abs=0.01)


def test_t4_caine():
    assert caine_threshold([1, 4, 24]) == pytest.approx([14.82, 8.63, 4.29], abs=0.01)


def test_t6_depth_from_stage():
    np.testing.assert_array_equal(depth_from_stage(np.array([[0, 1], [2, 5]]), 2), [[2, 1], [0, 0]])


def test_depth_perm_water_and_hand_cap():
    d = depth_from_stage(np.array([0.0, 35.0, 1.0]), 40, perm=np.array([False, False, True]))
    assert d[0] == 40 and d[1] == 0 and np.isnan(d[2])


def _linear_src():
    return {"h": SRC_STAGES.tolist(), "Q": (SRC_STAGES * 100).tolist()}  # Q = 100 h


def test_t7_hourly_envelope():
    h, Q = hourly_envelope([50, 0, 0], tc_h=[2.0], C=[0.5], A_loc_km2=[50.0], src=[_linear_src()])
    assert (np.diff(h[0]) >= 0).all()
    assert h[0, 2] == h[0].max()


def test_more_rain_more_flood():
    hand = np.linspace(0, 10, 100).reshape(10, 10)
    rid = np.zeros((10, 10), int)
    areas = []
    for i in (20, 100):
        h, _ = hourly_envelope([i] * 4, [1.0], [0.5], [20.0], [_linear_src()])
        areas.append(flooded_area_km2(depth_stack(h, rid, hand)[-1]))
    assert areas[1] > areas[0]


def test_runoff_c_and_manual_series():
    assert runoff_c(np.array([6, -1]))[0] == pytest.approx(0.85) and np.isnan(runoff_c(np.array([6, -1]))[1])
    tri = manual_series(30, 6, "triangular_front")
    assert sum(tri) == pytest.approx(180) and int(np.argmax(tri)) == 1  # peak at hour ceil(6/3) = 2


def test_series_builders():
    from app.engines.rainfall import day_hours, wettest_window, worst_day_index
    win, k = wettest_window([0, 1, 5, 7, 2, 0], 3)
    assert win == [5, 7, 2] and k == 2
    hourly = [{"local_date": "2026-10-16", "local_hour": 3, "precip_mm": 4.0}]
    assert day_hours(hourly, "2026-10-16")[3] == 4.0
    assert worst_day_index([{"precip_mm": 1}, {"precip_mm": 9}, {"precip_mm": 2}]) == 1
