"""Earth Engine I/O (S1.3-S1.6, S1.8). Dataset IDs verified against the EE catalog on 2026-10-15."""
import logging
from datetime import date, datetime, timezone

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
GRIP_ID = "projects/sat-io/open-datasets/GRIP4/South-East-Asia"  # GRIP4 roads, region 6 (verified access)
FABDEM_ID = "projects/sat-io/open-datasets/FABDEM"  # Copernicus DEM with forests and buildings removed (verified access)
ROAD_SEARCH_M = 5000
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


def layer_images(grid: GridSpec, today: date | None = None, bare_earth: bool = False) -> dict[str, ee.Image]:
    """One ee.Image per layer group; band names are the §4.2 keys.

    bare_earth (urban mode): terrain from FABDEM instead of Copernicus GLO-30, whose buildings would turn streets into
    pits and building edges into "slopes" (wrong ponding, landslide classes and walking times)."""
    today = today or date.today()
    r = grid_region(grid)

    dem_col = ee.ImageCollection(FABDEM_ID if bare_earth else DEM_ID)
    band = "b1" if bare_earth else "DEM"
    dem = dem_col.filterBounds(r).select([band], ["DEM"]).mosaic().setDefaultProjection(dem_col.first().projection())

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
    # GFD `flooded` includes permanent water; count only flood water (flooded and not jrc_perm_water)
    gfd = (ee.ImageCollection(GFD_ID).map(lambda i: i.select("flooded").And(i.select("jrc_perm_water").Not()))
           .sum().unmask(0).rename("gfd_count"))
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


def fetch_training_layers(train_grid: GridSpec, bare_earth: bool = False) -> dict[str, np.ndarray]:
    """dem, ndvi, soil_clay, rain_clim, upa and dist_road_m (GRIP4 global roads) on a coarse grid for the landslide
    training region (S5.2). OSM is not fetched for the 100 km box; GRIP4 gives the road factor a real distribution."""
    im = layer_images(train_grid, bare_earth=bare_earth)  # same DEM family as the AOI terrain
    roads = (ee.FeatureCollection(GRIP_ID).filterBounds(grid_region(train_grid))
             .distance(searchRadius=ROAD_SEARCH_M, maxError=30).unmask(ROAD_SEARCH_M).rename("dist_road_m"))
    img = (im["terrain"].addBands(im["landcover"].select(["ndvi", "soil_clay"]))
           .addBands(im["hazard_hist"].select(["rain_clim"])).addBands(im["hydro30"].select(["upa"])).addBands(roads))
    return fetch_grid(img, train_grid, ["dem", "ndvi", "soil_clay", "rain_clim", "upa", "dist_road_m"])


def fetch_landslides(train_grid: GridSpec, max_accuracy_km: float) -> list[tuple[float, float]]:
    """NASA Global Landslide Catalog points (lon, lat) in the training region with location accuracy <= max_accuracy_km."""
    init_ee()
    fc = ee.FeatureCollection(LANDSLIDE_ID).filterBounds(grid_region(train_grid))
    d = ee.Dictionary({k: fc.aggregate_array(k) for k in ("longitude", "latitude", "location_a")}).getInfo()
    return [(float(lo), float(la)) for lo, la, acc in zip(d["longitude"], d["latitude"], d["location_a"])
            if LANDSLIDE_ACCURACY_KM.get(str(acc), 1e9) <= max_accuracy_km]


IMERG_ID = "NASA/GPM_L3/IMERG_V07"  # V06 deprecated (verified); half-hourly mm/h


def chirps_max_daily_mm(lon: float, lat: float) -> float:
    """Max daily CHIRPS total 2001-2024 within 5 km of the point (S10.5 historical extreme)."""
    init_ee()
    g = ee.Geometry.Point([lon, lat]).buffer(5000)
    img = ee.ImageCollection(CHIRPS_ID).filterDate("2001-01-01", "2025-01-01").select("precipitation").max()
    v = img.reduceRegion(ee.Reducer.max(), g, scale=5566, maxPixels=1e8).get("precipitation")
    return float(ee.Number(v).getInfo() or 0.0)


def chirps_annual_max(lon: float, lat: float, years: range = range(2001, 2025)) -> list[dict]:
    """Wettest day of each year (mm) within 5 km of the point and its date: CHIRPS daily, same area and scale as
    `chirps_max_daily_mm`, so the largest of these is the record. One server-side map, one getInfo."""
    init_ee()
    g = ee.Geometry.Point([lon, lat]).buffer(5000)
    col = ee.ImageCollection(CHIRPS_ID).select("precipitation")

    def year(y):
        y = ee.Number(y)
        yc = col.filterDate(ee.Date.fromYMD(y, 1, 1), ee.Date.fromYMD(y.add(1), 1, 1)).map(
            lambda im: im.addBands(ee.Image.constant(im.date().millis()).rename("t").toDouble()))
        top = yc.qualityMosaic("precipitation").select(["precipitation", "t"])
        v = top.reduceRegion(ee.Reducer.max(2).setOutputs(["mm", "t"]), g, 5566, maxPixels=1e8)
        return ee.Feature(None, {"year": y, "mm": v.get("mm"), "t": v.get("t")})
    fc = ee.FeatureCollection(ee.List(list(years)).map(year)).getInfo()
    out = []
    for f in fc["features"]:
        pr = f["properties"]
        if pr.get("mm") is None:
            continue
        d = datetime.fromtimestamp(pr["t"] / 1000, tz=timezone.utc).date().isoformat() if pr.get("t") else None
        out.append({"year": int(pr["year"]), "mm": round(float(pr["mm"]), 1), "date": d})
    return out


