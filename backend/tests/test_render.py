import io

import numpy as np
from PIL import Image

from app.engines.render import to_png


def test_to_png_rgba_and_nodata_transparent():
    a = np.array([[0.0, 1.0], [np.nan, 0.5]])
    img = Image.open(io.BytesIO(to_png(a, "blues", 0, 1)))
    assert img.mode == "RGBA" and img.size == (2, 2)
    px = np.array(img)
    assert px[1, 0, 3] == 0 and px[0, 0, 3] > 0
    assert tuple(px[0, 0, :3]) == (239, 243, 255) and tuple(px[0, 1, :3]) == (8, 48, 107)
