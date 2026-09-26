"""Analysis pipeline: resolve -> fetch -> clean -> metrics -> confidence ->
comparisons -> ranking. Produces one JSON-serialisable ``results`` dict that
every other command (report, rank, charts) works from, so follow-up questions
never need to refetch data.
"""

from __future__ import annotations

import datetime as dt
import math
import zlib
from dataclasses import dataclass, field
from typing import Any

from . import __version__, i18n, langs, periods
from .net import NetError
from .periods import Window
from .resolve import TopicSpec, resolve_topics
from .series import (add, days_per_month, dense_daily, detect_spikes, dropped_to_zero, late_start,
                     level_shift, monthly_sums, spike_events)
from .stats import bootstrap_ci, seasonal_kendall, seasonal_sen_slope, sign_test_p
from .wiki import SeriesKey, Wiki

SCHEMA = "wikitrends/1"
CI_ALPHA = 0.10  # 90% intervals
BOOT_REPS = 4000

DEFAULT_WEIGHTS = {"reach": 0.30, "momentum": 0.35, "intensity": 0.20, "confidence": 0.15}
WEIGHT_PRESETS = {
    "balanced": DEFAULT_WEIGHTS,
    "growth-first": {"reach": 0.15, "momentum": 0.60, "intensity": 0.10, "confidence": 0.15},
    "size-first": {"reach": 0.60, "momentum": 0.15, "intensity": 0.10, "confidence": 0.15},
    "niche-first": {"reach": 0.15, "momentum": 0.25, "intensity": 0.45, "confidence": 0.15},
}


@dataclass
class Params:
    topics: list[TopicSpec]
    langs: list[str]
    window: Window
    search_lang: str = "en"
    agent: str = "user"
    include_redirects: bool = True
    max_redirects: int = 30
    platform_split: bool = True
    geo: bool = True
    weights: dict[str, float] | None = None
    ui_lang: str = "en"
    notes: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- helpers
def _seed(*parts: str) -> int:
    return zlib.crc32("|".join(parts).encode("utf-8"))


def _ratio(num: float, den: float) -> float | None:
    return num / den - 1.0 if den > 0 else None


def _sum_idx(values: list[float], idx: list[int]) -> float:
    return sum(values[i] for i in idx)


def _r(x: float | None, nd: int = 4) -> float | None:
    return None if x is None else round(x, nd)


def yoy_block(prev: list[float], last: list[float], seed: int) -> dict[str, Any]:
    """Year-over-year growth of the sum with a paired month bootstrap CI."""
    growth = _ratio(sum(last), sum(prev))
    up = sum(1 for a, b in zip(prev, last) if b > a)
    down = sum(1 for a, b in zip(prev, last) if b < a)
    lo = hi = None
    if growth is not None:
        lo, hi = bootstrap_ci(
            len(prev), lambda idx: _ratio(_sum_idx(last, idx), _sum_idx(prev, idx)),
            reps=BOOT_REPS, alpha=CI_ALPHA, seed=seed)
    return {"value": _r(growth), "ci": [_r(lo), _r(hi)], "months_up": up, "months_down": down,
            "months_compared": len(prev), "sign_p": _r(sign_test_p(up, up + down), 5)}


def share_yoy_block(prev: list[float], last: list[float], p_prev: list[float], p_last: list[float],
                    seed: int) -> dict[str, Any]:
    """YoY change of the topic's share of all views of the language edition."""
    def stat(idx: list[int]) -> float | None:
        a, b = _sum_idx(prev, idx), _sum_idx(last, idx)
        pa, pb = _sum_idx(p_prev, idx), _sum_idx(p_last, idx)
        if a <= 0 or pa <= 0 or pb <= 0:
            return None
        return (b / pb) / (a / pa) - 1.0

    full = list(range(len(prev)))
    value = stat(full)
    lo = hi = None
    if value is not None:
        lo, hi = bootstrap_ci(len(prev), stat, reps=BOOT_REPS, alpha=CI_ALPHA, seed=seed)
    return {"value": _r(value), "ci": [_r(lo), _r(hi)]}


