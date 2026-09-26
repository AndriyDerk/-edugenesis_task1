"""Cache, periods, language codes and the HTTP client."""

from __future__ import annotations

import datetime as dt
import gzip
import io
import json
import urllib.error

import pytest

from wikitrends import cache as cache_mod
from wikitrends import langs, periods
from wikitrends.net import Client, NetError, NotFound, OfflineError

D = dt.date


# ------------------------------------------------------------------ cache
def test_subtract_ranges():
    step = cache_mod.next_day
    assert cache_mod.subtract_ranges(D(2024, 1, 1), D(2024, 1, 10), [], step) == [(D(2024, 1, 1), D(2024, 1, 10))]
    covered = [(D(2024, 1, 3), D(2024, 1, 5)), (D(2024, 1, 8), D(2024, 1, 20))]
    assert cache_mod.subtract_ranges(D(2024, 1, 1), D(2024, 1, 10), covered, step) == [
        (D(2024, 1, 1), D(2024, 1, 2)), (D(2024, 1, 6), D(2024, 1, 7))]
    assert cache_mod.subtract_ranges(D(2024, 1, 4), D(2024, 1, 5), covered, step) == []


def test_subtract_ranges_monthly():
    step = cache_mod.next_month
    covered = [(D(2024, 3, 1), D(2024, 6, 1))]
    assert cache_mod.subtract_ranges(D(2024, 1, 1), D(2024, 8, 1), covered, step) == [
        (D(2024, 1, 1), D(2024, 2, 1)), (D(2024, 7, 1), D(2024, 8, 1))]


def test_put_series_respects_stable_until(tmp_path):
    c = cache_mod.Cache(tmp_path / "c.sqlite")
    pts = {"2024-01-01": 5, "2024-01-09": 7}
    c.put_series("k", pts, D(2024, 1, 1), D(2024, 1, 10), stable_until=D(2024, 1, 7))
    assert c.missing("k", D(2024, 1, 1), D(2024, 1, 10)) == [(D(2024, 1, 8), D(2024, 1, 10))]
    assert c.get_series("k", D(2024, 1, 1), D(2024, 1, 10)) == pts
    c.put_series("k", {"2024-01-10": 3}, D(2024, 1, 8), D(2024, 1, 10), stable_until=D(2024, 2, 1))
    assert c.missing("k", D(2024, 1, 1), D(2024, 1, 10)) == []
    assert c.coverage("k") == [(D(2024, 1, 1), D(2024, 1, 10))]


def test_monthly_coverage_only_complete_months(tmp_path):
    c = cache_mod.Cache(tmp_path / "c.sqlite")
    c.put_series("m", {"2024-08-01": 1, "2024-09-01": 2}, D(2024, 8, 1), D(2024, 9, 1),
                 stable_until=D(2024, 9, 20), monthly=True)
    assert c.missing("m", D(2024, 8, 1), D(2024, 9, 1), monthly=True) == [(D(2024, 9, 1), D(2024, 9, 1))]


def test_kv_ttl(tmp_path):
    c = cache_mod.Cache(tmp_path / "c.sqlite")
    c.set("a", {"x": 1}, ttl_days=1)
    c.set("b", [1], ttl_days=-1)
    assert c.get("a") == {"x": 1}
    assert c.get("b") is None
    assert c.info()["metadata_entries"] == 2
    c.clear()
    assert c.get("a") is None


# ------------------------------------------------------------------ periods
def test_default_window_is_24_complete_months():
    w = periods.make_window(today=D(2026, 9, 26))
    assert (w.start, w.end, w.n_months) == (D(2024, 9, 1), D(2026, 8, 31), 24)


def test_window_respects_publication_lag():
    assert periods.last_complete_month_end(D(2026, 9, 2)) == D(2026, 7, 31)
    assert periods.last_complete_month_end(D(2026, 9, 4)) == D(2026, 8, 31)


def test_short_window_extended_with_note():
    w = periods.make_window(months=12, today=D(2026, 9, 26))
    assert w.n_months == 24 and w.notes and "extended" in w.notes[0]


