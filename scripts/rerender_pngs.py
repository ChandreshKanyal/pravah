"""Re-draw a run's map PNGs (flood depth) from its stored arrays, after a change to
app/engines/render.py. The model results are not touched. Ponding is not stored as an array, so it keeps its PNG.

    backend/.venv/bin/python scripts/rerender_pngs.py [run_id ...]     (default: latest run of every area)
"""
import io
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import numpy as np  # noqa: E402


def main() -> None:
    from app.engines.render import DEPTH_COLORS, DEPTH_EDGES, WATER_COLOR, to_png_binned
    from app.services import firestore as fs, storage

    ids = sys.argv[1:] or [a["latest_run_id"] for a in fs.query("aois") if a.get("latest_run_id")]
    for rid in ids:
        depth = np.load(io.BytesIO(storage.get_run(rid, "depth.npz")))["depth"].astype(np.float32)
        pngs = {f"depth_h{t + 1}": to_png_binned(depth[t], DEPTH_EDGES, DEPTH_COLORS, nan_color=WATER_COLOR) for t in range(depth.shape[0])}
        with ThreadPoolExecutor(8) as ex:
            list(ex.map(lambda kv: storage.put_run(rid, f"png/{kv[0]}.png", kv[1], "image/png"), pngs.items()))
        print(rid, len(pngs), "PNGs")


if __name__ == "__main__":
    main()
