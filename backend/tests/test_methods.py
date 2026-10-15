"""Tests for the 17 Oct method fixes: flow-path tc, areal reduction, IMD duration rule, regional landslide threshold,
AUC, per-segment Tobler, coarse terrain and SRC at zero flow."""
import math

import numpy as np
import pytest
from shapely.geometry import LineString

from app.engines.grid import make_grid, terrain_coarse
from app.engines.hydrology import HydroGrid, downstream_index, flow_path, src_stage
from app.engines.landslide import auc, exceedance, rain_modulation
from app.engines.rainfall import (areal_reduction_factor, daily_to_duration_mm, kirpich_tc_min, landslide_threshold,
                                  tc_hours_path, threshold_name)
from app.engines.roads import tobler_kmh, tobler_time_s


def test_flow_path_longest_branch_and_head_elevation():
    # row0 flows east into col 3 then south; row1 flows east; both end at (1,3) which leaves the grid
    d8 = np.array([[1, 1, 1, 4],
                   [1, 1, 1, 1]])
    g = HydroGrid(lon0=0.0, lat0=0.0, width=4, height=2)
    elv = np.array([[40.0, 30, 20, 10], [35, 25, 15, 5]])
    L, head = flow_path(downstream_index(d8), g, elv)
    # outlet (1,3): row0 path = 3 dx + 1 dy, row1 path = 3 dx; longest is row0 with head elevation 40
    assert L[7] == pytest.approx(3 * g.dx + g.dy)
    assert head[7] == 40.0
    assert L[0] == 0 and head[0] == 40.0


def test_tc_path_uses_relief_slope_and_hack_fallback():
    assert tc_hours_path([10000], [500], [50])[0] == pytest.approx(kirpich_tc_min(10000, 0.05) / 60)
    # one-cell path -> Hack length for A = 50 km2 (13.28 km) with S = 0.005
    assert tc_hours_path([0], [0], [50])[0] == pytest.approx(kirpich_tc_min(13280.0, 0.005) / 60, rel=1e-3)


def test_arf_tp29_fit():
    assert areal_reduction_factor(0, 1) == pytest.approx(1.0)
    # A = 500 km2 (193 mi2), D = 3 h: 1 - e^-1.448 + e^(-1.448-1.931) = 0.799
    assert areal_reduction_factor(500, 3) == pytest.approx(0.799, abs=0.002)
    assert areal_reduction_factor(50, 3) > areal_reduction_factor(500, 3)
    assert areal_reduction_factor(500, 24) > areal_reduction_factor(500, 1)


def test_imd_one_third_rule():
    assert daily_to_duration_mm(201, 4) == pytest.approx(201 * (4 / 24) ** (1 / 3))
    assert daily_to_duration_mm(201, 4) == pytest.approx(110.6, abs=0.1)
    assert daily_to_duration_mm(100, 24) == pytest.approx(100)


def test_dahal_hasegawa_threshold_and_auto_choice():
    assert landslide_threshold([1, 24], "dahal_hasegawa") == pytest.approx([73.90, 6.00], abs=0.02)
    assert threshold_name("auto", 78.98, 30.28) == "dahal_hasegawa"  # Rudraprayag
    assert threshold_name("auto", 72.88, 19.07) == "caine"  # Mumbai
    assert threshold_name("caine", 78.98, 30.28) == "caine"
    # 6 mm/h for 24 h sits exactly on the Himalayan threshold: R = 1 -> g = 1
    assert exceedance([6.0] * 24, "dahal_hasegawa")[-1] == pytest.approx(1.0, abs=0.01)
    assert rain_modulation([6.0] * 24, threshold="dahal_hasegawa")[-1] == pytest.approx(1.0, abs=0.01)


def test_auc():
    assert auc([0.1, 0.2, 0.8, 0.9], [False, False, True, True]) == pytest.approx(1.0)
    assert auc([0.9, 0.8, 0.2, 0.1], [False, False, True, True]) == pytest.approx(0.0)
    assert auc([0.5, 0.5, 0.5, 0.5], [False, True, False, True]) == pytest.approx(0.5)
    assert auc([0.1, 0.2], [False, False]) is None


def test_tobler_per_segment_counts_up_and_down():
    grid = make_grid((78.98, 30.28, 78.99, 30.29), buffer_m=0, cell=30, snap=30)
    cols = np.arange(grid.width)
    dem = np.tile(np.where(cols % 2 == 0, 0.0, 6.0), (grid.height, 1))  # 6 m up, 6 m down every 30 m
    y = grid.y0 - 15 * grid.cell
    line = LineString([(grid.x0 + 15, y), (grid.x0 + 15 + 300, y)])
    t = tobler_time_s(line, grid, dem, (grid.x0 + 15, y), 300.0)
    flat = 300 / (float(tobler_kmh(0)) / 3.6)
    assert t > 1.3 * flat  # end-to-end the climb nets to zero, but each 30 m segment is a 20% grade
    rev = tobler_time_s(line, grid, dem, (grid.x0 + 315, y), 300.0)
    assert rev == pytest.approx(t, rel=0.15)


def test_terrain_coarse_matches_shape_and_smooths():
    rng = np.random.default_rng(0)
    dem = np.add.outer(np.arange(30) * 10.0, np.zeros(31)) + rng.normal(0, 5, (30, 31))
    tc = terrain_coarse(dem, 30.0, 3)
    assert tc["slope_deg"].shape == dem.shape
    # true slope = atan(10/30) = 18.4 deg; the 90 m version is much less noisy
    assert abs(float(np.median(tc["slope_deg"])) - math.degrees(math.atan(1 / 3))) < 2.0


def test_src_stage_zero_flow_is_zero_stage():
    table = {"h": [0, 0.25, 0.5], "Q": [0, 0, 5.0]}
    assert src_stage(table, 0.0) == 0.0
    assert src_stage(table, 5.0) == pytest.approx(0.5)


def test_external_inflow_shares_by_outside_area():
    from types import SimpleNamespace
    from app.pipeline.run_pipeline import external_inflow
    area = SimpleNamespace(reaches=[{"A_up_km2": 1000.0, "A_loc_km2": 100.0},   # main stem: 900 km2 outside
                                    {"A_up_km2": 460.0, "A_loc_km2": 10.0},     # tributary entering: 450 outside
                                    {"A_up_km2": 20.0, "A_loc_km2": 20.0}])     # local stream
    q = external_inflow(area, 900.0)
    assert list(q) == pytest.approx([900.0, 450.0, 0.0])
    assert external_inflow(area, 0.0) == 0.0
