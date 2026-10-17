"""The Overpass tag filters OSMnx uses for walk/drive, applied locally to one combined download (osm.bundle)."""
import osmnx as ox

from app.services.osm import _FILTER, _passes


def _f(kind):
    return _FILTER.findall(ox._overpass._get_network_filter(kind))


def test_drive_and_walk_filters():
    drive, walk = _f("drive"), _f("walk")
    assert _passes({"highway": "primary"}, drive) and _passes({"highway": "primary"}, walk)
    assert not _passes({"highway": "footway"}, drive) and _passes({"highway": "footway"}, walk)
    assert not _passes({"highway": "motorway"}, walk) and _passes({"highway": "motorway"}, drive)
    assert not _passes({"highway": "residential", "access": "private"}, drive)
    assert not _passes({"highway": "service", "service": "driveway"}, drive)
    assert not _passes({"waterway": "canal"}, walk)  # no highway tag
