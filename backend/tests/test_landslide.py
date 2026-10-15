import numpy as np
import pytest

from app.engines.ahp import ahp_weights
from app.engines.fr import fr_ratings, frequency_ratio
from app.engines.landslide import (EXPERT, LSI_MATRIX, aspect_class, learn_ratings, lsi_dynamic_classes, actionable,
                                   rain_modulation)


def test_t8_landslide_ahp():
    w, _, _, cr = ahp_weights(LSI_MATRIX)
    assert cr == pytest.approx(0.0102, abs=0.0005)
    assert w == pytest.approx([0.206, 0.190, 0.130, 0.107, 0.107, 0.107, 0.091, 0.063], abs=0.002)


def test_t9_frequency_ratio():
    classes = np.array([0] * 20 + [1] * 80)
    slides = np.zeros(100, bool)
    slides[[0, 1, 2, 3, 50]] = True  # 4 of 5 slides in class A (0)
    fr = frequency_ratio(classes, slides, 2)
    assert fr[0] == pytest.approx(4.0)
    assert fr_ratings(fr)[0] == pytest.approx(1.0)


def test_fallback_when_few_slides():
    classes = {"slope": np.zeros(10, int)}
    ratings, n = learn_ratings(classes, np.zeros(10, bool), ["slope"])
    assert n == 0 and ratings["slope"] == EXPERT["slope"]


def test_aspect_classes():
    assert aspect_class(np.array([0, 44, 46, 180, 350, -1])).tolist() == [0, 1, 1, 4, 0, 8]


def test_rain_modulation_caine():
    assert rain_modulation([10])[0] < 1  # 10 mm/h x 1 h is below 14.82 -> class drops
    assert rain_modulation([60] * 4)[-1] == 1.25  # 60 mm/h x 4 h far above 8.63 -> graded cap
    assert rain_modulation([8.63] * 4)[-1] == pytest.approx(1.0, abs=0.01)  # at threshold: unchanged
    assert rain_modulation([0])[0] == 0.75


def test_dynamic_classes_shift():
    lsi = np.full((2, 2), 0.5, np.float32)
    edges = [0.3, 0.4, 0.5, 0.6]  # static 0.5 -> class 4
    slope = np.full((2, 2), 30.0)
    for thr in ("caine", "dahal_hasegawa"):  # spec S5 acceptance: 10 mm/h x 1 h lowers, 60 mm/h x 4 h raises
        low = lsi_dynamic_classes(lsi, edges, [10], slope, threshold=thr)[0, 0, 0]
        high = lsi_dynamic_classes(lsi, edges, [60] * 4, slope, threshold=thr)[-1, 0, 0]
        assert low == 3 and high == 5
        g = lsi_dynamic_classes(lsi, edges, [60] * 4, slope, mode="graded_g", threshold=thr)[-1, 0, 0]
        assert g == 5
    # between 1x and 2x the threshold the static class holds; flat ground stays class 1
    mid = lsi_dynamic_classes(lsi, edges, [12] * 4, np.array([[30.0, 2.0], [30.0, 30.0]]))[-1]
    assert mid[0, 0] == 4 and mid[0, 1] == 1


def test_actionable_caps_untriggered_hours():
    dyn = np.array([[[5]], [[5]]], np.uint8)
    act = actionable(dyn, np.array([False, True]))
    assert act[0, 0, 0] == 3 and act[1, 0, 0] == 5
