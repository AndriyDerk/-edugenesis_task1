"""Statistics are checked against pymannkendall (independent reference
implementation) and against hand-computed values."""

from __future__ import annotations

import math
import random
import statistics

import pytest

from wikitrends import stats

pmk = pytest.importorskip("pymannkendall")


def _series(n: int, seed: int, trend: float = 0.0, ties: bool = False) -> list[float]:
    rng = random.Random(seed)
    xs = [100 + trend * i + 12 * math.sin(i * 2 * math.pi / 12) + rng.gauss(0, 8) for i in range(n)]
    return [float(round(x / 5) * 5) if ties else x for x in xs]


def test_median_quantile_match_statistics():
    rng = random.Random(1)
    for n in (1, 2, 5, 10, 33):
        xs = [rng.random() for _ in range(n)]
        assert stats.median(xs) == pytest.approx(statistics.median(xs))
        if n > 1:
            qs = statistics.quantiles(xs, n=4, method="inclusive")
            assert stats.quantile(xs, 0.25) == pytest.approx(qs[0])
            assert stats.quantile(xs, 0.75) == pytest.approx(qs[2])


@pytest.mark.parametrize("seed,trend,ties", [(1, 0.0, False), (2, 0.8, False), (3, -0.5, True), (4, 0.2, True)])
def test_mann_kendall_matches_reference(seed, trend, ties):
    xs = _series(36, seed, trend, ties)
    ours = stats.mann_kendall(xs)
    ref = pmk.original_test(xs)
    assert ours["s"] == pytest.approx(ref.s)
    assert ours["var"] == pytest.approx(ref.var_s)
    assert ours["z"] == pytest.approx(ref.z)
    assert ours["p"] == pytest.approx(ref.p)


@pytest.mark.parametrize("n", [24, 36, 48, 60])
@pytest.mark.parametrize("ties", [False, True])
def test_seasonal_kendall_matches_reference(n, ties):
    xs = _series(n, n, 0.3, ties)
    ours = stats.seasonal_kendall(xs, 12)
    ref = pmk.seasonal_test(xs, period=12)
    assert ours["s"] == pytest.approx(ref.s)
    assert ours["var"] == pytest.approx(ref.var_s)
    assert ours["p"] == pytest.approx(ref.p)


@pytest.mark.parametrize("n", [24, 36, 60])
def test_seasonal_sen_slope_matches_reference(n):
    xs = _series(n, 10 + n, 0.5)
    np = pytest.importorskip("numpy")
    ref = pmk.seasonal_sens_slope(np.asarray(xs), period=12).slope
    assert stats.seasonal_sen_slope(xs, 12) == pytest.approx(ref)


def test_sen_slope_matches_reference():
    xs = _series(40, 7, 1.3)
    assert stats.sen_slope(xs) == pytest.approx(pmk.sens_slope(xs).slope)


def test_seasonal_sen_recovers_known_growth():
    # log series growing exactly 20%/year with a seasonal pattern
    xs = [math.log(100 * 1.2 ** (i / 12) * (1 + 0.3 * math.sin(2 * math.pi * i / 12))) for i in range(48)]
    assert math.exp(stats.seasonal_sen_slope(xs, 12)) - 1 == pytest.approx(0.2, abs=1e-9)


def test_sign_test_known_values():
    assert stats.sign_test_p(12, 12) == pytest.approx(2 / 4096)
    assert stats.sign_test_p(10, 12) == pytest.approx(2 * (1 + 12 + 66) / 4096)
    assert stats.sign_test_p(6, 12) == 1.0
    assert stats.sign_test_p(0, 0) == 1.0


def test_bootstrap_is_deterministic_and_sane():
    prev = [100.0] * 12
    last = [120.0 + (i % 3) for i in range(12)]

    def stat(idx):
        return sum(last[i] for i in idx) / sum(prev[i] for i in idx) - 1

    a = stats.bootstrap_ci(12, stat, reps=2000, seed=5)
    b = stats.bootstrap_ci(12, stat, reps=2000, seed=5)
    assert a == b
    lo, hi = a
    assert lo <= stat(list(range(12))) <= hi
    assert 0.19 < lo < hi < 0.23


def test_short_inputs_do_not_crash():
    assert stats.mann_kendall([1, 2])["p"] == 1.0
    assert stats.seasonal_kendall([1.0] * 12)["p"] == 1.0
    assert stats.sen_slope([1.0]) is None
    assert stats.bootstrap_ci(1, lambda idx: 0.0) == (None, None)
