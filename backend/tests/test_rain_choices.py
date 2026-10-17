"""Rain choices shared by every source (17 Oct): shape, strength against the source, record rarity."""
import numpy as np
import pytest

from app.engines import improvements as imp, rainfall
from app.models.scenario import ScenarioParams
from app.pipeline.run_pipeline import with_strength


def test_gumbel_factors():
    # textbook EV1 frequency factors (infinite sample)
    assert rainfall.gumbel_k(10) == pytest.approx(1.305, abs=0.002)
    assert rainfall.gumbel_k(100) == pytest.approx(3.137, abs=0.002)
    x = [19.0, 18.7, 21.4, 13.8, 22.4, 8.0, 26.3, 17.4, 19.5, 19.6, 13.1, 19.8]
    lv = [rainfall.return_level_mm(x, T) for T in (2, 10, 25, 100)]
    assert lv == sorted(lv) and lv[0] < np.mean(x) < lv[1]


def test_cloudburst_shape_is_a_choice_and_says_so():
    early, lab_e = rainfall.preset_series("cloudburst", 8)  # default stays early-peaked
    steady, lab_s = rainfall.preset_series("cloudburst", 8, shape="constant")
    assert max(early) == pytest.approx(100, abs=0.5) and "not a cloudburst" not in lab_e
    assert sum(steady) == pytest.approx(sum(early)) and max(steady) == pytest.approx(25, abs=0.1)
    assert "not a cloudburst" in lab_s


def test_strength_is_labelled_and_capped():
    p = ScenarioParams(aoi_id="x", rain_scale=1.5)
    s, label, _, _ = with_strength(([10.0, 250.0], "Forecast Mon", [], None, "forecast"), p)
    assert s == [15.0, 300.0] and "not the actual forecast" in label
    s, label, _, _ = with_strength(([10.0], "Your own", [], None, None), p)  # your own intensity is not scaled
    assert s == [10.0] and "not the actual" not in label


def test_channel_leads_need_water_seen_from_space():
    ch = np.zeros((40, 40), bool)
    ch[:, 20] = True
    arr = {"ndvi": np.where(ch, 0.5, 0.2), "water_occ": np.zeros((40, 40))}
    rc2ll = lambda r, c: (float(c), float(r))  # noqa: E731
    assert imp.choked_channels(arr, ch, None, rc2ll, ("a", "b", 3), False) == []  # never held water: too narrow / dry
    arr["water_occ"] = np.where(ch, 30.0, 0.0)
    assert len(imp.choked_channels(arr, ch, None, rc2ll, ("a", "b", 3), False)) == 1


def test_rain_change_rules_match_the_panel():
    from app.models.scenario import apply_rain_change
    p = {"rain_source": "forecast", "rain_scale": 1.5, "rain_shape": "constant", "return_period_y": 25, "hyetograph": "constant",
         "rain_series_override": [1.0], "preset_label": "x"}
    q = apply_rain_change({**p, "hyetograph": "triangular_front"}, {"hyetograph"})
    assert q["rain_shape"] == "triangular_front" and q["rain_scale"] == 1.5 and q["rain_series_override"] is None
    q = apply_rain_change({**p, "rain_source": "manual"}, {"rain_source"})
    assert q["rain_scale"] == 1.0 and q["rain_shape"] is None and q["return_period_y"] is None
    q = apply_rain_change({**p, "forecast_day_index": 2}, {"forecast_day_index"})  # another day keeps the strength
    assert q["rain_scale"] == 1.5
    assert apply_rain_change(dict(p), {"travel_mode"}) == p  # not a rain change


def test_overpass_selectors_follow_the_tag_lists():
    from app.services.osm import POI_TAGS, WATERWAY_TAGS, _selector
    assert _selector("amenity", True) == 'nwr["amenity"]'
    assert _selector("tourism", ["hotel", "hostel"]) == 'nwr["tourism"~"^(hotel|hostel)$"]'
    assert len([_selector(k, v) for k, v in {**POI_TAGS, **WATERWAY_TAGS}.items()]) == len({**POI_TAGS, **WATERWAY_TAGS})
