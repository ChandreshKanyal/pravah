import networkx as nx
import numpy as np

from app.engines import improvements as imp

BBOX = (0.0, 0.0, 1.0, 1.0)


def test_single_exit_counts_people_behind_the_only_link():
    # a loop of 4 nodes (town) with a spur 4-5-6 (colony) hanging off node 0 by one link (0-4) over low ground
    G = nx.MultiDiGraph()
    pos = {0: (0.50, 0.50), 1: (0.52, 0.50), 2: (0.52, 0.52), 3: (0.50, 0.52), 4: (0.46, 0.50), 5: (0.44, 0.50), 6: (0.42, 0.50)}
    for n, (x, y) in pos.items():
        G.add_node(n, x=x, y=y)
    for u, v in [(0, 1), (1, 2), (2, 3), (3, 0), (0, 4), (4, 5), (5, 6)]:
        G.add_edge(u, v, name="Link" if (u, v) == (0, 4) else "")
    pop = np.zeros((100, 100), np.float32)
    rc = {n: (int(100 - y * 100), int(x * 100)) for n, (x, y) in pos.items()}
    for n in (5, 6):
        pop[rc[n]] = 400  # 800 people in the colony
    pop[rc[2]] = 5000
    hand = np.full((100, 100), 10.0, np.float32)
    hand[50, 48] = 1.0  # the link's midpoint is low
    stream = np.zeros((100, 100), bool)
    ll2rc = lambda lon, lat: (int(100 - lat * 100), int(lon * 100))  # noqa: E731
    rc2ll = lambda r, c: ((np.asarray(c) + 0.5) / 100, (100 - np.asarray(r) - 0.5) / 100)  # noqa: E731
    out = imp.single_exits(G, hand, stream, pop, ll2rc, rc2ll, BBOX, urban=True, min_people=300)
    assert len(out) == 1
    it = out[0]
    assert it["category"] == "single_exit" and it["place"] == "Link"
    assert 700 <= it["numbers"]["people_cut_off"] <= 900  # the colony, not the town


def test_culverts_use_only_road_openings_and_cap_bridges():
    hand = np.zeros((50, 50), np.float32)
    upa = np.full((50, 50), 40.0, np.float32)
    pop = np.full((50, 50), 10.0, np.float32)
    cands = [{"type": "river", "row": 5, "col": 5, "lon": 0.1, "lat": 0.9, "name": "R", "waterway_id": "r"}]  # sampled point: ignored
    cands += [{"type": "road crossing", "row": 10 + 3 * i, "col": 10, "lon": 0.1 + 0.05 * i, "lat": 0.5, "name": "R", "waterway_id": "r"}
              for i in range(6)]
    out = imp.culverts(cands, hand, upa, pop, 30.0, BBOX, True, {"r": "river"})
    assert all(it["numbers"]["kind"] == "bridge opening" for it in out)
    assert len(out) == 3


def test_rank_orders_and_numbers_items():
    a = imp._item("bare_ground", 0.5, 0.5, 1.0, ["x"], "y", True, basis="imagery")
    b = imp._item("reported", 0.6, 0.6, 0.7, ["x"], "y", True, basis="web")
    out = imp.rank([a, b])
    assert [o["id"] for o in out] == ["I1", "I2"] and out[0]["category"] == "reported"


def test_firestore_nested_arrays_round_trip():
    from app.services.firestore import decode, encode
    doc = {"overlay_corners": [[78.9, 30.2], [78.9, 30.4]], "flat": [1, 2], "deep": {"x": [[[1, 2]], [3]]}}
    enc = encode(doc)
    assert all(not isinstance(v, list) for v in enc["overlay_corners"])  # no array directly inside an array
    assert decode(enc) == doc


def test_profile_gates():
    """One model for every area: tidal channels and one-cell stubs get no river stage; hollows waterlog only when
    their catchment is mostly built-up."""
    import numpy as np
    from app.engines import profile as prof
    reaches = [{"e_up": 12, "e_down": 9, "cells": [1, 2, 3]}, {"e_up": 0.3, "e_down": 0.0, "cells": [1, 2, 3, 4]},
               {"e_up": 40, "e_down": 39, "cells": [7]}]
    assert prof.reliable_reaches(reaches).tolist() == [True, False, False]
    ws = np.array([[1, 1, 2, 2], [1, 1, 2, 2]])
    lc = np.array([[6, 6, 1, 1], [6, 4, 1, 6]])
    ok = prof.built_hollows({"ws_label": ws, "v_dep": np.zeros(3)}, lc)
    assert ok.tolist() == [False, True, False]  # hollow 1 is 75% built, hollow 2 is 25%
    p = prof.area_profile(np.full((2, 4), 20.0), lc, None, reaches, ok)
    assert p["hazards"] == ["river", "waterlogging", "landslide"] and p["tidal"]
