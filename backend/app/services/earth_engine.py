"""Earth Engine I/O (S1.3-S1.6, S1.8). Dataset IDs verified against the EE catalog on 2026-10-15."""
import logging
from datetime import date

import ee
import geopandas as gpd
import numpy as np

from app.config import get_settings
from app.models.grid import GridSpec

log = logging.getLogger(__name__)

DEM_ID = "COPERNICUS/DEM/GLO30_2024_1"  # GLO30 is superseded by GLO30_2024_1 (verified)
MERIT_ID = "MERIT/Hydro/v1_0_1"
DW_ID = "GOOGLE/DYNAMICWORLD/V1"
S2_ID = "COPERNICUS/S2_SR_HARMONIZED"
CLAY_ID = "OpenLandMap/SOL/SOL_CLAY-WFRACTION_USDA-3A1A1A_M/v02"  # band b0 = surface
CHIRPS_ID = "UCSB-CHG/CHIRPS/DAILY"
GFD_ID = "GLOBAL_FLOOD_DB/MODIS_EVENTS/V1"
GSW_ID = "JRC/GSW1_4/GlobalSurfaceWater"  # GSW1_5 does not exist (verified)
WORLDPOP_ID = "WorldPop/GP/100m/pop"
WORLDPOP_YEAR = 2020  # latest year for IND in the catalog (verified)
LANDSLIDE_ID = "projects/sat-io/open-datasets/events/global_landslide_1970-2019"  # NASA GLC (verified access)
LANDSLIDE_ACCURACY_KM = {"exact": 0, "1km": 1, "5km": 5, "10km": 10, "25km": 25, "50km": 50}  # "unknown" dropped
OB_ID = "GOOGLE/Research/open-buildings/v3/polygons"
OBT_ID = "GOOGLE/Research/open-buildings-temporal/v1"

NODATA = -9999.0
MAX_REQUEST_BYTES = 40_000_000  # computePixels limit is ~48 MB; split below this
INT_KEYS = {"lc_class": np.int16, "d8": np.int16, "gfd_count": np.int16}

_initialised = False


def init_ee() -> None:
    """Initialise once per process, not per request."""
    global _initialised
    if not _initialised:
        ee.Initialize(project=get_settings().ee_project)
        _initialised = True


def ping() -> int:
    init_ee()
    return ee.Number(1).getInfo()


def grid_region(grid: GridSpec) -> ee.Geometry:
    init_ee()
    x1 = grid.x0 + grid.width * grid.cell
    y1 = grid.y0 - grid.height * grid.cell
    return ee.Geometry.Rectangle([grid.x0, y1, x1, grid.y0], proj=grid.crs, geodesic=False)


def resample(image: ee.Image, kind: str) -> ee.Image:
    """'bilinear' for continuous layers only. Never on class/code layers (lc_class, d8, upa, gfd_count)."""
    return image.resample("bilinear") if kind == "bilinear" else image


def _compute_block(image: ee.Image, grid: GridSpec, row0: int, col0: int, h: int, w: int) -> np.ndarray:
    # NOTE(spec-drift): request shape matches ee.data.computePixels docs (verified 2026-10-15).
    return ee.data.computePixels({
        "expression": image,
        "fileFormat": "NUMPY_NDARRAY",
        "grid": {
            "dimensions": {"width": w, "height": h},
            "affineTransform": {
                "scaleX": grid.cell, "shearX": 0, "translateX": grid.x0 + col0 * grid.cell,
                "shearY": 0, "scaleY": -grid.cell, "translateY": grid.y0 - row0 * grid.cell,
            },
            "crsCode": grid.crs,
        },
    })


def fetch_grid(image: ee.Image, grid: GridSpec, bands: list[str]) -> dict[str, np.ndarray]:
    """Fetch bands on the analysis grid. Masked pixels become NaN (float) or -1 (class keys)."""
    init_ee()
    img = image.select(bands).toFloat().unmask(NODATA)
    n_split = 1
    while grid.width * grid.height * len(bands) * 4 / n_split**2 > MAX_REQUEST_BYTES:
        n_split *= 2
    rows = np.array_split(np.arange(grid.height), n_split)
    cols = np.array_split(np.arange(grid.width), n_split)
    out = {b: np.empty((grid.height, grid.width), np.float32) for b in bands}
    for rr in rows:
        for cc in cols:
            arr = _compute_block(img, grid, int(rr[0]), int(cc[0]), len(rr), len(cc))
            for b in bands:
                out[b][rr[0]:rr[-1] + 1, cc[0]:cc[-1] + 1] = arr[b]
    for b in bands:
        nod = out[b] <= NODATA + 1
        if b in INT_KEYS:
            out[b] = np.where(nod, -1, np.rint(out[b])).astype(INT_KEYS[b])
        else:
            out[b][nod] = np.nan
    return out