def imerg_daily(lon: float, lat: float, end: date, days: int = 90) -> list[dict]:
    """Daily rain totals (mm) for the `days` before `end`, mean over 5 km; one server-side sequence, one getInfo."""
    init_ee()
    g = ee.Geometry.Point([lon, lat]).buffer(5000)
    col = ee.ImageCollection(IMERG_ID).select("precipitation")
    start = ee.Date(end.isoformat()).advance(-days, "day")

    def day(i):
        d = start.advance(i, "day")
        day_col = col.filterDate(d, d.advance(1, "day"))
        total = ee.Image(ee.Algorithms.If(day_col.size().gt(0), day_col.sum().multiply(0.5),
                                          ee.Image.constant(-1).rename("precipitation")))  # -1 = not yet published
        return ee.Feature(None, {"date": d.format("YYYY-MM-dd"),
                                 "mm": total.reduceRegion(ee.Reducer.mean(), g, 10000).get("precipitation")})
    fc = ee.FeatureCollection(ee.List.sequence(0, days - 1).map(day)).getInfo()
    out = []
    for f in fc["features"]:
        mm = f["properties"].get("mm")
        out.append({"date": f["properties"]["date"],
                    "precip_mm": None if mm is None or mm < 0 else round(float(mm), 2)})
    return out


def imerg_hourly(lon: float, lat: float, start: str, hours: int = 48) -> list[float]:
    """Hourly rain (mm) from IMERG V07 half-hourly rates, mean within 5 km, for `hours` from `start` (UTC ISO).
    Used for historical event replays (S18 credibility); IMERG under-reads intense convective cores."""
    init_ee()
    g = ee.Geometry.Point([lon, lat]).buffer(5000)
    col = ee.ImageCollection(IMERG_ID).select("precipitation")
    t0 = ee.Date(start)

    def hour(i):
        t = t0.advance(i, "hour")
        c = col.filterDate(t, t.advance(1, "hour"))
        img = ee.Image(ee.Algorithms.If(c.size().gt(0), c.mean(), ee.Image.constant(0).rename("precipitation")))  # mean rate = mm in that hour
        return ee.Feature(None, {"mm": img.reduceRegion(ee.Reducer.mean(), g, 10000).get("precipitation")})
    fc = ee.FeatureCollection(ee.List.sequence(0, hours - 1).map(hour)).getInfo()
    return [round(float(f["properties"].get("mm") or 0.0), 2) for f in fc["features"]]


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


def fetch_fabdem(grid: GridSpec) -> np.ndarray:
    """Bare-earth DEM (FABDEM, Hawker et al. 2022) on the analysis grid, for urban ponding: GLO-30 is a surface model
    whose buildings turn streets into deep artificial pits."""
    init_ee()
    col = ee.ImageCollection(FABDEM_ID)
    img = col.filterBounds(grid_region(grid)).mosaic().setDefaultProjection(col.first().projection()).rename("dem_bare")
    return fetch_grid(resample(img, "bilinear"), grid, ["dem_bare"])["dem_bare"]


