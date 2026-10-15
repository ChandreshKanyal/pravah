"""S13 urban: priority-flood fills pits, volume-conserving fill levels, drain priority ordering."""
import numpy as np
import pytest

from app.engines import drains, pluvial


def _bowl():
    """Flat 10 m plain with a 3x3 pit (8 m, centre 7 m). The plain drains to the edges; only the pit drains in."""
    dem = np.full((9, 9), 10.0)
    dem[3:6, 3:6] = 8.0
    dem[4, 4] = 7.0
    return dem


def test_priority_flood_fills_pit_to_rim():
    f = pluvial.priority_flood(_bowl())
    assert f[4, 4] == pytest.approx(10.0, abs=1e-2) and f[0, 0] == 10.0
    assert np.all(f >= _bowl() - 1e-9)


def test_prepare_and_volume_conserving_fill():
    dem = _bowl()
    st = pluvial.prepare(dem, 30.0, np.full(dem.shape, 1.0))
    assert len(st["v_dep"]) == 2  # one depression
    v = st["v_dep"][1]
    assert v == pytest.approx((8 * 2 + 3) * 900, rel=1e-3)  # 8 cells x 2 m + 1 cell x 3 m
    # water 1 m deep over 8 cells + 2 m in the centre = 10 m-cells = 9000 m3 -> level 9 m
    L = pluvial.level_for_volume(np.sort(dem[3:6, 3:6].ravel()), 9000.0, 900.0, 10.0)
    assert L == pytest.approx(9.0)
    assert st["ws_area_m2"][1] == pytest.approx(9 * 900)
    # 9 cells drain to the pit, C = 1: 50 mm excess -> 9*900*0.05 = 405 m3, conserved in the ponded depths
    depth, fill = pluvial.ponding(st, dem, [75.0], 30.0, drain_capacity_mm_h=25.0)
    assert fill[0, 1] == pytest.approx(405 / v, rel=1e-3)
    assert float(depth[0].sum() * 900) == pytest.approx(405, rel=1e-3)
    assert depth[0, 4, 4] == pytest.approx(0.45) and depth[0, 3, 3] == 0  # 405 m3 stays in the 7 m centre cell
    nothing, _ = pluvial.ponding(st, dem, [20.0], 30.0, drain_capacity_mm_h=25.0)
    assert not nothing.any()  # within drain capacity


def test_drain_priority_orders_by_score_and_photo():
    cands = [{"x": 0, "y": 0, "type": "drain", "waterway_id": "a", "name": ""},
             {"x": 0, "y": 0, "type": "culvert", "waterway_id": "b", "name": ""}]
    acc = np.ones((10, 10)); acc[5, 5] = 1000
    pop = np.zeros((10, 10)); pop[5, 5] = 100
    out = drains.priority(cands, [1, 5], [1, 5], acc, np.zeros((10, 10)), np.zeros((10, 10)), pop, {}, top=2)
    assert out[0]["waterway_id"] == "b" and out[0]["id"] == "D1"
    out2 = drains.priority(cands, [1, 5], [1, 5], acc, np.zeros((10, 10)), np.zeros((10, 10)), pop, {"a": "blocked", "b": "clear"}, top=2)
    assert out2[0]["priority"] >= out2[1]["priority"]
    assert {d["photo_condition"] for d in out2} == {"blocked", "clear"}