def _last_dry_season(today: date) -> tuple[str, str]:
    """Most recent complete Oct 1 to Mar 31 window."""
    end_year = today.year if today >= date(today.year, 4, 1) else today.year - 1
    return f"{end_year - 1}-10-01", f"{end_year}-04-01"


def layer_images(grid: GridSpec, today: date | None = None) -> dict[str, ee.Image]:
    """One ee.Image per layer group; band names are the §4.2 keys."""
    today = today or date.today()
    r = grid_region(grid)

    dem_col = ee.ImageCollection(DEM_ID)
    dem = dem_col.filterBounds(r).select("DEM").mosaic().setDefaultProjection(dem_col.first().projection())

    merit = ee.Image(MERIT_ID)
    hydro = resample(merit.select(["hnd", "elv"], ["hand", "elv_hydro"]), "bilinear").addBands(
        merit.select(["upa", "dir"], ["upa", "d8"]))

    dw = ee.ImageCollection(DW_ID).filterBounds(r).filterDate(
        ee.Date(today.isoformat()).advance(-365, "day"), ee.Date(today.isoformat()))
    lc = dw.select("label").mode().rename("lc_class")
    d0, d1 = _last_dry_season(today)
    s2 = ee.ImageCollection(S2_ID).filterBounds(r).filterDate(d0, d1).filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", 20))
    ndvi = s2.median().normalizedDifference(["B8", "B4"]).rename("ndvi").setDefaultProjection(
        s2.first().select("B8").projection())
    clay = ee.Image(CLAY_ID).select(["b0"], ["soil_clay"])
    landcover = lc.addBands(resample(ndvi, "bilinear")).addBands(resample(clay, "bilinear"))

    chirps = ee.ImageCollection(CHIRPS_ID).select("precipitation")
    annual_max = ee.ImageCollection.fromImages(
        [chirps.filterDate(f"{y}-01-01", f"{y + 1}-01-01").max() for y in range(2001, 2025)])
    rain = annual_max.mean().rename("rain_clim").setDefaultProjection(chirps.first().projection())
    gfd = ee.ImageCollection(GFD_ID).select("flooded").sum().unmask(0).rename("gfd_count")
    gsw = ee.Image(GSW_ID).select(["occurrence"], ["gsw_occ"]).unmask(0)
    hazard = resample(rain, "bilinear").addBands(gfd).addBands(resample(gsw, "bilinear"))

    wp_col = ee.ImageCollection(WORLDPOP_ID).filterBounds(r).filter(ee.Filter.eq("year", WORLDPOP_YEAR))
    wp_proj = wp_col.first().projection()
    density = wp_col.mosaic().divide(ee.Image.pixelArea().reproject(wp_proj)).rename("pop_density")

    return {
        "terrain": resample(dem, "bilinear").rename("dem"),
        "hydro30": hydro,
        "landcover": landcover,
        "hazard_hist": hazard,
        "population": density.setDefaultProjection(wp_proj),
    }


GROUP_BANDS = {
    "terrain": ["dem"],
    "hydro30": ["hand", "elv_hydro", "upa", "d8"],
    "landcover": ["lc_class", "ndvi", "soil_clay"],
    "hazard_hist": ["rain_clim", "gfd_count", "gsw_occ"],
    "population": ["pop_density"],
}


def fetch_merit_native(hgrid) -> dict[str, np.ndarray]:
    """MERIT hnd/elv/upa/dir on MERIT's own 3-arcsecond grid, no resampling (S2.1). dir comes back as `d8`."""
    g = GridSpec(crs="EPSG:4326", x0=hgrid.lon0, y0=hgrid.lat0, cell=hgrid.cell_deg,
                 width=hgrid.width, height=hgrid.height)
    img = ee.Image(MERIT_ID).select(["hnd", "elv", "upa", "dir"], ["hnd", "elv", "upa", "d8"])
    return fetch_grid(img, g, ["hnd", "elv", "upa", "d8"])


