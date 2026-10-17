"""Cloud Storage I/O (S1.11): layer groups as .npz + grid.json, vectors as parquet/GraphML, overlay PNGs."""
import gzip
import io
import json
import os
import tempfile
from functools import lru_cache

import geopandas as gpd
import networkx as nx
import numpy as np
import osmnx as ox
from google.cloud import storage
from google.cloud.storage.retry import DEFAULT_RETRY

from app.config import get_settings

UPLOAD_TIMEOUT_S = 300  # slow home uplinks: an 11 MB GeoJSON timed out at the 60 s default
UPLOAD_RETRY = DEFAULT_RETRY.with_timeout(600)  # overall retry budget (library default 120 s)
from app.models.grid import GridSpec


@lru_cache
def _bucket() -> storage.Bucket:
    s = get_settings()
    return storage.Client(project=s.google_cloud_project).bucket(s.gcs_bucket)


def _path(aoi_id: str, name: str) -> str:
    return f"aoi/{aoi_id}/{name}"


def exists(aoi_id: str, name: str) -> bool:
    return _bucket().blob(_path(aoi_id, name)).exists()


def put_bytes(aoi_id: str, name: str, data: bytes, content_type: str = "application/octet-stream") -> None:
    _bucket().blob(_path(aoi_id, name)).upload_from_string(data, content_type=content_type, timeout=UPLOAD_TIMEOUT_S, retry=UPLOAD_RETRY)


def get_bytes(aoi_id: str, name: str) -> bytes:
    return _bucket().blob(_path(aoi_id, name)).download_as_bytes()


def save_grid(aoi_id: str, grid: GridSpec) -> None:
    put_bytes(aoi_id, "grid.json", json.dumps(grid.to_dict()).encode(), "application/json")


def load_grid(aoi_id: str) -> GridSpec:
    return GridSpec.from_dict(json.loads(get_bytes(aoi_id, "grid.json")))


def put_json(aoi_id: str, name: str, obj) -> None:
    put_bytes(aoi_id, name, json.dumps(obj).encode(), "application/json")


def get_json(aoi_id: str, name: str):
    return json.loads(get_bytes(aoi_id, name))


def save_layers(aoi_id: str, group: str, arrays: dict[str, np.ndarray], grid: GridSpec) -> None:
    buf = io.BytesIO()
    np.savez_compressed(buf, **arrays)
    put_bytes(aoi_id, f"{group}.npz", buf.getvalue())
    save_grid(aoi_id, grid)


def load_layers(aoi_id: str, group: str) -> dict[str, np.ndarray]:
    with np.load(io.BytesIO(get_bytes(aoi_id, f"{group}.npz"))) as z:
        return {k: z[k] for k in z.files}


def save_gdf(aoi_id: str, name: str, gdf: gpd.GeoDataFrame) -> None:
    buf = io.BytesIO()
    gdf.to_parquet(buf)
    put_bytes(aoi_id, name, buf.getvalue())


def load_gdf(aoi_id: str, name: str) -> gpd.GeoDataFrame:
    return gpd.read_parquet(io.BytesIO(get_bytes(aoi_id, name)))


def save_graph(aoi_id: str, name: str, G: nx.MultiDiGraph) -> None:
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, name)
        ox.save_graphml(G, p)
        with open(p, "rb") as f:
            put_bytes(aoi_id, name, f.read(), "application/xml")


def load_graph(aoi_id: str, name: str) -> nx.MultiDiGraph:
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, name)
        with open(p, "wb") as f:
            f.write(get_bytes(aoi_id, name))
        return ox.load_graphml(p)


def save_png(aoi_id: str, name: str, png: bytes) -> str:
    """Store an overlay PNG and return its URL, served through the backend (see api/layers.py)."""
    put_bytes(aoi_id, f"png/{name}.png", png, "image/png")
    return f"/api/layers/{aoi_id}/{name}.png"



def put_run(run_id: str, name: str, data: bytes, content_type: str = "application/octet-stream") -> None:
    """JSON/GeoJSON is stored gzip-encoded (about 10x smaller); GCS decompresses on download for clients that do not
    ask for gzip, so get_run still returns the plain bytes."""
    blob = _bucket().blob(f"runs/{run_id}/{name}")
    if name.endswith((".json", ".geojson")) and len(data) > 4096:
        blob.content_encoding = "gzip"
        data = gzip.compress(data, 6)
    blob.upload_from_string(data, content_type=content_type, timeout=UPLOAD_TIMEOUT_S, retry=UPLOAD_RETRY)


def run_exists(run_id: str, name: str) -> bool:
    return _bucket().blob(f"runs/{run_id}/{name}").exists()


def get_run(run_id: str, name: str) -> bytes:
    return _bucket().blob(f"runs/{run_id}/{name}").download_as_bytes()


def put_run_gz(run_id: str, name: str, data: bytes, content_type: str = "application/octet-stream") -> None:
    """Large binaries stored gzip-encoded and served as-is with Content-Encoding: gzip (see get_run_gz)."""
    blob = _bucket().blob(f"runs/{run_id}/{name}")
    blob.content_encoding = "gzip"
    blob.upload_from_string(gzip.compress(data, 6), content_type=content_type, timeout=UPLOAD_TIMEOUT_S, retry=UPLOAD_RETRY)


def get_run_gz(run_id: str, name: str) -> bytes:
    """The stored gzip bytes, not decompressed."""
    return _bucket().blob(f"runs/{run_id}/{name}").download_as_bytes(raw_download=True)
