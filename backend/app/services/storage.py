"""Cloud Storage I/O (S1.11): layer groups as .npz + grid.json, vectors as parquet/GraphML, overlay PNGs."""
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

from app.config import get_settings
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
    _bucket().blob(_path(aoi_id, name)).upload_from_string(data, content_type=content_type)


def get_bytes(aoi_id: str, name: str) -> bytes:
    return _bucket().blob(_path(aoi_id, name)).download_as_bytes()


def save_grid(aoi_id: str, grid: GridSpec) -> None:
    put_bytes(aoi_id, "grid.json", json.dumps(grid.to_dict()).encode(), "application/json")


def load_grid(aoi_id: str) -> GridSpec:
    return GridSpec.from_dict(json.loads(get_bytes(aoi_id, "grid.json")))


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
