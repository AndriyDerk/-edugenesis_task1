"""Daily series processing: densify, detect/clean spikes, aggregate by month,
and spot data artefacts (article created mid-window, sudden level shifts)."""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass
from collections.abc import Sequence

from .stats import median

SPIKE_WINDOW = 29  # days, centred rolling baseline
SPIKE_K = 6.0  # robust z threshold
SPIKE_MIN_RATIO = 2.0  # spike must at least double the baseline
SPIKE_MIN_EXCESS = 20.0  # and add at least this many views


def dense_daily(points: dict[str, int], days: Sequence[dt.date]) -> list[float]:
    """Pageviews API omits zero days; fill them in."""
    return [float(points.get(d.isoformat(), 0)) for d in days]


def add(*series: Sequence[float]) -> list[float]:
    if not series:
        return []
    return [sum(vals) for vals in zip(*series)]


def rolling_baseline(values: Sequence[float], window: int = SPIKE_WINDOW) -> tuple[list[float], list[float]]:
    """Centred rolling median and MAD (edges use a truncated window)."""
    n = len(values)
    h = window // 2
    meds: list[float] = []
    mads: list[float] = []
    for i in range(n):
        chunk = values[max(0, i - h): min(n, i + h + 1)]
        m = median(chunk)
        meds.append(m)
        mads.append(median([abs(v - m) for v in chunk]))
    return meds, mads


@dataclass
class SpikeResult:
    clean: list[float]
    baseline: list[float]
    is_spike: list[bool]


def detect_spikes(
    values: Sequence[float],
    window: int = SPIKE_WINDOW,
    k: float = SPIKE_K,
    min_ratio: float = SPIKE_MIN_RATIO,
    min_excess: float = SPIKE_MIN_EXCESS,
) -> SpikeResult:
    """Flag days far above a robust local baseline and replace them with it.

    A day is a spike when it exceeds median + k * scale, is at least
    ``min_ratio`` x the median and adds at least ``min_excess`` views. The
    scale has Poisson and relative floors so small or smooth series do not
    produce false alarms.
    """
    meds, mads = rolling_baseline(values, window)
    clean: list[float] = []
    flags: list[bool] = []
    for v, m, d in zip(values, meds, mads):
        scale = max(1.4826 * d, (max(m, 1.0)) ** 0.5, 0.05 * m)
        spike = v > m + k * scale and v >= min_ratio * max(m, 1.0) and (v - m) >= min_excess
        flags.append(spike)
        clean.append(m if spike else v)
    return SpikeResult(clean=clean, baseline=meds, is_spike=flags)


def spike_events(
    days: Sequence[dt.date],
    raw: Sequence[float],
    result: SpikeResult,
    desktop: Sequence[float] | None = None,
    main_all: Sequence[float] | None = None,
    max_gap: int = 2,
) -> list[dict]:
    """Group spike days into events and label them.

    ``bot-like``: the extra traffic is overwhelmingly desktop while the
    article's normal traffic is mostly mobile - typical of undetected crawlers.
    ``event-like``: platform mix unchanged - typically news or a viral moment.
    """
    idx = [i for i, f in enumerate(result.is_spike) if f]
    groups: list[list[int]] = []
    for i in idx:
        if groups and i - groups[-1][-1] <= max_gap + 1:
            groups[-1].append(i)
        else:
            groups.append([i])

    base_share = None
    if desktop is not None and main_all is not None:
        normal = [(d, a) for d, a, f in zip(desktop, main_all, result.is_spike) if not f and a > 0]
        if normal:
            tot_a = sum(a for _, a in normal)
            base_share = sum(d for d, _ in normal) / tot_a if tot_a else None

    events = []
    for g in groups:
        peak = max(g, key=lambda i: raw[i])
        excess = sum(raw[i] - result.baseline[i] for i in g)
        kind = "unknown"
        share = None
        if base_share is not None:
            d_sum = sum(desktop[i] for i in g)
            a_sum = sum(main_all[i] for i in g)
            if a_sum > 0:
                share = d_sum / a_sum
                kind = "bot-like" if (share >= 0.6 and share - base_share >= 0.25) else "event-like"
        events.append({
            "start": days[g[0]].isoformat(),
            "end": days[g[-1]].isoformat(),
            "days": len(g),
            "peak_day": days[peak].isoformat(),
            "peak_views": int(raw[peak]),
            "baseline": round(result.baseline[peak], 1),
            "ratio": round(raw[peak] / max(result.baseline[peak], 1.0), 1),
            "excess_views": int(round(excess)),
            "desktop_share": round(share, 2) if share is not None else None,
            "baseline_desktop_share": round(base_share, 2) if base_share is not None else None,
            "kind": kind,
        })
    events.sort(key=lambda e: -e["excess_views"])
    return events


def monthly_sums(days: Sequence[dt.date], values: Sequence[float], months: Sequence[str]) -> list[float]:
    acc = {m: 0.0 for m in months}
    for d, v in zip(days, values):
        key = f"{d:%Y-%m}"
        if key in acc:
            acc[key] += v
    return [acc[m] for m in months]


def days_per_month(days: Sequence[dt.date], months: Sequence[str]) -> list[int]:
    acc = {m: 0 for m in months}
    for d in days:
        key = f"{d:%Y-%m}"
        if key in acc:
            acc[key] += 1
    return [acc[m] for m in months]


def late_start(days: Sequence[dt.date], values: Sequence[float], min_level: float = 5.0) -> str | None:
    """First day with views if the series is empty for a long initial stretch
    but clearly alive later: the article (or basket item) appeared mid-window."""
    first = next((i for i, v in enumerate(values) if v > 0), None)
    if first is None or first < 30:
        return None
    tail = values[-90:]
    if sum(tail) / max(len(tail), 1) >= min_level:
        return days[first].isoformat()
    return None


def dropped_to_zero(days: Sequence[dt.date], values: Sequence[float], min_level: float = 5.0) -> str | None:
    """Last active day if the series dies for the final 30+ days (article
    deleted/renamed without redirect)."""
    last = next((i for i in range(len(values) - 1, -1, -1) if values[i] > 0), None)
    if last is None or len(values) - 1 - last < 30:
        return None
    head = values[: last + 1][-180:]
    if sum(head) / max(len(head), 1) >= min_level:
        return days[last].isoformat()
    return None


def level_shift(per_day: Sequence[float], months: Sequence[str], block: int = 3,
                up: float = 2.5, down: float = 0.4, min_level: float = 3.0) -> dict | None:
    """Largest abrupt jump between consecutive 3-month blocks (median based)."""
    best = None
    for i in range(block, len(per_day) - block + 1):
        before = median(per_day[i - block:i])
        after = median(per_day[i:i + block])
        if before < min_level and after < min_level:
            continue
        ratio = (after + 1e-9) / (before + 1e-9)
        if ratio >= up or ratio <= down:
            # tie-break equal block medians by the sharpest single-month step
            step = (per_day[i] + 1e-9) / (per_day[i - 1] + 1e-9)
            strength = abs(math.log(max(ratio, 1e-9))) + 1e-3 * abs(math.log(step))
            if best is None or strength > best["strength"]:
                best = {"month": months[i], "ratio": round(ratio, 2), "strength": strength,
                        "before_per_day": round(before, 1), "after_per_day": round(after, 1)}
    if best:
        best.pop("strength")
    return best