def direction_of(yoy: dict[str, Any]) -> str:
    v = yoy.get("value")
    if v is None:
        return "no-baseline"
    lo, hi = yoy["ci"]
    p = yoy["sign_p"]
    if lo is not None and lo > 0 and p < 0.10:
        return "growing"
    if hi is not None and hi < 0 and p < 0.10:
        return "declining"
    if lo is not None and hi is not None and lo >= -0.10 and hi <= 0.10:
        return "stable"
    if v > 0 and ((lo is not None and lo > 0) or p < 0.10):
        return "likely growing"
    if v < 0 and ((hi is not None and hi < 0) or p < 0.10):
        return "likely declining"
    return "inconclusive"


# --------------------------------------------------------------------------- metrics
def compute_metrics(cell: dict[str, Any]) -> dict[str, Any]:
    """All numbers for one topic x language cell, from its monthly arrays."""
    m = cell["monthly"]
    months = m["months"]
    n = len(months)
    clean, raw, days = m["clean"], m["raw"], m["days"]
    proj = m.get("project") or [None] * n
    seed_base = cell["id"]
    last_i = list(range(n - 12, n))
    prev_i = list(range(n - 24, n - 12))
    pick = lambda arr, idx: [arr[i] for i in idx]  # noqa: E731

    yoy_clean = yoy_block(pick(clean, prev_i), pick(clean, last_i), _seed(seed_base, "clean"))
    yoy_raw = yoy_block(pick(raw, prev_i), pick(raw, last_i), _seed(seed_base, "raw"))
    proj_ok = all(p is not None and p > 0 for p in pick(proj, prev_i + last_i))
    yoy_norm = None
    project_yoy = None
    if proj_ok:
        yoy_norm = share_yoy_block(pick(clean, prev_i), pick(clean, last_i), pick(proj, prev_i),
                                   pick(proj, last_i), _seed(seed_base, "norm"))
        project_yoy = _ratio(sum(pick(proj, last_i)), sum(pick(proj, prev_i)))

    desk = m.get("desktop_main")
    main_all = m.get("main_all")
    platform = None
    if desk and main_all:
        mob = [a - d for a, d in zip(main_all, desk)]
        d_last, d_prev = sum(pick(desk, last_i)), sum(pick(desk, prev_i))
        m_last, m_prev = sum(pick(mob, last_i)), sum(pick(mob, prev_i))
        a_last = sum(pick(main_all, last_i))
        platform = {
            "desktop_share_last12": _r(d_last / a_last if a_last else None, 3),
            "desktop_yoy": _r(_ratio(d_last, d_prev)),
            "mobile_yoy": _r(_ratio(m_last, m_prev)),
        }

    last12 = sum(pick(clean, last_i))
    days_last = sum(pick(days, last_i))
    per_day = [c / d if d else 0.0 for c, d in zip(clean, days)]
    log_per_day = [math.log(v + 1.0) for v in per_day]
    sk = seasonal_kendall(per_day, 12)
    sen = seasonal_sen_slope(log_per_day, 12)
    trend = {
        "months": n,
        "seasonal_kendall_z": _r(sk["z"], 3),
        "seasonal_kendall_p": _r(sk["p"], 5),
        "sen_annual_growth": _r(math.exp(sen) - 1.0) if sen is not None else None,
    }
    cagr = None
    if n >= 36:
        first12 = sum(clean[:12])
        years = (n - 12) / 12.0
        if first12 > 0 and last12 > 0:
            cagr = (last12 / first12) ** (1.0 / years) - 1.0
    last3 = _ratio(sum(clean[n - 3:]), sum(clean[n - 15:n - 12]))

    per_million = None
    if proj_ok:
        per_million = last12 / sum(pick(proj, last_i)) * 1e6
    total_raw = sum(raw)
    total_clean = sum(clean)
    return {
        "avg_daily_last12": _r(last12 / days_last if days_last else 0.0, 2),
        "avg_monthly_last12": _r(last12 / 12.0, 1),
        "views_last12": int(round(last12)),
        "views_prev12": int(round(sum(pick(clean, prev_i)))),
        "total_views_raw": int(round(total_raw)),
        "per_million_last12": _r(per_million, 2),
        "yoy": yoy_clean,
        "yoy_raw": yoy_raw,
        "yoy_normalized": yoy_norm,
        "project_yoy": _r(project_yoy),
        "last3_yoy": _r(last3),
        "cagr": _r(cagr),
        "trend": trend,
        "platform": platform,
        "spike_excess_share": _r((total_raw - total_clean) / total_raw if total_raw else 0.0, 4),
        "direction": "new-article" if cell.get("new_article") else direction_of(yoy_clean),
    }


