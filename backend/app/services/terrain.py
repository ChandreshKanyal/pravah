"""Bare-earth terrain per area for water flow and the 3D view.

Copernicus GLO-30 is a surface model: tree canopy and buildings are part of the ground, so a forest clearing reads as
a 15-20 m pit and a street as a trench, and water run over it pools in places that are dry in reality. FABDEM
(Hawker et al. 2022) removes forests and buildings from the same data. Urban areas already store it (pluvial
dem_bare); other areas fetch it once from Earth Engine and keep it as the layer group "bare".
"""
import logging
from functools import lru_cache

import numpy as np
from google.api_core.exceptions import NotFound

from app.services import storage

log = logging.getLogger(__name__)
FABDEM = "FABDEM bare earth (Hawker et al. 2022)"
GLO30 = "Copernicus GLO-30 surface model (FABDEM unavailable)"


@lru_cache(maxsize=4)
def bare_dem(aoi_id: str) -> tuple[np.ndarray, str]:
    """(DEM on the analysis grid, source label). Treat the array as read-only: it is shared."""
    try:
        return storage.load_layers(aoi_id, "bare")["dem"], FABDEM
    except (NotFound, KeyError):
        pass
    try:
        pl = storage.load_layers(aoi_id, "pluvial")
        if "dem_bare" in pl:
            return pl["dem_bare"], FABDEM
    except (NotFound, KeyError):
        pass
    try:
        from app.services import earth_engine as ees
        ees.init_ee()
        grid = storage.load_grid(aoi_id)
        dem = ees.fetch_fabdem(grid).astype(np.float32)
        if np.isnan(dem).all():
            raise ValueError("FABDEM has no data here")
        storage.save_layers(aoi_id, "bare", {"dem": dem}, grid)
        return dem, FABDEM
    except Exception as e:  # noqa: BLE001
        log.warning("bare DEM for %s unavailable (%s); using the surface model", aoi_id, e)
        return storage.load_layers(aoi_id, "terrain")["dem"], GLO30


@lru_cache(maxsize=4)
def flow_ground(aoi_id: str) -> tuple[np.ndarray, dict]:
    """Ground for water flow and the 3D view: bare earth, hydrologically conditioned (breached) in hilly areas so
    streams pass the false dams a 30 m grid makes of narrow gorges and bridges. Urban areas keep their depressions:
    street ponding is the hazard there."""
    dem, src = bare_dem(aoi_id)
    if storage.exists(aoi_id, "pluvial.npz"):
        return dem, {"source": src, "conditioned": False}
    try:
        return storage.load_layers(aoi_id, "flowdem")["dem"], {"source": src, "conditioned": True, **storage.get_json(aoi_id, "flowdem.json")}
    except (NotFound, KeyError):
        pass
    from app.engines.swe import condition
    w, st = condition(dem)
    storage.save_layers(aoi_id, "flowdem", {"dem": w}, storage.load_grid(aoi_id))
    storage.put_json(aoi_id, "flowdem.json", st)
    return w, {"source": src, "conditioned": True, **st}
