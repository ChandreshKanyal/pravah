import numpy as np
import pytest

from app.engines.ahp import InconsistentMatrix, ahp_weights
from app.engines.fsi import FSI_MATRIX, factor_scores, fsi


def test_t8_flood_ahp():
    w, _, _, cr = ahp_weights(FSI_MATRIX)
    assert cr == pytest.approx(0.0128, abs=0.0005)
    assert w == pytest.approx([0.236, 0.165, 0.148, 0.148, 0.135, 0.092, 0.077], abs=0.002)


def test_inconsistent_matrix_raises():
    with pytest.raises(InconsistentMatrix):
        ahp_weights([[1, 9, 1 / 9], [1 / 9, 1, 9], [9, 1 / 9, 1]])


def test_fsi_valley_higher_than_ridge():
    one = np.ones((1, 2))
    s = factor_scores(hand=np.array([[0.5, 200.0]]), gfd_count=np.array([[2, 0]]), gsw_occ=np.array([[40.0, 0.0]]),
                      dist_stream_m=np.array([[20.0, 2000.0]]), upa=np.array([[5000.0, 0.1]]),
                      rain_clim=one * 90, slope_deg=np.array([[2.0, 40.0]]), C=one * 0.5)
    val, cls, meta = fsi(s)
    assert val[0, 0] > 0.8 and val[0, 1] < 0.2
    assert cls[0, 0] == 5 and cls[0, 1] == 1
    assert sum(meta["weights"]) == pytest.approx(1, abs=1e-3)
