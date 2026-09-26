from __future__ import annotations

import datetime as dt
import math
import random

from wikitrends import series

DAYS = [dt.date(2024, 9, 1) + dt.timedelta(days=i) for i in range(730)]


def _poisson(rng: random.Random, lam: float) -> int:
    # Knuth for small lambda, normal approximation for large
    if lam > 50:
        return max(0, int(round(rng.gauss(lam, math.sqrt(lam)))))
    k, p, limit = 0, 1.0, math.exp(-lam)
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1


def _noisy(level, growth=0.0, seed=1, noise=0.10):
    rng = random.Random(seed)
    return [level * (1 + growth) ** (i / 365) * math.exp(rng.gauss(0, noise)) for i in range(len(DAYS))]


def test_dense_daily_fills_zero_days():
    pts = {"2024-09-01": 5, "2024-09-03": 7}
    assert series.dense_daily(pts, DAYS[:4]) == [5.0, 0.0, 7.0, 0.0]


def test_single_spike_detected_and_cleaned():
    values = _noisy(500)
    values[200] = 5000
    res = series.detect_spikes(values)
    assert res.is_spike[200]
    assert sum(res.is_spike) == 1
    assert 400 < res.clean[200] < 600


def test_no_false_positives_on_smooth_growth():
    for seed in range(5):
        values = _noisy(300, growth=0.8, seed=seed, noise=0.12)
        assert sum(series.detect_spikes(values).is_spike) == 0


def test_low_volume_noise_not_flagged():
    rng = random.Random(3)
    values = [float(_poisson(rng, 2.0)) for _ in DAYS]
    assert sum(series.detect_spikes(values).is_spike) == 0
    values[100] = 60  # a real burst on a tiny article is still caught
    assert series.detect_spikes(values).is_spike[100]


def test_spike_event_classification():
    main = _noisy(1000, seed=4)
    desktop = [v * 0.25 for v in main]
    total = list(main)
    for i, d_share in ((100, 0.97), (400, 0.25)):
        extra = 8000
        total[i] += extra
        main[i] += extra
        desktop[i] += extra * d_share
    res = series.detect_spikes(total)
    events = series.spike_events(DAYS, total, res, desktop, main)
    kinds = {e["peak_day"]: e["kind"] for e in events}
    assert kinds[DAYS[100].isoformat()] == "bot-like"
    assert kinds[DAYS[400].isoformat()] == "event-like"


def test_multi_day_spike_grouped():
    values = _noisy(800, seed=8)
    for i in (300, 301, 302):
        values[i] = 9000
    res = series.detect_spikes(values)
    events = series.spike_events(DAYS, values, res)
    assert len(events) == 1 and events[0]["days"] == 3 and events[0]["kind"] == "unknown"


def test_monthly_sums_and_days():
    months = ["2024-09", "2024-10"]
    vals = [1.0] * 61
    assert series.monthly_sums(DAYS[:61], vals, months) == [30.0, 31.0]
    assert series.days_per_month(DAYS[:61], months) == [30, 31]


def test_late_start_and_dropped():
    values = [0.0] * 200 + [50.0] * 530
    assert series.late_start(DAYS, values) == DAYS[200].isoformat()
    assert series.late_start(DAYS, [50.0] * 730) is None
    dying = [40.0] * 600 + [0.0] * 130
    assert series.dropped_to_zero(DAYS, dying) == DAYS[599].isoformat()
    assert series.dropped_to_zero(DAYS, [40.0] * 730) is None


def test_level_shift():
    months = [f"2024-{m:02d}" for m in range(1, 13)] + [f"2025-{m:02d}" for m in range(1, 13)]
    flat = [100.0] * 24
    assert series.level_shift(flat, months) is None
    jump = [100.0] * 12 + [400.0] * 12
    shift = series.level_shift(jump, months)
    assert shift["month"] == "2025-01" and shift["ratio"] == 4.0
    gradual = [100 * 1.06 ** i for i in range(24)]  # +100%/yr but smooth
    assert series.level_shift(gradual, months) is None