def test_explicit_window_and_clipping():
    w = periods.make_window(start="2021-01", end="2030-12", today=D(2026, 9, 26))
    assert w.start == D(2021, 1, 1) and w.end == D(2026, 8, 31)
    w = periods.make_window(start="2010-01", end="2018-12", today=D(2026, 9, 26))
    assert w.start == D(2015, 7, 1)
    with pytest.raises(periods.PeriodError):
        periods.make_window(start="2025-05", end="2024-01", today=D(2026, 9, 26))
    with pytest.raises(periods.PeriodError):
        periods.parse_month("May 2024")


# ------------------------------------------------------------------ langs
def test_language_aliases_and_validation():
    assert langs.normalize("ua")[0] == "uk"
    assert langs.normalize("CZ")[0] == "cs"
    assert langs.normalize("pl.wikipedia.org") == ("pl", None)
    assert langs.normalize("plwiki") == ("pl", None)
    code, note = langs.normalize("ast")
    assert code == "ast" and "built-in" in note
    with pytest.raises(langs.LangError):
        langs.normalize("Polish language")
    codes, notes = langs.parse_list("pl, cs;ua uk")
    assert codes == ["pl", "cs", "uk"] and notes


def test_site_mapping():
    assert langs.site("pl") == "plwiki"
    assert langs.site("zh-yue") == "zh_yuewiki"
    assert langs.code_from_site("zh_yuewiki") == "zh-yue"
    assert langs.code_from_site("be_x_oldwiki") == "be-tarask"
    assert langs.code_from_site("commonswiki") is None
    assert langs.project("uk") == "uk.wikipedia"
    assert langs.label("uk", "uk") == "українська (uk)"


# ------------------------------------------------------------------ net
class FakeResp:
    def __init__(self, body: bytes, headers=None):
        self._body = body
        self.headers = headers or {}

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _http_error(code, headers=None, body=b"{}"):
    return urllib.error.HTTPError("http://x", code, "err", headers or {}, io.BytesIO(body))


def test_client_retries_429_with_retry_after():
    calls, sleeps = [], []

    def opener(req, timeout):
        calls.append(req)
        if len(calls) < 3:
            raise _http_error(429, {"Retry-After": "2"})
        return FakeResp(json.dumps({"ok": 1}).encode())

    c = Client("ua-test", rps=1000, opener=opener, sleep=sleeps.append)
    assert c.get_json("http://x/a", {"q": "ü"}) == {"ok": 1}
    assert sleeps == [2.0, 2.0]
    assert calls[0].get_header("User-agent") == "ua-test"
    assert "q=%C3%BC" in calls[0].full_url
    assert c.stats == {"requests": 3, "retries": 2}


def test_client_404_and_gzip_and_offline():
    c = Client("ua", rps=1000, opener=lambda r, timeout: (_ for _ in ()).throw(_http_error(404)), sleep=lambda s: None)
    with pytest.raises(NotFound):
        c.get_json("http://x")
    body = gzip.compress(b'{"a": 2}')
    c = Client("ua", rps=1000, opener=lambda r, timeout: FakeResp(body, {"Content-Encoding": "gzip"}))
    assert c.get_json("http://x") == {"a": 2}
    with pytest.raises(OfflineError):
        Client("ua", offline=True).get_json("http://x")


def test_client_gives_up_and_explains_proxy_block():
    def blocked(req, timeout):
        raise urllib.error.URLError(OSError("Tunnel connection failed: 403 Forbidden"))

    c = Client("ua", rps=1000, opener=blocked, sleep=lambda s: None)
    with pytest.raises(NetError) as exc:
        c.get_json("https://wikimedia.org/api/x")
    assert "wikimedia.org" in str(exc.value) and "blocked" in str(exc.value)

    def always_500(req, timeout):
        raise _http_error(500)

    c = Client("ua", rps=1000, retries=2, opener=always_500, sleep=lambda s: None)
    with pytest.raises(NetError) as exc:
        c.get_json("http://x")
    assert exc.value.status == 500 and c.stats["requests"] == 3


def test_client_does_not_retry_unknown_hosts():
    import socket
    calls = []

    def dns_fail(req, timeout):
        calls.append(1)
        raise urllib.error.URLError(socket.gaierror(-2, "Name or service not known"))

    c = Client("ua", rps=1000, opener=dns_fail, sleep=lambda s: None)
    with pytest.raises(NetError) as exc:
        c.get_json("https://xx.wikipedia.org/w/api.php")
    assert "unknown host xx.wikipedia.org" in str(exc.value) and len(calls) == 1
