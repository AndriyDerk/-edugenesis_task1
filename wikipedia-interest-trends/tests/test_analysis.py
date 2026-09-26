"""Metrics, confidence, comparisons and ranking on synthetic monthly data with
known answers."""

from __future__ import annotations

import pytest

from wikitrends import analysis

MONTHS = [f"{2024 + (i + 8) // 12}-{(i + 8) % 12 + 1:02d}" for i in range(24)]
DAYS = [30] * 24


def make_cell(clean, raw=None, project=None, desktop=None, main_all=None, cid="t1:pl", flags=None,
              events=None, **extra):
    cell = {
        "id": cid, "topic_id": cid.split(":")[0], "topic": "T", "lang": cid.split(":")[1], "label": cid.split(":")[1],
        "flags": flags or [], "error": None,
        "monthly": {"months": MONTHS[-len(clean):], "days": DAYS[-len(clean):], "clean": clean, "raw": raw or clean,
                    "project": project, "desktop_main": desktop, "main_all": main_all},
        "spikes": {"days": 0, "events": events or [], "events_total": 0},
    }
    cell.update(extra)
    cell["metrics"] = analysis.compute_metrics(cell)
    cell["confidence"] = analysis.assess_confidence(cell)
    return cell


def seasonal(level, growth):
    return [level * (1 + growth) ** (i / 12) * (1.2 if i % 12 in (0, 1) else 1.0) for i in range(24)]


def test_yoy_exact_value_and_counts():
    prev = [100.0] * 12
    last = [150.0] * 12
    y = analysis.yoy_block(prev, last, seed=1)
    assert y["value"] == pytest.approx(0.5)
    assert y["ci"] == [pytest.approx(0.5), pytest.approx(0.5)]
    assert (y["months_up"], y["months_down"]) == (12, 0)


def test_growth_and_normalised_growth():
    clean = seasonal(3000, 0.30)
    project = [1e8 * (1 - 0.10) ** (i / 12) for i in range(24)]
    cell = make_cell(clean, project=project)
    mt = cell["metrics"]
    # sum-ratio of a continuous 30%/yr series equals exactly 30%
    assert mt["yoy"]["value"] == pytest.approx(0.30, abs=1e-3)
    assert mt["project_yoy"] == pytest.approx(-0.10, abs=1e-3)
    assert mt["yoy_normalized"]["value"] == pytest.approx(1.30 / 0.90 - 1, abs=1e-3)
    assert mt["direction"] == "growing"
    assert mt["trend"]["sen_annual_growth"] == pytest.approx(0.30, abs=0.01)
    assert cell["confidence"]["grade"] == "HIGH"


def test_flat_series_is_stable_not_growing():
    clean = [1000.0 + (7 if i % 2 else -7) for i in range(24)]
    cell = make_cell(clean, project=[1e7] * 24)
    assert cell["metrics"]["direction"] == "stable"


def test_noisy_small_series_is_low_confidence():
    import random
    rng = random.Random(3)
    clean = [max(0.0, 150 + rng.gauss(0, 60)) for _ in range(24)]
    cell = make_cell(clean, project=[1e7] * 24)
    assert cell["metrics"]["avg_daily_last12"] < 10
    assert cell["confidence"]["grade"] == "LOW"
    codes = {r["code"] for r in cell["confidence"]["reasons"]}
    assert "very_low_volume" in codes


def test_spike_driven_growth_penalised():
    clean = [1000.0] * 24
    raw = [1000.0] * 23 + [9000.0]
    cell = make_cell(clean, raw=raw, project=[1e7] * 24)
    codes = {r["code"] for r in cell["confidence"]["reasons"]}
    assert "spike_driven" in codes


def test_baseline_divergence_and_platform_split():
    clean = seasonal(5000, 0.05)
    project = [1e8 * 1.25 ** (i / 12) for i in range(24)]
    main_all = clean
    desktop = [v * 0.4 * (1.5 ** (i / 12)) for i, v in enumerate(clean)]
    cell = make_cell(clean, project=project, desktop=desktop, main_all=main_all)
    codes = {r["code"] for r in cell["confidence"]["reasons"]}
    assert "baseline_divergence" in codes
    assert cell["metrics"]["yoy_normalized"]["value"] < 0 < cell["metrics"]["yoy"]["value"]
    assert "platform_divergence" in codes


def test_new_article_direction():
    clean = [0.0] * 10 + [3000.0] * 14
    cell = make_cell(clean, project=[1e7] * 24, new_article="2025-07-01",
                     flags=[{"code": "late_start", "data": {"date": "2025-07-01"}}])
    assert cell["metrics"]["direction"] == "new-article"
    assert not analysis.growth_valid(cell)
    assert cell["confidence"]["grade"] != "HIGH"


def test_cagr_for_long_windows():
    clean = [1000 * 1.2 ** (i / 12) for i in range(48)]
    cell = {"id": "t1:pl", "lang": "pl", "monthly": {"months": [f"m{i}" for i in range(48)], "days": [30] * 48,
                                                     "clean": clean, "raw": clean, "project": None}}
    mt = analysis.compute_metrics(cell)
    assert mt["cagr"] == pytest.approx(0.2, abs=1e-3)
    assert mt["trend"]["months"] == 48


def test_compare_pair_verdicts():
    a = make_cell(seasonal(2000, 0.40), project=[1e8] * 24, cid="t1:pl")
    b = make_cell(seasonal(2000, 0.02), project=[1e8] * 24, cid="t1:cs")
    c = make_cell(seasonal(2000, 0.03), project=[1e8] * 24, cid="t1:sk")
    ab = analysis.compare_pair(a, b)
    assert ab["verdict"] == "faster" and ab["winner"] == "t1:pl"
    assert ab["diff_pp"] == pytest.approx(38, abs=0.5)
    assert ab["ci_pp"][0] > 0
    bc = analysis.compare_pair(b, c)
    assert bc["verdict"] in ("no_difference", "faster")


def test_ranking_scores_sensitivity_and_weights():
    big_slow = make_cell(seasonal(200000, 0.0), project=[3e9] * 24, cid="t1:de")
    small_fast = make_cell(seasonal(3000, 0.6), project=[1e8] * 24, cid="t1:uk")
    mid = make_cell(seasonal(20000, 0.1), project=[5e8] * 24, cid="t1:pl")
    ranking = analysis.rank_cells([big_slow, small_fast, mid])
    assert ranking["dimension"] == "language"
    assert {r["cell"] for r in ranking["rows"]} == {"t1:de", "t1:uk", "t1:pl"}
    assert all(0 <= r["score"] <= 100 for r in ranking["rows"])
    growth = analysis.rank_cells([big_slow, small_fast, mid], analysis.parse_weights("growth-first"))
    size = analysis.rank_cells([big_slow, small_fast, mid], analysis.parse_weights("size-first"))
    assert growth["rows"][0]["cell"] == "t1:uk"
    assert size["rows"][0]["cell"] == "t1:de"
    assert growth["top_stable"] is False


def test_parse_weights():
    assert analysis.parse_weights(None) is None
    w = analysis.parse_weights("reach=1,momentum=3")
    assert w["momentum"] == 3 and w["intensity"] == 0
    with pytest.raises(ValueError):
        analysis.parse_weights("speed=1")
    with pytest.raises(ValueError):
        analysis.parse_weights("reach=0")
