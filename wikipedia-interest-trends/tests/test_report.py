from __future__ import annotations

from wikitrends import i18n
from wikitrends.report import _md_blocks, check_claims


def results_stub():
    return {
        "cells": [{
            "id": "t1:pl", "label": "pl", "lang": "pl", "error": None,
            "metrics": {
                "yoy": {"value": 0.352, "ci": [0.22, 0.491]},
                "yoy_raw": {"value": 0.36, "ci": [0.2, 0.5]},
                "yoy_normalized": {"value": 0.41, "ci": [0.3, 0.52]},
                "project_yoy": -0.061, "last3_yoy": 0.5, "cagr": None,
                "trend": {"sen_annual_growth": 0.33}, "spike_excess_share": 0.02,
                "platform": {"desktop_share_last12": 0.3, "desktop_yoy": 0.2, "mobile_yoy": 0.4},
                "total_views_raw": 1000,
            },
            "confidence": {"reasons": []},
            "spikes": {"events": []},
        }],
        "comparisons": [{"a_label": "pl", "b_label": "cs", "diff_pp": 27.1, "ci_pp": [11.0, 44.2]}],
    }


def test_claims_that_match_pass():
    text = "Interest in Poland grew 35% (90% CI 22–49%), 41% relative to the wiki; pl leads by 27 pp."
    assert check_claims(text, results_stub()) == []


def test_ci_level_mentions_are_not_claims():
    for text in ("довірчий інтервал 90% +22,0…+49,1%", "The 90% uncertainty interval is tight",
                 "90% CI 22-49%", "з 95-відсотковим… 95% довірчим інтервалом"):
        assert check_claims(text, results_stub()) == [], text
    assert [p["claim"] for p in check_claims("sales grew 90%", results_stub())] == ["90%"]


def test_fabricated_claims_are_flagged():
    problems = check_claims("Interest grew 80% and Czech by 19 pp.", results_stub())
    claims = {p["claim"] for p in problems}
    assert claims == {"80%", "19 pp"}


def test_ukrainian_number_formats():
    ok = "Інтерес зріс на +35,2% (90% ДІ +22,0…+49,1%), різниця 27,1 п.п."
    assert check_claims(ok, results_stub()) == []
    bad = "Інтерес зріс на 57,5%"
    assert [p["claim"] for p in check_claims(bad, results_stub())] == ["57,5%"]


def test_markdown_blocks():
    blocks = _md_blocks("# Title\nPara line one\nline two\n\n- a\n- b\n1. c")
    assert blocks == [("p", "Title Para line one line two"), ("li", "a"), ("li", "b"), ("li", "c")]


def test_number_formatting():
    assert i18n.fmt_pct(0.352) == "+35.2%"
    assert i18n.fmt_pct(-0.05, "uk") == "−5,0%"
    assert i18n.fmt_compact(42123) == "42k"
    assert i18n.fmt_compact(4123, "uk") == "4,1 тис."
    assert i18n.fmt_num(12340, "uk") == "12 340"
    assert i18n.fmt_month("2025-09", "uk") == "вер. 2025"


def test_every_reason_code_has_both_languages():
    assert set(i18n.REASONS["en"]) == set(i18n.REASONS["uk"])
    assert set(i18n.TEXT["en"]) == set(i18n.TEXT["uk"])
    assert set(i18n.LABELS["en"]) == set(i18n.LABELS["uk"])


def test_note_translation():
    en = ("no article titled 'foo' on en.wikipedia; picked top search result 'Foo bar' - check the alternatives")
    assert "обрано" in i18n.note(en, "uk")
    assert i18n.note(en, "en") == en
