"""Smoke tests against the REAL Wikimedia APIs (skipped by default).

    WIKITRENDS_LIVE=1 python -m pytest tests/test_live.py -v

They pin down the response shapes the fake server imitates, so a change in the
production APIs shows up here first.
"""

from __future__ import annotations

import datetime as dt
import os

import pytest

pytestmark = pytest.mark.skipif(not os.environ.get("WIKITRENDS_LIVE"), reason="set WIKITRENDS_LIVE=1 to hit real APIs")


@pytest.fixture
def wiki(tmp_path, monkeypatch):
    for k in ("WIKITRENDS_REST_BASE", "WIKITRENDS_WIKI_API", "WIKITRENDS_WIKIDATA_API", "WIKITRENDS_TODAY",
              "WIKITRENDS_OFFLINE"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("WIKITRENDS_HOME", str(tmp_path))
    from wikitrends import config
    from wikitrends.cache import Cache
    from wikitrends.net import Client
    from wikitrends.wiki import Wiki
    return Wiki(Client(config.user_agent(), rps=2), Cache(None), workers=2)


def test_per_article_and_aggregate_shapes(wiki):
    from wikitrends.wiki import SeriesKey
    start, end = dt.date(2024, 1, 1), dt.date(2024, 3, 31)
    key = SeriesKey("uk.wikipedia", "Астрономія", "all-access", "user")
    agg = SeriesKey("uk.wikipedia", None, "all-access", "user", "monthly")
    data, errors = wiki.fetch_series([key, agg], start, end)
    assert not errors
    assert len(data[key]) >= 80 and all(v >= 0 for v in data[key].values())
    assert sorted(data[agg]) == ["2024-01-01", "2024-02-01", "2024-03-01"]
    assert min(data[agg].values()) > 1_000_000


def test_missing_article_is_empty_not_error(wiki):
    from wikitrends.wiki import SeriesKey
    key = SeriesKey("en.wikipedia", "Zzqx nonexistent article 123", "all-access", "user")
    data, errors = wiki.fetch_series([key], dt.date(2024, 1, 1), dt.date(2024, 1, 31))
    assert not errors and data[key] == {}


def test_resolution_via_search_and_wikidata(wiki):
    from wikitrends.resolve import TopicSpec, resolve_topics
    res = resolve_topics(wiki, [TopicSpec(None, ["Intermittent fasting"])], ["pl", "cs", "uk"])
    item = res["topics"][0]["items"][0]
    assert item["qid"] and item["qid"].startswith("Q")
    assert res["topics"][0]["cells"]["pl"]["articles"], "Polish article expected"
    info = wiki.page_info("en", ["Astronomy"])["Astronomy"]
    assert info["exists"] and info["qid"] == "Q333" and info["redirects"]


def test_top_by_country_shape(wiki):
    rows = wiki.top_countries("pl", 2024, 1)
    assert rows and rows[0]["country"] == "PL" and rows[0]["rank"] == 1


def test_cli_end_to_end(tmp_path, monkeypatch, capsys):
    for k in ("WIKITRENDS_REST_BASE", "WIKITRENDS_WIKI_API", "WIKITRENDS_WIKIDATA_API", "WIKITRENDS_TODAY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("WIKITRENDS_HOME", str(tmp_path / "home"))
    monkeypatch.chdir(tmp_path)
    from wikitrends.cli import main
    assert main(["analyze", "--topic", "Astronomy", "--langs", "uk,pl", "--pdf", "--quiet"]) == 0
    out = capsys.readouterr().out
    assert "Findings" in out and "report.pdf" in out
