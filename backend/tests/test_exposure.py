import numpy as np
import pytest

from app.engines.buildings import classify, cluster_flags
from app.engines.exposure import building_risk, per_hour, triage
from app.engines.population import distribute, scale_factor


def test_classify_rules_in_order():
    cls, F, conf, floors = classify(
        area_m2=[20, 30, 100, 200, 200, 300], height_m=[np.nan, 3.0, 4.0, 4.0, 10.0, 5.0],
        presence_2016=[1, 1, 1, 0.1, 1, 1], presence_2023=[1, 1, 1, 0.9, 1, 1], cluster=[False] * 6)
    assert list(cls) == ["makeshift_or_hut", "makeshift_or_hut", "likely_kaccha_or_low_rise",
                         "new_unplanned_low_rise", "likely_pukka_multi_storey", "likely_pukka_low_rise"]
    assert list(conf) == [0.35, 0.50, 0.40, 0.35, 0.55, 0.40]
    assert list(floors) == [1, 1, 1, 1, 3, 2]


def test_cluster_rule():
    xs = np.arange(9) * 5.0  # 9 small huts within 40 m line; middle ones see >= 8 within 30 m? use a tight grid
    x, y = np.meshgrid(np.arange(3) * 8.0, np.arange(3) * 8.0)
    flags = cluster_flags(x.ravel(), y.ravel(), np.full(9, 30.0))
    assert flags[4]  # centre sees all 9 within 30 m
    assert not cluster_flags(xs * 10, np.zeros(9), np.full(9, 30.0)).any()


def test_t14_population_conservation():
    pop = np.array([[10.0, 5.0], [0.0, 7.0]])
    rows, cols = np.array([0, 0, 1, 5]), np.array([0, 0, 1, 5])  # last building outside grid
    pop_b, un = distribute(pop, rows, cols, np.array([100.0, 300.0, 50.0, 10.0]), np.array([3.0, 3.0, np.nan, 3.0]))
    assert pop_b[:2] == pytest.approx([2.5, 7.5])
    assert pop_b.sum() + un.sum() == pytest.approx(pop.sum(), abs=1)
    assert un[0, 1] == 5.0
    pb3, un3 = distribute(pop, rows, cols, np.array([100.0, 300.0, 50.0, 10.0]), np.array([3.0, 3.0, np.nan, 3.0]), block=2)
    assert un3.sum() == 0 and pb3.sum() == pytest.approx(pop.sum())  # one 2x2 block holds all people
    k = scale_factor(22.0, 1.0, 44)
    assert (pop_b.sum() + un.sum()) * k == pytest.approx(44, abs=1)


def test_building_risk_hand_computed():
    # d=1.5 m, F=0.8, dist 150 m, ls 2: R = 0.5*0.5 + 0.3*0.8 + 0.2*0.5 = 0.59 -> high
    # dry, ls 2 -> 0; dry, ls 4 -> R = 0.3*0.45 + 0 = 0.135 -> raised to high (landslide)
    R, cls, why = building_risk([1.5, 0.0, 0.0], [0.8, 0.8, 0.45], [150, 150, 400], [2, 2, 4])
    assert R == pytest.approx([0.59, 0.0, 0.135])
    assert list(cls) == ["high", "low", "high"] and list(why) == ["flood", "", "landslide"]


def test_exposure_monotone_with_depth_and_triage_sorted():
    pop_b = np.array([10.0, 20.0])
    rows, cols = np.array([0, 1]), np.array([0, 1])
    un = np.zeros((2, 2))
    shallow = np.array([[[0.1, 0], [0, 0.0]]])
    deep = np.array([[[0.1, 0], [0, 1.0]]])
    assert per_hour(deep, None, rows, cols, pop_b, un)["exposed_pop_by_hour"][0] > \
        per_hour(shallow, None, rows, cols, pop_b, un)["exposed_pop_by_hour"][0]
    t = triage(["a", "b", "a"], ["low", "critical", "critical"], [5, 1, 9])
    assert [r["risk_class"] for r in t] == ["critical", "critical", "low"] and t[0]["people"] == 9