# --------------------------------------------------------------------------- confidence
# Codes that cap the score (49 = at most LOW, 74 = at most MEDIUM).
HARD_CAPS = {"very_low_volume": 49, "late_start": 49, "dropped_to_zero": 49, "no_baseline": 49,
             "low_volume": 74, "new_item": 74}

def assess_confidence(cell: dict[str, Any]) -> dict[str, Any]:
    """Rule-based, explainable reliability grade for the cell's trend claim.

    Starts at 100 and subtracts points for each problem found; every rule adds a
    reason (code + data) so the grade can be explained and localised."""
    mt = cell["metrics"]
    score = 100
    reasons: list[dict[str, Any]] = []

    def add(points: int, code: str, **data: Any) -> None:
        nonlocal score
        score -= points
        reasons.append({"effect": -points, "code": code, "data": data, "text": i18n.reason(code, data)})

    d = mt["avg_daily_last12"]
    if d < 10:
        add(40, "very_low_volume", per_day=d)
    elif d < 50:
        add(20, "low_volume", per_day=d)
    elif d < 200:
        add(8, "modest_volume", per_day=d)
    else:
        add(0, "volume", per_day=d)

    y = mt["yoy"]
    direction = mt["direction"]
    lo, hi = y["ci"]
    agree = y["months_up"] if (y["value"] or 0) >= 0 else y["months_down"]
    if direction in ("growing", "declining"):
        add(0, "consistent", agree=agree, lo=lo, hi=hi)
    elif direction == "stable":
        add(0, "stable", lo=lo, hi=hi)
    elif direction.startswith("likely"):
        add(12, "partial_support", agree=agree, lo=lo, hi=hi)
    elif direction == "no-baseline":
        add(40, "no_baseline")
    elif direction == "new-article":
        pass  # penalised through the late_start flag below
    else:
        add(25, "inconclusive", agree=agree, lo=lo, hi=hi)
    if lo is not None and hi is not None and hi - lo > 0.6 and direction != "new-article":
        add(10, "wide_ci", width=round((hi - lo) * 100))

    raw_v, clean_v = mt["yoy_raw"]["value"], y["value"]
    if raw_v is not None and clean_v is not None and abs(raw_v - clean_v) > 0.15:
        add(15, "spike_driven", raw=raw_v, clean=clean_v)
    if mt["spike_excess_share"] > 0.20:
        add(10, "spiky", share=mt["spike_excess_share"])
    bot_excess = sum(e["excess_views"] for e in cell["spikes"]["events"] if e["kind"] == "bot-like")
    if mt["total_views_raw"] and bot_excess / mt["total_views_raw"] > 0.03:
        add(10, "bot_traffic", share=bot_excess / mt["total_views_raw"])

    norm = mt.get("yoy_normalized")
    proj_yoy = mt.get("project_yoy")
    if norm is None:
        add(5, "no_wiki_baseline")
    elif clean_v is not None and norm["value"] is not None and proj_yoy is not None:
        nv = norm["value"]
        if (clean_v > 0.03 and nv < -0.03) or (clean_v < -0.03 and nv > 0.03):
            add(5, "baseline_divergence", wiki_lang=cell["lang"], project=proj_yoy, norm=nv)

    plat = mt.get("platform")
    if plat and plat["desktop_yoy"] is not None and plat["mobile_yoy"] is not None:
        dy, my = plat["desktop_yoy"], plat["mobile_yoy"]
        share = plat["desktop_share_last12"] or 0
        if 0.15 <= share <= 0.85 and ((dy > 0.10 and my < -0.10) or (dy < -0.10 and my > 0.10)):
            add(10, "platform_divergence", desktop=dy, mobile=my)
        elif (dy > 0) == (my > 0):
            add(0, "platforms_agree", desktop=dy, mobile=my)

    penalties = {"late_start": 35, "dropped_to_zero": 35, "level_shift": 10, "incomplete_basket": 10,
                 "redirects_truncated": 5, "fetch_errors": 15, "new_item": 20}
    for flag in cell["flags"]:
        if flag["code"] in penalties:
            add(penalties[flag["code"]], flag["code"], **flag.get("data", {}))

    score = max(0, min(100, score))
    # Hard caps: no amount of statistical consistency rescues these cases.
    capped_by = [r["code"] for r in reasons if r["code"] in HARD_CAPS]
    if capped_by:
        score = min(score, min(HARD_CAPS[c] for c in capped_by))
    grade = "HIGH" if score >= 75 else "MEDIUM" if score >= 50 else "LOW"
    return {"grade": grade, "score": score, "reasons": reasons, "capped_by": capped_by}


