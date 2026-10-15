import numpy as np
import pytest

from app.engines.hydrology import (HydroGrid, build_reaches, downstream_index, drain_cells, hotspots,
                                   local_accumulation_km2, make_hydro_grid, src_point, src_stage, src_tables)


def test_t5_src_point():
    r = src_point(np.array([0.5, 1.5, 3.0]), 900.0, np.zeros(3), h=2.0, L=90.0, S=0.01, n=0.035)
    assert r["V"] == pytest.approx(1800)
    assert r["A"] == pytest.approx(20) and r["P"] == pytest.approx(20) and r["R"] == pytest.approx(1.0)
    assert r["Q"] == pytest.approx(57.14, abs=0.01)


def test_make_hydro_grid_snaps_outward():
    g = make_hydro_grid((78.9001, 30.2001, 79.0999, 30.3999))
    assert g.lon0 <= 78.9001 and g.lat0 >= 30.3999
    assert abs(g.lon0 * 1200 - round(g.lon0 * 1200)) < 1e-9
    assert g.lon0 + g.width * g.cell_deg >= 79.0999


def _toy():
    """Two 3-cell tributaries (rows 0 and 2) joining a trunk (row 1) that flows east and leaves the grid.

    row0:  E  E  SE  .        row1: E E E E (trunk)        row2: E E NE .
    """
    d8 = np.array([[1, 1, 2, 4],
                   [1, 1, 1, 1],
                   [1, 1, 128, 64]])
    return d8, downstream_index(d8)


def test_downstream_and_accumulation():
    d8, down = _toy()
    assert down[3] == 7 and down[7] == -1 and down[2] == 7
    acc = local_accumulation_km2(down, 1e6)  # 1 km2 cells
    assert acc[7] == pytest.approx(12)  # everything drains to the outlet


def test_drain_cells_and_reaches():
    d8, down = _toy()
    g = HydroGrid(lon0=0, lat0=0, width=4, height=3)
    upa = local_accumulation_km2(down, 1e6).reshape(3, 4)
    stream = upa >= 1  # every cell is stream
    dc = drain_cells(stream, down)
    assert (dc == np.arange(12)).all()
    rid, reaches = build_reaches(g, stream, down, np.zeros((3, 4)), upa, upa.ravel())
    assert (rid >= 0).all()
    assert len(reaches) >= 3
    big = max(reaches, key=lambda r: r["A_up_km2"])
    assert big["A_up_km2"] == pytest.approx(12)


def test_src_tables_monotone_and_stage_lookup():
    hand = np.array([[0.0, 1.0], [2.0, 5.0]])
    catch = np.zeros((2, 2), int)
    reaches = [{"reach_id": 0, "L_m": 100.0, "S": 0.01}]
    t = src_tables(hand, catch, np.zeros((2, 2)), reaches, 900.0)["0"]
    q = np.array(t["Q"])
    assert q[0] == 0 and (np.diff(q) >= 0).all()
    h = src_stage(t, q[8])  # stage 2.0 m
    assert h == pytest.approx(2.0, abs=0.01)
    assert src_stage(t, 1e12) == 30


def test_hotspots_finds_confluence():
    d8, down = _toy()
    g = HydroGrid(lon0=0, lat0=0, width=4, height=3)
    upa = local_accumulation_km2(down, 1e6).reshape(3, 4)
    hs = hotspots(g, upa >= 1, down, upa)
    assert any(h["type"] == "confluence" for h in hs)
