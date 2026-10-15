"""Analytic Hierarchy Process weights (Saaty 1980)."""
import numpy as np

RI = {3: 0.58, 4: 0.90, 5: 1.12, 6: 1.24, 7: 1.32, 8: 1.41, 9: 1.45, 10: 1.49}


class InconsistentMatrix(ValueError):
    pass


def ahp_weights(M, max_cr: float = 0.10) -> tuple[np.ndarray, float, float, float]:
    """(weights, lambda_max, CI, CR) from the principal eigenvector. Raises if CR >= max_cr."""
    A = np.asarray(M, dtype=float)
    n = A.shape[0]
    vals, vecs = np.linalg.eig(A)
    k = int(np.argmax(vals.real))
    lam = float(vals[k].real)
    w = np.abs(vecs[:, k].real)
    w = w / w.sum()
    ci = (lam - n) / (n - 1)
    cr = ci / RI[n]
    if cr >= max_cr:
        raise InconsistentMatrix(f"AHP consistency ratio {cr:.3f} >= {max_cr}")
    return w, lam, ci, cr