def s2_rgb(grid: GridSpec, k: int = 3) -> np.ndarray:
    """Cloud-masked Sentinel-2 true colour (median of the last dry season) on the grid at cell / k, uint8 RGB, for the
    3D terrain texture. Copernicus Sentinel data are free and open (attribution required)."""
    init_ee()
    region = grid_region(grid)
    d0, d1 = _last_dry_season(date.today())

    def clear(img):
        scl = img.select("SCL")  # 3 cloud shadow, 8-9 cloud, 10 cirrus
        return img.updateMask(scl.neq(3).And(scl.neq(8)).And(scl.neq(9)).And(scl.neq(10)))

    col = (ee.ImageCollection(S2_ID).filterBounds(region).filterDate(d0, d1)
           .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", 40)).map(clear))
    img = col.select(["B4", "B3", "B2"]).median().visualize(min=0, max=2600, gamma=1.2)
    fine = GridSpec(crs=grid.crs, x0=grid.x0, y0=grid.y0, cell=grid.cell / k, width=grid.width * k, height=grid.height * k)
    arr = _compute_block(img, fine, 0, 0, fine.height, fine.width)
    return np.stack([arr["vis-red"], arr["vis-green"], arr["vis-blue"]], axis=-1).astype(np.uint8)


# ---------- improvements: open imagery that may legally be analysed by AI (Copernicus Sentinel, Dynamic World, JRC) ----------
S2_L1C_ID = "COPERNICUS/S2_HARMONIZED"  # top-of-atmosphere, archive from 2015 (SR coverage over India starts later)
EARLY = ("2016-01-01", "2017-12-31")    # "before": the first full years of Sentinel-2 and Dynamic World


def box_grid(grid: GridSpec, bbox, cell: float = 10.0) -> GridSpec:
    """A grid over the drawn box only (in the analysis grid's CRS) at Sentinel-2 resolution."""
    from app.engines.grid import _to_utm
    w, s, e, n = bbox
    xs, ys = _to_utm(grid.crs).transform([w, e, e, w], [s, s, n, n])
    x0, y1 = min(xs), min(ys)
    return GridSpec(crs=grid.crs, x0=float(x0), y0=float(max(ys)), cell=cell,
                    width=int(np.ceil((max(xs) - x0) / cell)), height=int(np.ceil((max(ys) - y1) / cell)))


def _l1c_clear(img):
    qa = img.select("QA60")  # bits 10 and 11: opaque cloud and cirrus
    return img.updateMask(qa.bitwiseAnd(1 << 10).eq(0).And(qa.bitwiseAnd(1 << 11).eq(0)))


def _sr_clear(img):
    scl = img.select("SCL")  # 3 cloud shadow, 8-9 cloud, 10 cirrus
    return img.updateMask(scl.neq(3).And(scl.neq(8)).And(scl.neq(9)).And(scl.neq(10)))


def recent_window(region, today: date, days: int = 75, max_cloud: int = 60) -> tuple[ee.ImageCollection, str, str, int]:
    """Clear Sentinel-2 surface reflectance from the last `days` days; falls back to the last dry season when the
    monsoon left too few scenes. Returns (collection, start, end, scenes)."""
    from datetime import timedelta
    d1 = today.isoformat()
    d0 = (today - timedelta(days=days)).isoformat()
    col = ee.ImageCollection(S2_ID).filterBounds(region).filterDate(d0, d1).filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", max_cloud))
    n = int(col.size().getInfo())
    if n < 2:
        d0, d1 = _last_dry_season(today)
        col = ee.ImageCollection(S2_ID).filterBounds(region).filterDate(d0, d1).filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", 30))
        n = int(col.size().getInfo())
    return col.map(_sr_clear), d0, d1, n


def improvement_layers(grid: GridSpec, bbox, today: date | None = None) -> dict:
    """10 m arrays over the box: recent NDVI and MNDWI, JRC water occurrence, Dynamic World built and wet probability
    then (2016-17) and now (last 12 months). Plus the dates used."""
    init_ee()
    today = today or date.today()
    bg = box_grid(grid, bbox)
    region = grid_region(bg)
    col, d0, d1, n = recent_window(region, today)
    med = col.median()
    ndvi = med.normalizedDifference(["B8", "B4"]).rename("ndvi")
    mndwi = med.normalizedDifference(["B3", "B11"]).rename("mndwi")
    occ = ee.Image(GSW_ID).select(["occurrence"], ["water_occ"])
    dw = ee.ImageCollection(DW_ID).filterBounds(region)
    then = dw.filterDate(*EARLY)
    now = dw.filterDate(ee.Date(today.isoformat()).advance(-365, "day"), ee.Date(today.isoformat()))
    built_then = then.select("built").mean().rename("built_then")
    built_now = now.select("built").mean().rename("built_now")
    wet_then = then.select("water").mean().add(then.select("flooded_vegetation").mean()).rename("wet_then")
    bare_then = then.select("bare").mean().rename("bare_then")
    bare_now = now.select("bare").mean().rename("bare_now")
    img = (ndvi.addBands(mndwi).addBands(occ.unmask(0)).addBands(built_then).addBands(built_now).addBands(wet_then)
           .addBands(bare_then).addBands(bare_now))
    arr = fetch_grid(img, bg, ["ndvi", "mndwi", "water_occ", "built_then", "built_now", "wet_then", "bare_then", "bare_now"])
    return {"grid": bg, "arrays": arr, "recent": (d0, d1, n), "early": EARLY,
            "built_now_window": ((today.replace(year=today.year - 1)).isoformat(), today.isoformat())}


def s2_chip(lon: float, lat: float, window: tuple[str, str], half_m: float = 300, false_colour: bool = False,
            l1c: bool = False, px: int = 384) -> bytes:
    """A small Sentinel-2 picture around a point (true colour, or false colour where vegetation is red), median of the
    clear scenes in `window`. Copernicus Sentinel data: free and open, attribution required."""
    import requests
    init_ee()
    pt = ee.Geometry.Point([lon, lat])
    rect = pt.buffer(half_m).bounds()
    col = ee.ImageCollection(S2_L1C_ID if l1c else S2_ID).filterBounds(rect).filterDate(*window).filter(
        ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", 60)).map(_l1c_clear if l1c else _sr_clear)
    bands = ["B8", "B4", "B3"] if false_colour else ["B4", "B3", "B2"]
    vis = col.select(bands).median().visualize(min=0, max=3200 if false_colour else 2600, gamma=1.2)
    url = vis.getThumbURL({"region": rect, "dimensions": px, "format": "png"})
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    return r.content
