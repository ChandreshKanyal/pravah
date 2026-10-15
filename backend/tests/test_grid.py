import numpy as np
import pytest
from pyproj import Geod

from app.engines.grid import corner_lonlats, lonlat_to_rowcol, make_grid, rowcol_to_lonlat, terrain, utm_epsg
from app.models.aoi import AOIRequest, AOIValidationError, aoi_id_for, build_aoi

RUDRA = (78.93, 30.24, 79.03, 30.33)  # ~10 km box, Rudraprayag


def test_utm_epsg():
    assert utm_epsg(78.98, 30.28) == 32644
    assert utm_epsg(72.88, 19.07) == 32643


def test_make_grid_snapped_and_buffered():
    g = make_grid(RUDRA)
    assert g.crs == "EPSG:32644" and g.cell == 30
    assert g.x0 % 90 == 0 and g.y0 % 90 == 0
    assert g.width % 3 == 0 and g.height % 3 == 0
    assert 500 < g.width < 600 and 500 < g.height < 600  # ~10 km + 2 x 3 km buffer


def test_t15_grid_round_trip_under_30m():
    g = make_grid(RUDRA)
    rng = np.random.default_rng(0)
    lon = rng.uniform(RUDRA[0], RUDRA[2], 200)
    lat = rng.uniform(RUDRA[1], RUDRA[3], 200)
    r, c = lonlat_to_rowcol(g, lon, lat)
    lon2, lat2 = rowcol_to_lonlat(g, r, c)
    _, _, d = Geod(ellps="WGS84").inv(lon, lat, lon2, lat2)
    assert np.max(d) < 30


def test_corner_lonlats_order():
    c = corner_lonlats(make_grid(RUDRA))
    bl, tl, tr, br = c
    assert tl[1] > bl[1] and tr[0] > tl[0] and br[1] < tr[1]


def test_t13_aspect():
    cols = np.tile(np.arange(10, dtype=float), (10, 1))
    rows = np.tile(np.arange(10, dtype=float)[:, None], (1, 10))
    east = terrain(cols * 3.0, 30)  # z rises east -> faces west
    north = terrain(-rows * 3.0, 30)  # rows go south, so -rows rises north -> faces south
    assert east["aspect_deg"][5, 5] == pytest.approx(270)
    assert north["aspect_deg"][5, 5] == pytest.approx(180)
    assert east["slope_deg"][5, 5] == pytest.approx(np.degrees(np.arctan(0.1)), abs=1e-4)


def test_flat_aspect_is_minus_one():
    assert (terrain(np.zeros((5, 5)), 30)["aspect_deg"] == -1).all()


def test_aoi_id_and_limits():
    assert aoi_id_for(RUDRA) == build_aoi(AOIRequest(bbox=RUDRA)).aoi_id
    assert len(aoi_id_for(RUDRA)) == 12
    with pytest.raises(AOIValidationError):
        build_aoi(AOIRequest(bbox=(78.0, 30.0, 78.3, 30.3)))  # ~29 km
    with pytest.raises(AOIValidationError):
        build_aoi(AOIRequest(bbox=(72.85, 19.05, 72.90, 19.10), mode="urban"))  # ~5 km > 4 km
