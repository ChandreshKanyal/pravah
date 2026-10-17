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


def test_design_storm_and_presets_follow_the_imd_rules():
    from app.engines.rainfall import daily_to_duration_mm, design_storm_weights, preset_series
    for H in (2, 4, 6, 12, 24):
        w = design_storm_weights(H)
        assert w.sum() == pytest.approx(1)
        p = int(np.argmax(w))
        assert p == -(-H // 3) - 1
        # nested: the wettest k hours (a run around the peak) hold the k-hour share of the reduction curve
        for k in range(1, H + 1):
            best = max(w[i:i + k].sum() for i in range(H - k + 1))
            assert best == pytest.approx((k / H) ** (1 / 3), rel=1e-9)
    s, label = preset_series("imd_very_heavy", 4)
    assert sum(s) == pytest.approx(daily_to_duration_mm(204.4, 4)) and len(set(s)) == 1 and "very heavy" in label
    s, _ = preset_series("imd_very_heavy", 4, "triangular_front")
    assert sum(s) == pytest.approx(daily_to_duration_mm(204.4, 4)) and max(s) == pytest.approx(daily_to_duration_mm(204.4, 1))
    for H in (1, 3, 6):  # cloudburst: peak hour exactly 100 mm whatever the duration, shape forced
        s, _ = preset_series("cloudburst", H, "constant")
        assert max(s) == pytest.approx(100) and sum(s) == pytest.approx(100 * H ** (1 / 3))


def test_series_builders():
    from app.engines.rainfall import day_hours, wettest_window, worst_day_index
    win, k = wettest_window([0, 1, 5, 7, 2, 0], 3)
    assert win == [5, 7, 2] and k == 2
    hourly = [{"local_date": "2026-10-16", "local_hour": 3, "precip_mm": 4.0}]
    assert day_hours(hourly, "2026-10-16")[3] == 4.0
    assert worst_day_index([{"precip_mm": 1}, {"precip_mm": 9}, {"precip_mm": 2}]) == 1


def test_fsi_ignores_implausible_satellite_flood_pixels():
    from app.engines.fsi import factor_scores
    hand = np.array([[2.0, 300.0, 2.0]])
    slope = np.array([[1.0, 2.0, 25.0]])
    gfd = np.array([[3, 3, 3]])
    s = factor_scores(hand, gfd, np.zeros((1, 3)), np.zeros((1, 3)), np.ones((1, 3)), np.full((1, 3), 100.0), slope, np.full((1, 3), 0.5))
    assert s["hist"][0, 0] > 0 and s["hist"][0, 1] == 0 and s["hist"][0, 2] == 0  # ridge and steep slope dropped


def test_forecast_window_never_starts_in_past_hours():
    from app.engines.rainfall import day_hours, first_covered_hour, wettest_window
    hourly = [{"local_date": "2026-10-16", "local_hour": h, "precip_mm": 0.0} for h in range(21, 24)]
    first = first_covered_hour(hourly, "2026-10-16")
    win, k = wettest_window(day_hours(hourly, "2026-10-16")[first:], 2)
    assert first == 21 and k + first == 21


def test_edited_hourly_rain_is_used_as_is_and_keeps_its_clock():
    from app.models.scenario import ScenarioParams
    from app.pipeline.run_pipeline import rain_series
    p = ScenarioParams(aoi_id="x", rain_source="forecast", duration_h=3, rain_series_override=[5, 40.5, 12],
                       override_start_local="2026-10-20T14:00", preset_label="Forecast Tue 20 Oct (edited by hand)")
    series, label, _, start = rain_series(p, None)
    assert series == [5.0, 40.5, 12.0] and start == "2026-10-20T14:00" and "edited" in label
