"""Small, dependency-free statistics used by the analysis.

* Mann-Kendall and seasonal (Hirsch-Slack) Kendall trend tests with tie
  correction and continuity correction (matches ``pymannkendall``).
* Sen / seasonal Sen slope estimators.
* Percentile bootstrap with a seeded RNG, so every run is reproducible.
"""

from __future__ import annotations

import math
import random
from typing import Callable, Sequence


def median(xs: Sequence[float]) -> float:
    s = sorted(xs)
    n = len(s)
    if n == 0:
        raise ValueError("median of empty sequence")
    mid = n // 2
    return float(s[mid]) if n % 2 else (s[mid - 1] + s[mid]) / 2.0


def quantile(xs: Sequence[float], q: float) -> float:
    """Linear-interpolation quantile (numpy's default method)."""
    s = sorted(xs)
    if not s:
        raise ValueError("quantile of empty sequence")
    pos = (len(s) - 1) * q
    lo = math.floor(pos)
    hi = math.ceil(pos)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def mad(xs: Sequence[float], center: float | None = None) -> float:
    c = median(xs) if center is None else center
    return median([abs(x - c) for x in xs])


def normal_two_sided_p(z: float) -> float:
    return math.erfc(abs(z) / math.sqrt(2.0))


def _sign(v: float) -> int:
    return (v > 0) - (v < 0)


def _mk_s_var(x: Sequence[float]) -> tuple[float, float]:
    n = len(x)
    s = 0
    for i in range(n - 1):
        xi = x[i]
        for j in range(i + 1, n):
            s += _sign(x[j] - xi)
    counts: dict[float, int] = {}
    for v in x:
        counts[v] = counts.get(v, 0) + 1
    ties = sum(t * (t - 1) * (2 * t + 5) for t in counts.values() if t > 1)
    var = (n * (n - 1) * (2 * n + 5) - ties) / 18.0
    return float(s), var


def _z(s: float, var: float) -> float:
    if var <= 0 or s == 0:
        return 0.0
    return (s - 1) / math.sqrt(var) if s > 0 else (s + 1) / math.sqrt(var)


def mann_kendall(x: Sequence[float | None]) -> dict[str, float]:
    vals = [v for v in x if v is not None and not math.isnan(v)]
    if len(vals) < 3:
        return {"s": 0.0, "var": 0.0, "z": 0.0, "p": 1.0, "n": len(vals)}
    s, var = _mk_s_var(vals)
    z = _z(s, var)
    return {"s": s, "var": var, "z": z, "p": normal_two_sided_p(z), "n": len(vals)}


def seasonal_kendall(x: Sequence[float | None], period: int = 12) -> dict[str, float]:
    """Seasonal Kendall test: Mann-Kendall within each season, summed.
    Robust to seasonality because only same-season values are compared."""
    s_total = 0.0
    var_total = 0.0
    pairs = 0
    for season in range(period):
        vals = [v for v in x[season::period] if v is not None and not math.isnan(v)]
        if len(vals) < 2:
            continue
        s, var = _mk_s_var(vals)
        s_total += s
        var_total += var
        pairs += len(vals) * (len(vals) - 1) // 2
    z = _z(s_total, var_total)
    return {"s": s_total, "var": var_total, "z": z, "p": normal_two_sided_p(z) if var_total > 0 else 1.0,
            "pairs": pairs}


def sen_slope(x: Sequence[float | None]) -> float | None:
    pts = [(i, v) for i, v in enumerate(x) if v is not None and not math.isnan(v)]
    slopes = [(vj - vi) / (j - i) for a, (i, vi) in enumerate(pts) for (j, vj) in pts[a + 1:]]
    return median(slopes) if slopes else None


def seasonal_sen_slope(x: Sequence[float | None], period: int = 12) -> float | None:
    """Median of within-season slopes; unit = change per full period (year)."""
    slopes: list[float] = []
    for season in range(period):
        col = list(x[season::period])
        pts = [(i, v) for i, v in enumerate(col) if v is not None and not math.isnan(v)]
        for a, (i, vi) in enumerate(pts):
            for j, vj in pts[a + 1:]:
                slopes.append((vj - vi) / (j - i))
    return median(slopes) if slopes else None


def sign_test_p(k: int, n: int) -> float:
    """Two-sided exact binomial sign test for k successes out of n (p=0.5)."""
    if n == 0:
        return 1.0
    tail = min(k, n - k)
    prob = sum(math.comb(n, i) for i in range(tail + 1)) / 2 ** n
    return min(1.0, 2 * prob)


def bootstrap_ci(
    n: int,
    statistic: Callable[[list[int]], float | None],
    reps: int = 4000,
    alpha: float = 0.10,
    seed: int = 12345,
) -> tuple[float | None, float | None]:
    """Percentile bootstrap CI of ``statistic(indices)`` resampling 0..n-1."""
    if n < 2:
        return None, None
    rng = random.Random(seed)
    values = []
    for _ in range(reps):
        idx = [rng.randrange(n) for _ in range(n)]
        v = statistic(idx)
        if v is not None and not math.isnan(v) and not math.isinf(v):
            values.append(v)
    if len(values) < reps * 0.5:
        return None, None
    return quantile(values, alpha / 2), quantile(values, 1 - alpha / 2)


def safe_ratio(num: float, den: float) -> float | None:
    return num / den if den else None
