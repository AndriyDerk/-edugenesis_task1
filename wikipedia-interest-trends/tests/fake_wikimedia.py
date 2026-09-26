"""A small, deterministic stand-in for the Wikimedia APIs used by the skill.

It implements just enough of

* Analytics API: per-article, aggregate and top-by-country pageviews,
* MediaWiki Action API: titles/redirects/pageprops/description + search,
* Wikidata: wbgetentities (labels, descriptions, sitelinks),

with the same JSON shapes as production, over a synthetic "world" whose true
trends are known. Used by the test-suite and by offline agent evals:

    python tests/fake_wikimedia.py --port 8765   # prints the env vars to export
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import random
import threading
import urllib.parse
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

D = dt.date


@dataclass
class Series:
    base: float  # human views/day at 2023-01-01
    growth: float  # annual growth rate
    season: float = 0.10  # yearly seasonal amplitude
    peak_month: int = 1
    desktop: float = 0.30  # desktop share of normal traffic
    created: D | None = None
    spikes: list[tuple[D, float, float]] = field(default_factory=list)  # (day, multiplier, desktop share)
    noise: float = 0.08


@dataclass
class Page:
    title: str
    qid: str | None
    series: Series | None = None
    redirects: dict[str, Series] = field(default_factory=dict)
    description: str = ""
    disambiguation: bool = False


EPOCH = D(2023, 1, 1)


def _rng(*parts: object) -> random.Random:
    return random.Random("|".join(map(str, parts)))


def daily_views(s: Series, key: str, day: D) -> tuple[int, int]:
    """(all_access, desktop) human views for one day - deterministic."""
    if s.created and day < s.created:
        return 0, 0
    t = (day - EPOCH).days / 365.25
    level = s.base * (1 + s.growth) ** t
    level *= 1 + s.season * math.cos(2 * math.pi * ((day.month - s.peak_month) / 12.0))
    level *= 1.0 - 0.06 * (day.weekday() >= 5)
    level *= math.exp(_rng(key, day.isoformat()).gauss(0, s.noise))
    desktop = level * s.desktop
    for sd, mult, dshare in s.spikes:
        if sd == day:
            extra = level * (mult - 1)
            level += extra
            desktop += extra * dshare
    return int(round(level)), int(round(desktop))


def project_views(lang: str, day: D) -> int:
    base, growth = PROJECTS[lang]
    t = (day - EPOCH).days / 365.25
    return int(base * (1 + growth) ** t * (1 + 0.05 * math.cos(2 * math.pi * (day.month - 1) / 12)))


# ----------------------------------------------------------------------- world
PROJECTS = {  # views/day, annual growth
    "en": (240_000_000, -0.08), "pl": (3_000_000, -0.06), "cs": (1_100_000, -0.04), "uk": (1_500_000, 0.02),
    "de": (25_000_000, -0.05), "es": (30_000_000, -0.07), "tr": (4_000_000, -0.03), "fr": (22_000_000, -0.05),
}

WORLD: dict[str, dict[str, Page]] = {lang: {} for lang in PROJECTS}
ENTITIES: dict[str, dict] = {}


def _add(lang: str, page: Page) -> None:
    WORLD[lang][page.title] = page


def _entity(qid: str, labels: dict[str, str], descriptions: dict[str, str]) -> None:
    ENTITIES[qid] = {"labels": labels, "descriptions": descriptions}


# Intermittent fasting: strong growth in pl (with a bot burst), weak in cs, new article in uk.
_entity("Q900001", {"en": "intermittent fasting", "uk": "інтервальне голодування", "pl": "post przerywany"},
        {"en": "eating pattern that cycles between fasting and eating"})
_add("en", Page("Intermittent fasting", "Q900001", Series(9000, 0.10, desktop=0.35),
                {"Intermittent Fasting": Series(300, 0.1), "Time-restricted eating": Series(200, 0.2)},
                "Eating pattern"))
_add("pl", Page("Post przerywany", "Q900001",
                Series(420, 0.45, season=0.15, peak_month=1, desktop=0.25,
                       spikes=[(D(2025, 3, 14), 9.0, 0.97), (D(2025, 3, 15), 6.0, 0.97)]),
                {"Głodówka przerywana": Series(15, 0.3)}, "Wzorzec żywieniowy"))
_add("cs", Page("Přerušovaný půst", "Q900001",
                Series(95, 0.03, season=0.15, desktop=0.3, noise=0.25,
                       spikes=[(D(2026, 1, 5), 7.0, 0.3)]),
                {}, "Způsob stravování"))
_add("uk", Page("Інтервальне голодування", "Q900001", Series(60, 0.3, desktop=0.2, created=D(2025, 6, 1))))

# Astronomy: seasonal (school year), moderate growth in uk, event spike.
_entity("Q333", {"en": "astronomy", "uk": "астрономія"}, {"en": "natural science that studies celestial objects"})
_add("en", Page("Astronomy", "Q333", Series(8000, -0.05, season=0.2, peak_month=3), {"Astronomer (field)": Series(5, 0)}))
_add("uk", Page("Астрономія", "Q333",
                Series(650, 0.12, season=0.30, peak_month=11, desktop=0.35,
                       spikes=[(D(2026, 8, 12), 4.0, 0.3)]),
                {"Зоряна наука": Series(4, 0.0)}, "природнича наука"))
_add("pl", Page("Astronomia", "Q333", Series(900, -0.02, season=0.25, peak_month=11)))

# Learning English basket: English language + ESL article, several languages.
_entity("Q1860", {"en": "English", "uk": "англійська мова"}, {"en": "West Germanic language"})
_entity("Q900002", {"en": "English as a second or foreign language", "uk": "англійська як іноземна"},
        {"en": "use of English by speakers with different native languages"})
for lang, title, base, growth in [("en", "English language", 25000, -0.06), ("de", "Englische Sprache", 2500, -0.04),
                                  ("pl", "Język angielski", 1400, 0.02), ("uk", "Англійська мова", 1300, 0.18),
                                  ("es", "Idioma inglés", 3000, 0.01), ("tr", "İngilizce", 900, 0.12),
                                  ("fr", "Anglais", 2600, -0.03)]:
    _add(lang, Page(title, "Q1860", Series(base, growth, season=0.12, peak_month=9)))
for lang, title, base, growth in [("en", "English as a second or foreign language", 1500, -0.02),
                                  ("de", "Englisch als Fremdsprache", 80, 0.0),
                                  ("pl", "Angielski jako język obcy", 40, 0.05),
                                  ("uk", "Англійська як іноземна", 30, 0.25),
                                  ("es", "Inglés como lengua extranjera", 150, 0.03)]:
    _add(lang, Page(title, "Q900002", Series(base, growth, season=0.12, peak_month=9)))

# Ambiguous term.
_add("en", Page("Mercury", None, None, disambiguation=True, description="Topics referred to by the same term"))
_entity("Q308", {"en": "Mercury"}, {"en": "first planet from the Sun"})
_entity("Q925", {"en": "mercury"}, {"en": "chemical element with symbol Hg"})
_add("en", Page("Mercury (planet)", "Q308", Series(12000, 0.0), description="Smallest planet in the Solar System"))
_add("en", Page("Mercury (element)", "Q925", Series(6000, 0.0), description="Chemical element with atomic number 80"))
_add("uk", Page("Меркурій", "Q308", Series(900, 0.05)))

GEO = {
    "pl": ["PL", "DE", "GB", "US", "IE"], "cs": ["CZ", "SK", "DE", "GB", "US"], "uk": ["UA", "PL", "DE", "CZ", "US"],
    "en": ["US", "GB", "IN", "CA", "AU"], "de": ["DE", "AT", "CH", "US", "GB"], "es": ["MX", "ES", "AR", "CO", "US"],
    "tr": ["TR", "DE", "AZ", "NL", "US"], "fr": ["FR", "BE", "CA", "CH", "MA"],
}


def _sitelinks(qid: str) -> dict[str, dict]:
    out = {}
    for lang, pages in WORLD.items():
        for p in pages.values():
            if p.qid == qid:
                out[f"{lang}wiki"] = {"site": f"{lang}wiki", "title": p.title, "badges": []}
    return out


def _find(lang: str, title: str) -> tuple[Page | None, Series | None, str | None]:
    """(page, series, redirect_target) for a title that may be a redirect."""
    for p in WORLD.get(lang, {}).values():
        if p.title == title:
            return p, p.series, None
        if title in p.redirects:
            return p, p.redirects[title], p.title
    return None, None, None


def _normalize(title: str) -> str:
    t = title.replace("_", " ").strip()
    return t[:1].upper() + t[1:]


# ----------------------------------------------------------------------- server
class Handler(BaseHTTPRequestHandler):
    server_version = "FakeWikimedia/1.0"
    requests_log: list[str] = []

    def log_message(self, *args) -> None:  # silence
        pass

    def _json(self, code: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        Handler.requests_log.append(self.path)
        if "wikipedia-interest-trends" not in self.headers.get("User-Agent", ""):
            return self._json(403, {"error": "missing user agent"})
        parsed = urllib.parse.urlsplit(self.path)
        parts = [urllib.parse.unquote(p) for p in parsed.path.split("/") if p]
        query = dict(urllib.parse.parse_qsl(parsed.query))
        try:
            if parts[:3] == ["api", "rest_v1", "metrics"]:
                return self._pageviews(parts[3:])
            if parts[:1] == ["wiki"] and len(parts) >= 3:
                return self._mediawiki(parts[1], query)
            if parts[:1] == ["wikidata"]:
                return self._wikidata(query)
        except Exception as exc:  # noqa: BLE001
            return self._json(500, {"error": repr(exc)})
        return self._json(404, {"title": "Not found."})

    # ---- pageviews
    def _pageviews(self, p: list[str]) -> None:
        def span(a: str, b: str) -> tuple[D, D]:
            return D(int(a[:4]), int(a[4:6]), int(a[6:8])), D(int(b[:4]), int(b[4:6]), int(b[6:8]))

        not_found = {"type": "https://mediawiki.org/wiki/HyperSwitch/errors/not_found", "title": "Not found.",
                     "detail": "The date(s) you used are valid, but we either do not have data for those date(s), "
                               "or the project you asked for is not loaded yet."}
        if p[:2] == ["pageviews", "per-article"]:
            project, access, agent, article, gran, start, end = p[2:9]
            lang = project.split(".")[0]
            _, series, _ = _find(lang, article.replace("_", " "))
            if series is None or agent not in ("user", "all-agents"):
                return self._json(404, not_found)
            a, b = span(start, end)
            items = []
            buckets: dict[str, int] = {}
            day = a
            while day <= b:
                allv, desk = daily_views(series, f"{lang}:{article}", day)
                v = {"all-access": allv, "desktop": desk, "mobile-web": int((allv - desk) * 0.8),
                     "mobile-app": allv - desk - int((allv - desk) * 0.8)}[access]
                if v > 0:
                    ts = day.strftime("%Y%m%d00") if gran == "daily" else day.strftime("%Y%m0100")
                    buckets[ts] = buckets.get(ts, 0) + v
                day += dt.timedelta(days=1)
            for ts, v in sorted(buckets.items()):
                items.append({"project": project, "article": article, "granularity": gran, "timestamp": ts,
                              "access": access, "agent": agent, "views": v})
            if not items:
                return self._json(404, not_found)
            return self._json(200, {"items": items})
        if p[:2] == ["pageviews", "aggregate"]:
            project, access, agent, gran, start, end = p[2:8]
            lang = project.split(".")[0]
            if lang not in PROJECTS:
                return self._json(404, not_found)
            a, b = span(start, end)
            buckets = {}
            day = a
            while day <= b:
                ts = day.strftime("%Y%m0100") if gran == "monthly" else day.strftime("%Y%m%d00")
                buckets[ts] = buckets.get(ts, 0) + project_views(lang, day)
                day += dt.timedelta(days=1)
            items = [{"project": project, "access": access, "agent": agent, "granularity": gran, "timestamp": ts,
                      "views": v} for ts, v in sorted(buckets.items())]
            return self._json(200, {"items": items})
        if p[:2] == ["pageviews", "top-by-country"]:
            project, access, year, month = p[2:6]
            lang = project.split(".")[0]
            countries = [{"country": c, "views": "1000000-9999999", "rank": i + 1}
                         for i, c in enumerate(GEO.get(lang, []))]
            return self._json(200, {"items": [{"project": project, "access": access, "year": year, "month": month,
                                               "countries": countries}]})
        return self._json(404, not_found)

    # ---- MediaWiki
    def _mediawiki(self, lang: str, q: dict[str, str]) -> None:
        if lang not in WORLD:
            return self._json(404, {"error": "no such wiki"})
        if q.get("action") != "query":
            return self._json(200, {"error": {"code": "badaction", "info": "unsupported"}})
        if q.get("meta") == "siteinfo":
            return self._json(200, {"query": {"general": {"sitename": "Wikipedia"}}})
        if q.get("generator") == "search":
            needle = q.get("gsrsearch", "").casefold()
            words = [w for w in needle.split() if w]
            hits = []
            for p in WORLD[lang].values():
                hay = (p.title + " " + p.description + " " + " ".join(p.redirects)).casefold()
                if words and all(w in hay for w in words):
                    hits.append(p)
            hits.sort(key=lambda p: (p.disambiguation, p.title.casefold() != needle, len(p.title)))
            pages = []
            for i, p in enumerate(hits[: int(q.get("gsrlimit", 6))], start=1):
                props = {}
                if p.qid:
                    props["wikibase_item"] = p.qid
                if p.disambiguation:
                    props["disambiguation"] = ""
                pages.append({"pageid": 1000 + i, "ns": 0, "title": p.title, "index": i, "pageprops": props,
                              "description": p.description})
            return self._json(200, {"batchcomplete": True, "query": {"pages": pages}} if pages else
                              {"batchcomplete": True})
        titles = q.get("titles", "").split("|")
        normalized, redirects, pages, seen = [], [], [], set()
        for raw in titles:
            t = _normalize(raw)
            if t != raw:
                normalized.append({"from": raw, "to": t})
            page, _, target = _find(lang, t)
            if target:
                redirects.append({"from": t, "to": target})
                t = target
            if t in seen:
                continue
            seen.add(t)
            if page is None:
                pages.append({"ns": 0, "title": t, "missing": True})
                continue
            entry = {"pageid": abs(hash(t)) % 10**6, "ns": 0, "title": page.title,
                     "description": page.description}
            props = {}
            if page.qid:
                props["wikibase_item"] = page.qid
            if page.disambiguation:
                props["disambiguation"] = ""
            if props:
                entry["pageprops"] = props
            if page.redirects:
                entry["redirects"] = [{"pageid": 1, "ns": 0, "title": r} for r in page.redirects]
            pages.append(entry)
        query = {"pages": pages}
        if normalized:
            query["normalized"] = normalized
        if redirects:
            query["redirects"] = redirects
        return self._json(200, {"batchcomplete": True, "query": query})

    # ---- Wikidata
    def _wikidata(self, q: dict[str, str]) -> None:
        if q.get("action") != "wbgetentities":
            return self._json(200, {"error": {"code": "badaction", "info": "unsupported"}})
        langs_ = q.get("languages", "en").split("|")
        entities = {}
        for qid in q.get("ids", "").split("|"):
            if qid not in ENTITIES:
                entities[qid] = {"id": qid, "missing": ""}
                continue
            e = ENTITIES[qid]
            entities[qid] = {
                "type": "item", "id": qid,
                "labels": {l: {"language": l, "value": v} for l, v in e["labels"].items() if l in langs_},
                "descriptions": {l: {"language": l, "value": v} for l, v in e["descriptions"].items() if l in langs_},
                "sitelinks": _sitelinks(qid),
            }
        return self._json(200, {"entities": entities, "success": 1})


class FakeWikimedia:
    def __init__(self, port: int = 0):
        self.httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    @property
    def env(self) -> dict[str, str]:
        base = f"http://127.0.0.1:{self.port}"
        return {
            "WIKITRENDS_REST_BASE": f"{base}/api/rest_v1",
            "WIKITRENDS_WIKI_API": f"{base}/wiki/{{lang}}/api.php",
            "WIKITRENDS_WIKIDATA_API": f"{base}/wikidata/api.php",
            "WIKITRENDS_TODAY": "2026-09-26",
            "WIKITRENDS_MAX_RPS": "200",
        }

    def __enter__(self) -> "FakeWikimedia":
        self.thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args()
    server = FakeWikimedia(args.port)
    for k, v in server.env.items():
        print(f"export {k}='{v}'")
    print(f"# serving fake Wikimedia on http://127.0.0.1:{server.port} (Ctrl+C to stop)", flush=True)
    try:
        server.httpd.serve_forever()
    except KeyboardInterrupt:
        pass