# --------------------------------------------------------------------------- comparisons
def _yoy_arrays(cell: dict[str, Any]) -> tuple[list[float], list[float]]:
    clean = cell["monthly"]["clean"]
    n = len(clean)
    return clean[n - 24:n - 12], clean[n - 12:]


def compare_pair(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    pa, la = _yoy_arrays(a)
    pb, lb = _yoy_arrays(b)

    def stat(idx: list[int]) -> float | None:
        ga = _ratio(_sum_idx(la, idx), _sum_idx(pa, idx))
        gb = _ratio(_sum_idx(lb, idx), _sum_idx(pb, idx))
        return None if ga is None or gb is None else ga - gb

    diff = stat(list(range(12)))
    lo = hi = None
    if diff is not None:
        lo, hi = bootstrap_ci(12, stat, reps=BOOT_REPS, alpha=CI_ALPHA, seed=_seed(a["id"], b["id"]))
    winner = None
    if diff is None:
        verdict = "not_comparable"
    elif lo is not None and lo > 0:
        verdict, winner = "faster", a["id"]
    elif hi is not None and hi < 0:
        verdict, winner = "faster", b["id"]
    else:
        verdict = "no_difference"
    return {"a": a["id"], "b": b["id"], "a_label": a["label"], "b_label": b["label"],
            "diff_pp": _r(diff * 100 if diff is not None else None, 2),
            "ci_pp": [_r(lo * 100 if lo is not None else None, 2), _r(hi * 100 if hi is not None else None, 2)],
            "verdict": verdict, "winner": winner}


def growth_valid(cell: dict[str, Any]) -> bool:
    """True when the cell's year-over-year growth is a meaningful number."""
    if cell.get("error"):
        return False
    mt = cell["metrics"]
    return mt["yoy"]["value"] is not None and mt["direction"] not in ("new-article", "no-baseline")


def comparison_groups(cells: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    ok = [c for c in cells if growth_valid(c)]
    topics = list(dict.fromkeys(c["topic_id"] for c in ok))
    langs_ = list(dict.fromkeys(c["lang"] for c in ok))
    groups = []
    if len(topics) == 1 or len(langs_) > 1:
        for t in topics:
            g = [c for c in ok if c["topic_id"] == t]
            if len(g) >= 2:
                groups.append(g)
    if len(langs_) == 1 or len(topics) > 1:
        for lang in langs_:
            g = [c for c in ok if c["lang"] == lang]
            if len(g) >= 2 and g not in groups:
                groups.append(g)
    return groups


def compare_cells(cells: list[dict[str, Any]], max_pairs: int = 10) -> list[dict[str, Any]]:
    out = []
    for group in comparison_groups(cells):
        ordered = sorted(group, key=lambda c: -(c["metrics"]["yoy"]["value"] or -9))
        leader = ordered[0]
        for other in ordered[1:]:
            out.append(compare_pair(leader, other))
            if len(out) >= max_pairs:
                return out
    return out


# --------------------------------------------------------------------------- ranking
# Fixed (absolute) scales, so a score means the same thing in every run and a
# two-option comparison does not collapse into 0 vs 100.
SCALES = {
    "reach": (2.0, 6.0),  # log10 avg monthly views: 100 .. 1M
    "momentum": (-0.30, 0.50),  # YoY growth vs whole wiki: -30% .. +50%
    "intensity": (0.0, 3.0),  # log10 views per million wiki views: 1 .. 1000
    "confidence": (0.0, 1.0),
}


def _components(cell: dict[str, Any]) -> dict[str, float | None]:
    mt = cell["metrics"]
    norm = mt.get("yoy_normalized") or {}
    momentum = norm.get("value") if norm.get("value") is not None else mt["yoy"]["value"]
    if not growth_valid(cell):
        momentum = None  # unknown growth scores as neutral, never as a win
    pm = mt.get("per_million_last12")
    return {
        "reach": math.log10(mt["avg_monthly_last12"] + 1.0),
        "momentum": momentum,
        "intensity": math.log10(pm) if pm and pm > 0 else None,
        "confidence": cell["confidence"]["score"] / 100.0,
    }


TIE_POINTS = 3.0  # score gaps below this are within the noise of the inputs


def _scaled(name: str, value: float | None) -> float:
    if value is None:
        return 0.5
    lo, hi = SCALES[name]
    return max(0.0, min(1.0, (value - lo) / (hi - lo)))


def parse_weights(text: str | None) -> dict[str, float] | None:
    if not text:
        return None
    if text in WEIGHT_PRESETS:
        return dict(WEIGHT_PRESETS[text])
    weights = dict.fromkeys(DEFAULT_WEIGHTS, 0.0)
    for part in text.split(","):
        if not part.strip():
            continue
        if "=" not in part:
            raise ValueError(f"bad weight '{part}': use reach=0.4,momentum=0.4,... or a preset "
                             f"({', '.join(WEIGHT_PRESETS)})")
        k, v = part.split("=", 1)
        k = k.strip().lower()
        if k not in weights:
            raise ValueError(f"unknown weight '{k}'; allowed: {', '.join(DEFAULT_WEIGHTS)}")
        weights[k] = float(v)
    if sum(weights.values()) <= 0:
        raise ValueError("weights must sum to a positive number")
    return weights


def _score(scaled: dict[str, list[float]], weights: dict[str, float], i: int) -> float:
    total = sum(weights.values())
    return 100.0 * sum(weights[k] * scaled[k][i] for k in weights) / total


def rank_cells(cells: list[dict[str, Any]], weights: dict[str, float] | None = None) -> dict[str, Any] | None:
    ok = [c for c in cells if not c.get("error") and c["metrics"]["avg_monthly_last12"] > 0]
    if len(ok) < 2:
        return None
    topics = {c["topic_id"] for c in ok}
    langs_ = {c["lang"] for c in ok}
    dimension = "language" if len(topics) == 1 else "topic" if len(langs_) == 1 else "topic x language"
    comps = [_components(c) for c in ok]
    scaled = {k: [_scaled(k, cp[k]) for cp in comps] for k in DEFAULT_WEIGHTS}
    primary = weights or DEFAULT_WEIGHTS
    scores = [_score(scaled, primary, i) for i in range(len(ok))]
    order = sorted(range(len(ok)), key=lambda i: -scores[i])

    sensitivity = {}
    for name, w in WEIGHT_PRESETS.items():
        s = [_score(scaled, w, i) for i in range(len(ok))]
        sensitivity[name] = ok[max(range(len(ok)), key=lambda i: s[i])]["id"]
    top_id = ok[order[0]]["id"]
    agree = sum(1 for v in sensitivity.values() if v == top_id)

    names = {"reach": "audience size", "momentum": "growth", "intensity": "topic salience in that wiki",
             "confidence": "data reliability"}
    # strengths/weaknesses are relative to the other options (what makes this one different)
    bounds = {}
    for k in DEFAULT_WEIGHTS:
        vals = [scaled[k][j] for j in range(len(ok)) if comps[j][k] is not None]
        if len(vals) >= 2 and max(vals) - min(vals) >= 0.15:
            spread = max(vals) - min(vals)
            bounds[k] = (min(vals) + 0.25 * spread, max(vals) - 0.25 * spread)
    rows = []
    for pos, i in enumerate(order, start=1):
        c = ok[i]
        strengths = [names[k] for k, (lo, hi) in bounds.items() if comps[i][k] is not None and scaled[k][i] >= hi]
        weaknesses = [names[k] for k, (lo, hi) in bounds.items() if comps[i][k] is not None and scaled[k][i] <= lo]
        rows.append({
            "rank": pos,
            "cell": c["id"],
            "label": c["label"],
            "score": round(scores[i], 1),
            "components": {k: round(scaled[k][i], 3) for k in DEFAULT_WEIGHTS},
            "inputs": {
                "avg_monthly_views": c["metrics"]["avg_monthly_last12"],
                "growth_vs_wiki": (c["metrics"].get("yoy_normalized") or {}).get("value"),
                "growth": c["metrics"]["yoy"]["value"],
                "per_million": c["metrics"].get("per_million_last12"),
                "confidence": c["confidence"]["grade"],
            },
            "strengths": strengths,
            "weaknesses": weaknesses,
        })
    for a, b in zip(rows, rows[1:]):
        a["gap_to_next"] = round(a["score"] - b["score"], 1)
    ties = []
    group: list[str] = []
    for row in rows[:6]:
        group.append(row["cell"])
        if row.get("gap_to_next") is None or row["gap_to_next"] >= TIE_POINTS:
            # only ties that matter for the decision: involving one of the top 3 places
            if len(group) > 1 and rows[[r["cell"] for r in rows].index(group[0])]["rank"] <= 3:
                ties.append(group)
            group = []
    return {
        "dimension": dimension,
        "weights": primary,
        "custom_weights": weights is not None,
        "rows": rows,
        "ties": ties,
        "sensitivity": sensitivity,
        "top_stable": agree == len(WEIGHT_PRESETS),
        "top_agreement": f"{agree}/{len(WEIGHT_PRESETS)}",
    }


# --------------------------------------------------------------------------- pipeline
def _cell_label(topic_label: str, lang: str, single_topic: bool, single_lang: bool) -> str:
    if single_topic:
        return lang
    if single_lang:
        return topic_label
    return f"{topic_label} [{lang}]"


def build_cell(topic: dict[str, Any], lang: str, data: dict[SeriesKey, dict[str, int]],
               errors: dict[SeriesKey, str], project_monthly: dict[str, int] | None,
               window: Window, agent: str, platform_split: bool, label: str) -> dict[str, Any]:
    project = langs.project(lang)
    days = periods.days(window.start, window.end)
    months = window.months
    res = topic["cells"][lang]
    cell: dict[str, Any] = {
        "id": f"{topic['id']}:{lang}",
        "topic_id": topic["id"],
        "topic": topic["label"],
        "lang": lang,
        "lang_name": langs.name(lang),
        "label": label,
        "articles": [],
        "missing_items": res["missing"],
        "flags": [],
        "error": None,
    }
    if not res["articles"]:
        cell["error"] = f"no {langs.name(lang)} article for this topic"
        return cell

    total_series: list[list[float]] = []
    main_series: list[list[float]] = []
    desk_series: list[list[float]] = []
    per_article: list[tuple[str, list[float]]] = []
    fetch_errors: list[str] = []
    main_failed = 0
    for art in res["articles"]:
        key = SeriesKey(project, art["title"], "all-access", agent)
        if key in errors:
            fetch_errors.append(f"{art['title']}: {errors[key]}")
            main_failed += 1
            continue
        main = dense_daily(data.get(key, {}), days)
        main_series.append(main)
        total_series.append(main)
        red_total = 0.0
        combined = list(main)
        for r in art["redirects"]:
            rkey = SeriesKey(project, r, "all-access", agent)
            if rkey in errors:
                fetch_errors.append(f"redirect {r}: {errors[rkey]}")
                continue
            rs = dense_daily(data.get(rkey, {}), days)
            red_total += sum(rs)
            total_series.append(rs)
            combined = add(combined, rs)
        per_article.append((art["title"], combined))
        if platform_split:
            dkey = SeriesKey(project, art["title"], "desktop", agent)
            if dkey in errors:
                fetch_errors.append(f"{art['title']} (desktop): {errors[dkey]}")
            desk_series.append(dense_daily(data.get(dkey, {}), days))
        cell["articles"].append({
            "title": art["title"], "qid": art["qid"], "item": art["item"],
            "redirects": len(art["redirects"]), "redirects_total": art["redirects_total"],
            "redirects_truncated": art["redirects_truncated"],
            "views_main": int(sum(main)), "views_redirects": int(red_total),
        })
    if main_failed == len(res["articles"]):
        cell["error"] = "download failed: " + "; ".join(fetch_errors[:2])
        return cell

    total = add(*total_series)
    if sum(total) == 0:
        cell["error"] = "no views recorded in the period"
        return cell
    main_all = add(*main_series)
    desktop = add(*desk_series) if platform_split and len(desk_series) == len(main_series) else None
    spikes = detect_spikes(total)
    events = spike_events(days, total, spikes, desktop, main_all)

    m_days = days_per_month(days, months)
    monthly = {
        "months": months,
        "days": m_days,
        "raw": [round(v) for v in monthly_sums(days, total, months)],
        "clean": [round(v, 1) for v in monthly_sums(days, spikes.clean, months)],
        "project": [project_monthly.get(f"{m}-01") for m in months] if project_monthly else None,
        "main_all": [round(v) for v in monthly_sums(days, main_all, months)],
        "desktop_main": [round(v) for v in monthly_sums(days, desktop, months)] if desktop else None,
    }
    cell["monthly"] = monthly
    cell["spikes"] = {"days": sum(spikes.is_spike), "events": events[:6], "events_total": len(events)}

    def flag(code: str, **data: Any) -> None:
        cell["flags"].append({"code": code, "data": data, "text": i18n.reason(code, data)})

    prev12_start = dt.date.fromisoformat(f"{months[-24]}-01") if len(months) >= 24 else window.start
    start_day = late_start(days, total)
    if start_day:
        flag("late_start", date=start_day)
        if dt.date.fromisoformat(start_day) > prev12_start + dt.timedelta(days=14):
            cell["new_article"] = start_day
    elif len(per_article) > 1:
        last_n = sum(days_per_month(days, months)[-12:])
        cell_last = sum(total[-last_n:]) or 1.0
        for title, series_ in per_article:
            item_start = late_start(days, series_, min_level=1.0)
            share = sum(series_[-last_n:]) / cell_last
            if item_start and share >= 0.10:
                flag("new_item", title=title, date=item_start, share=share)
    end_day = dropped_to_zero(days, total)
    if end_day:
        flag("dropped_to_zero", date=end_day)
    per_day = [c / d if d else 0.0 for c, d in zip(monthly["clean"], m_days)]
    shift = level_shift(per_day, months)
    if shift and not start_day and not end_day:
        flag("level_shift", month=shift["month"], ratio=shift["ratio"])
    if res["missing"]:
        flag("incomplete_basket", items=res["missing"])
    if any(a["redirects_truncated"] for a in res["articles"]):
        flag("redirects_truncated")
    if fetch_errors:
        flag("fetch_errors", n=len(fetch_errors))
        cell["fetch_errors"] = fetch_errors[:5]

    cell["metrics"] = compute_metrics(cell)
    cell["confidence"] = assess_confidence(cell)
    return cell


def run(wiki: Wiki, params: Params) -> dict[str, Any]:
    window = params.window
    wiki.progress(f"resolving {len(params.topics)} topic(s) in {len(params.langs)} language(s)")
    resolution = resolve_topics(wiki, params.topics, params.langs, search_lang=params.search_lang,
                                include_redirects=params.include_redirects,
                                max_redirects=params.max_redirects, ui_lang=params.ui_lang)
    before = dict(wiki.client.stats)

    keys: list[SeriesKey] = []
    for topic in resolution["topics"]:
        for lang in params.langs:
            project = langs.project(lang)
            for art in topic["cells"][lang]["articles"]:
                keys.append(SeriesKey(project, art["title"], "all-access", params.agent))
                if params.platform_split:
                    keys.append(SeriesKey(project, art["title"], "desktop", params.agent))
                keys.extend(SeriesKey(project, r, "all-access", params.agent) for r in art["redirects"])
    project_keys = [SeriesKey(langs.project(lang), None, "all-access", params.agent, "monthly")
                    for lang in params.langs]

    data, errors = wiki.fetch_series(keys, window.start, window.end)
    pdata, perrors = wiki.fetch_series(project_keys, window.start, window.end)
    warnings = list(resolution["warnings"])
    for key, err in perrors.items():
        warnings.append(f"wiki-wide traffic for {key.project} unavailable ({err}); normalised metrics skipped")

    single_topic = len(resolution["topics"]) == 1
    single_lang = len(params.langs) == 1
    cells = []
    for topic in resolution["topics"]:
        for lang in params.langs:
            pkey = SeriesKey(langs.project(lang), None, "all-access", params.agent, "monthly")
            pm = pdata.get(pkey) if pkey not in perrors else None
            label = _cell_label(topic["label"], lang, single_topic, single_lang)
            cells.append(build_cell(topic, lang, data, errors, pm or None, window, params.agent,
                                    params.platform_split, label))

    geo = {}
    if params.geo:
        for lang in params.langs:
            try:
                rows = wiki.top_countries(lang, window.end.year, window.end.month)
                geo[lang] = {"month": f"{window.end:%Y-%m}", "top": rows[:5]}
            except NetError as exc:
                warnings.append(f"reader-country data for {lang} unavailable: {exc}")

    after = wiki.client.stats
    results = {
        "schema": SCHEMA,
        "tool_version": __version__,
        "generated_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "params": {
            "langs": params.langs,
            "search_lang": params.search_lang,
            "agent": params.agent,
            "include_redirects": params.include_redirects,
            "max_redirects": params.max_redirects,
            "platform_split": params.platform_split,
            "weights": params.weights,
            "ui_lang": params.ui_lang,
        },
        "window": {"start": window.start.isoformat(), "end": window.end.isoformat(),
                   "months": window.n_months, "label": window.label(),
                   "last12": f"{window.months[-12]}..{window.months[-1]}",
                   "prev12": f"{window.months[-24]}..{window.months[-13]}",
                   "notes": list(window.notes) + params.notes},
        "resolution": resolution,
        "cells": cells,
        "comparisons": compare_cells(cells),
        "ranking": rank_cells(cells, params.weights),
        "geo": geo,
        "warnings": warnings,
        "fetch": {"requests": after["requests"] - before.get("requests", 0),
                  "retries": after["retries"] - before.get("retries", 0),
                  "failed_series": len(errors) + len(perrors)},
    }
    return results


def rerank(results: dict[str, Any], weights: dict[str, float] | None) -> dict[str, Any]:
    results["ranking"] = rank_cells(results["cells"], weights)
    results["params"]["weights"] = weights
    return results
