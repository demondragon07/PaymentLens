"""Statistics helpers: Wilson confidence interval and two-proportion z-test."""
from __future__ import annotations

import math

from scipy.stats import norm


def wilson_ci(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% confidence range for a rate (stays sensible near 0% and 100%)."""
    if n == 0:
        return (float("nan"), float("nan"))
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (centre - half, centre + half)


def two_proportion_z(s0: int, n0: int, s1: int, n1: int) -> tuple[float, float]:
    """Tests whether two rates are really different. Returns (z, p_value)."""
    if n0 == 0 or n1 == 0:
        return (float("nan"), float("nan"))
    p0, p1 = s0 / n0, s1 / n1
    pooled = (s0 + s1) / (n0 + n1)
    se = math.sqrt(pooled * (1 - pooled) * (1 / n0 + 1 / n1))
    if se == 0:
        return (0.0, 1.0)
    z = (p1 - p0) / se
    return (z, float(2 * (1 - norm.cdf(abs(z)))))
