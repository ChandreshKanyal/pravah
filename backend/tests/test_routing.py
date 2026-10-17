import numpy as np
import pytest

from app.engines.roads import narrowness, tobler_kmh
from app.engines.routing import NEVER, assembly_points, build_graph, edge_states, transport_solve, travel_times
from app.engines.shelters import capacity

T10_TIMES = {"S1": {"D1": 5, "D2": 4}, "S2": {"D1": 10, "D2": 6}}


def test_t10_transportation():
    alloc, gap, cost = transport_solve({"D1": 100, "D2": 50}, {"S1": 120, "S2": 100}, T10_TIMES)
    assert cost == 760 and gap == 0
    assert alloc == {("D1", "S1"): 100, ("D2", "S1"): 20, ("D2", "S2"): 30}


def test_t11_overflow():
    _, gap, _ = transport_solve({"D1": 100, "D2": 50}, {"S1": 120, "S2": 0}, T10_TIMES)
    assert gap == 30


def test_t12_tobler():
    assert float(tobler_kmh(0)) == pytest.approx(5.04, abs=0.01)


def test_capacity_and_narrowness():
    assert capacity(200, 2, 3.5) == 68
    assert narrowness("footway", None, None) == 1.0 and narrowness("primary", "2", None) == pytest.approx(0.1)


def test_edge_states_reasons():
    depth = np.zeros((3, 1, 4), np.float32)
    depth[1:, 0, 1] = 0.8  # cell 1 floods from hour 2
    lsi = np.ones((3, 1, 4), np.uint8)
    lsi[2, 0, 3] = 5  # cell 3 landslide class 5 at hour 3
    cells = [[0], [1], [2], [3], [0]]  # single-cell edges: share of class-5 cells is 0 or 1
    bridge_first = np.array([NEVER, NEVER, 3, NEVER, NEVER])  # edge 2 runs over a span the river reaches at hour 3
    bridge_cells = [set(), set(), {2}, set(), set()]
    first, reason, _ = edge_states(cells, np.array([0, 0, 0, 0, 1], bool), depth, lsi, 0.5, bridge_first, bridge_cells)
    assert list(first) == [NEVER, 2, 3, 3, 1]
    assert reason == ["", "flood", "bridge", "landslide", "blocked"]


def test_graph_and_travel_times():
    G = build_graph(np.array([1, 2, 1]), np.array([2, 3, 3]), np.array([10.0, 10.0, 50.0]), np.array([1, 1, 1], bool))
    t = travel_times(G, {"S": 3}, cutoff_s=100)
    assert t["S"][1] == 20 and t["S"][2] == 10


def test_assembly_points():
    z = np.zeros((10, 10))
    ap = assembly_points(z, np.full((10, 10), 20.0), z, None, z, 30.0)
    assert len(ap) == 1 and ap[0]["capacity"] == int(100 * 900 * 0.5 / 2)


def test_bridge_ignores_river_below_and_short_landslide_patch():
    depth = np.zeros((1, 1, 6), np.float32)
    depth[0, 0, 2] = 2.0  # river cell under the bridge deck
    lsi = np.ones((1, 1, 6), np.uint8)
    lsi[0, 0, 5] = 5  # one class-5 cell in a 5-cell road
    first, reason, _ = edge_states([[1, 2, 3], [1, 3, 4, 0, 5]], np.zeros(2, bool), depth, lsi, 0.5,
                                   np.array([NEVER, NEVER]), [{2}, set()], lsi_close_share=0.3)
    assert list(first) == [NEVER, NEVER]


def test_bridge_spans_deck_height_and_closures():
    import geopandas as gpd
    from shapely.geometry import LineString
    from app.engines import bridges
    from app.models.grid import GridSpec
    g = GridSpec(crs="EPSG:32644", x0=0.0, y0=300.0, cell=30.0, width=10, height=10)
    hand = np.full((10, 10), 20.0)
    hand[:, 4:6] = 0.0  # river channel in columns 4-5
    hand[:, 3] = hand[:, 6] = 9.0  # banks: deck about 9 m above normal level
    rid = np.where(hand < 1, 0, -1)
    ways = gpd.GeoDataFrame({"osmid": ["way/1", "way/2"], "name": ["River bridge", None], "highway": ["primary", "construction"],
                             "construction": [None, "primary"], "access": [None, None], "bridge": ["yes", "yes"], "layer": ["1", "1"],
                             "disused": [None, None], "abandoned": [None, None]},
                            geometry=[LineString([(100, 150), (200, 150)]), LineString([(100, 45), (200, 45)])], crs=g.crs)
    sp = bridges.spans(ways, g, hand, rid)
    assert len(sp) == 2
    main = next(s for s in sp if s["name"] == "River bridge")
    assert main["reach"] == 0 and 8.5 <= main["deck_m"] <= 20 and main["status"] == "open"
    stage = np.array([[2.0, 6.0, main["deck_m"] + 0.5]])
    first, reason, over = bridges.closure_hours(sp, stage)
    k = sp.index(main)
    assert first[k] == 3 and reason[k] == "overtopped" and over[k] == 0.5
    assert first[1 - k] == 1 and reason[1 - k] == "construction"
    f2, _, _ = bridges.closure_hours(sp, np.array([[2.0, 3.0, 4.0]]))
    assert f2[k] == bridges.NEVER  # a 4 m river under a ~9 m deck: open


def test_evacuation_deadline_ignores_bridges_that_were_never_open():
    from app.pipeline.run_pipeline import _evac_window
    ev = {"routes_summary": [], "bridges": [{"first_closed_hour": 1, "reason": "construction"},
                                            {"first_closed_hour": 3, "reason": "overtopped"}]}
    assert _evac_window(ev) == 3
    assert _evac_window({"routes_summary": [], "bridges": [{"first_closed_hour": 1, "reason": "construction"}]}) is None