def fetch_training_layers(train_grid: GridSpec) -> dict[str, np.ndarray]:
    """dem, ndvi, soil_clay, rain_clim, upa on a coarse grid for the landslide training region (S5.2)."""
    im = layer_images(train_grid)
    img = (im["terrain"].addBands(im["landcover"].select(["ndvi", "soil_clay"]))
           .addBands(im["hazard_hist"].select(["rain_clim"])).addBands(im["hydro30"].select(["upa"])))
    return fetch_grid(img, train_grid, ["dem", "ndvi", "soil_clay", "rain_clim", "upa"])


def fetch_landslides(train_grid: GridSpec, max_accuracy_km: float) -> list[tuple[float, float]]:
    """NASA Global Landslide Catalog points (lon, lat) in the training region with location accuracy <= max_accuracy_km."""
    init_ee()
    fc = ee.FeatureCollection(LANDSLIDE_ID).filterBounds(grid_region(train_grid))
    d = ee.Dictionary({k: fc.aggregate_array(k) for k in ("longitude", "latitude", "location_a")}).getInfo()
    return [(float(lo), float(la)) for lo, la, acc in zip(d["longitude"], d["latitude"], d["location_a"])
            if LANDSLIDE_ACCURACY_KM.get(str(acc), 1e9) <= max_accuracy_km]


def worldpop_total(grid: GridSpec) -> float:
    """WorldPop people inside the grid extent, summed at native resolution."""
    init_ee()
    r = grid_region(grid)
    col = ee.ImageCollection(WORLDPOP_ID).filterBounds(r).filter(ee.Filter.eq("year", WORLDPOP_YEAR))
    proj = col.first().projection()
    total = col.mosaic().setDefaultProjection(proj).reduceRegion(
        ee.Reducer.sum(), r, scale=proj.nominalScale(), maxPixels=1e9).get("population")
    return float(ee.Number(total).getInfo() or 0.0)


def fetch_buildings(bbox: tuple[float, float, float, float], grid: GridSpec) -> tuple[gpd.GeoDataFrame, list[str]]:
    """Open Buildings v3 (confidence >= 0.70) inside the AOI, with 2023 height/presence and 2016 presence."""
    init_ee()
    r = ee.Geometry.Rectangle(list(bbox))
    fc = ee.FeatureCollection(OB_ID).filterBounds(r).filter(ee.Filter.gte("confidence", 0.70))
    cols = ["bid", "geometry", "area_m2", "confidence", "height_m", "presence_2023", "presence_2016"]
    n = fc.size().getInfo()
    if n == 0:
        return gpd.GeoDataFrame(columns=cols, geometry="geometry", crs=grid.crs), ["No Open Buildings coverage here"]
    t = ee.ImageCollection(OBT_ID).filterBounds(r)
    proj = t.first().projection()
    img = (t.filterDate("2023-01-01", "2024-01-01").mosaic().select(["building_height", "building_presence"])
           .addBands(t.filterDate("2016-01-01", "2017-01-01").mosaic().select(["building_presence"], ["presence_2016"]))
           .setDefaultProjection(proj))
    reduced = img.reduceRegions(fc.select(["area_in_meters", "confidence"]), ee.Reducer.mean(), scale=4)
    # NOTE(spec-drift): computeFeatures with GEOPANDAS_GEODATAFRAME pages internally (verified 2026-10-15).
    gdf = ee.data.computeFeatures({"expression": reduced, "fileFormat": "GEOPANDAS_GEODATAFRAME"})
    if gdf.crs is None:
        gdf = gdf.set_crs("EPSG:4326")
    gdf = gdf.to_crs(grid.crs).rename(columns={
        "area_in_meters": "area_m2", "building_height": "height_m", "building_presence": "presence_2023"})
    for c in ("height_m", "presence_2023", "presence_2016"):
        if c not in gdf:
            gdf[c] = np.nan
    gdf["bid"] = [f"b{i}" for i in range(len(gdf))]
    log.info("buildings: %d", len(gdf))
    return gdf[cols].reset_index(drop=True), []
