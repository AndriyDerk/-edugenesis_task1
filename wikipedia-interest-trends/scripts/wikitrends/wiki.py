"""Wikimedia API access: pageviews (Analytics API), MediaWiki Action API
(search, canonical titles, redirects) and Wikidata (cross-language sitelinks).

All results go through ``Cache``; every public method is safe to call
repeatedly and only hits the network for data it has not seen before.
"""

from __future__ import annotations

import datetime as dt
import sys
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any, Callable, Iterable

from . import config, langs
from .cache import Cache
from .net import Client, NetError, NotFound

ACCESS = ("all-access", "desktop", "mobile-web", "mobile-app")
AGENTS = ("user", "all-agents", "automated", "spider")
MW_BATCH = 50
META_TTL_DAYS = 14
SEARCH_TTL_DAYS = 7


@dataclass(frozen=True)
class SeriesKey:
    """One pageview time series. ``title=None`` means the whole project."""

    project: str
    title: str | None
    access: str = "all-access"
    agent: str = "user"
    granularity: str = "daily"

    @property
    def monthly(self) -> bool:
        return self.granularity == "monthly"

    def cache_key(self) -> str:
        return "\x1f".join([self.project, self.title or "__project__", self.access, self.agent, self.granularity])


def _ts_to_iso(ts: str) -> str:
    return f"{ts[0:4]}-{ts[4:6]}-{ts[6:8]}"


class Wiki:
    def __init__(self, client: Client, cache: Cache, workers: int | None = None,
                 progress: Callable[[str], None] | None = None):
        self.client = client
        self.cache = cache
        self.workers = workers or config.workers()
        self.progress = progress or (lambda msg: None)

    # ------------------------------------------------------------------ pageviews
    def _pageviews_url(self, key: SeriesKey, start: dt.date, end: dt.date) -> str:
        base = config.rest_base()
        span = f"{start:%Y%m%d}00/{end:%Y%m%d}00"
        if key.title is None:
            return f"{base}/metrics/pageviews/aggregate/{key.project}/{key.access}/{key.agent}/{key.granularity}/{span}"
        title = urllib.parse.quote(key.title.replace(" ", "_"), safe="")
        return (f"{base}/metrics/pageviews/per-article/{key.project}/{key.access}/{key.agent}/"
                f"{title}/{key.granularity}/{span}")

    def _download(self, key: SeriesKey, start: dt.date, end: dt.date) -> dict[str, int]:
        if key.monthly:
            # ranges are tracked by first-of-month; ask the API up to the month's last day
            end = dt.date(end.year + (end.month == 12), end.month % 12 + 1, 1) - dt.timedelta(days=1)
        url = self._pageviews_url(key, start, end)
        try:
            data = self.client.get_json(url)
        except NotFound:
            return {}  # API answers 404 when there is no data at all for the range
        points: dict[str, int] = {}
        for item in data.get("items", []):
            day = _ts_to_iso(str(item["timestamp"]))
            points[day] = points.get(day, 0) + int(item.get("views", 0))
        return points

    def fetch_series(
        self, keys: Iterable[SeriesKey], start: dt.date, end: dt.date
    ) -> tuple[dict[SeriesKey, dict[str, int]], dict[SeriesKey, str]]:
        """Return ({key: {iso_day: views}}, {key: error}) for [start, end].

        Monthly series use first-of-month keys. Missing days mean zero views.
        """
        keys = list(dict.fromkeys(keys))
        stable = config.stable_until()
        tasks: list[tuple[SeriesKey, dt.date, dt.date]] = []
        for key in keys:
            s, e = (start.replace(day=1), end.replace(day=1)) if key.monthly else (start, end)
            for a, b in self.cache.missing(key.cache_key(), s, e, monthly=key.monthly):
                tasks.append((key, a, b))
        errors: dict[SeriesKey, str] = {}
        if tasks:
            self.progress(f"fetching {len(tasks)} pageview series ({len(keys) - len({t[0] for t in tasks})} of {len(keys)} fully cached)")
            done = 0
            with ThreadPoolExecutor(max_workers=self.workers) as pool:
                futures = {pool.submit(self._download, k, a, b): (k, a, b) for k, a, b in tasks}
                for fut in as_completed(futures):
                    key, a, b = futures[fut]
                    done += 1
                    try:
                        points = fut.result()
                    except NetError as exc:
                        errors[key] = str(exc)
                        continue
                    self.cache.put_series(key.cache_key(), points, a, b, stable, monthly=key.monthly)
                    if done % 20 == 0 or done == len(tasks):
                        self.progress(f"  {done}/{len(tasks)} series downloaded")
        result = {}
        for key in keys:
            s, e = (start.replace(day=1), end) if key.monthly else (start, end)
            result[key] = self.cache.get_series(key.cache_key(), s, e)
        return result, errors

    def top_countries(self, lang: str, year: int, month: int, access: str = "all-access") -> list[dict[str, Any]]:
        """Countries whose readers use this language edition most (views are
        privacy-bucketed by Wikimedia, so only rank and bucket are reliable)."""
        ckey = f"geo:{lang}:{access}:{year}-{month:02d}"
        cached = self.cache.get(ckey)
        if cached is not None:
            return cached
        url = f"{config.rest_base()}/metrics/pageviews/top-by-country/{langs.project(lang)}/{access}/{year}/{month:02d}"
        try:
            data = self.client.get_json(url)
        except NotFound:
            data = {"items": []}
        rows: list[dict[str, Any]] = []
        for item in data.get("items", []):
            for c in item.get("countries", []):
                views = c.get("views_ceil", c.get("views"))
                rows.append({"country": c.get("country"), "rank": c.get("rank"), "views": views})
        rows.sort(key=lambda r: (r["rank"] if isinstance(r["rank"], int) else 10**9))
        self.cache.set(ckey, rows, ttl_days=365)
        return rows

    # ------------------------------------------------------------ MediaWiki API
    def _mw(self, lang: str, params: dict[str, Any], max_continue: int = 5) -> list[dict[str, Any]]:
        """Run an Action API query following continuation; returns all responses."""
        base = {"action": "query", "format": "json", "formatversion": "2"}
        base.update(params)
        responses = []
        cont: dict[str, Any] = {}
        for _ in range(max_continue):
            data = self.client.get_json(config.wiki_api(lang), {**base, **cont})
            if "error" in data:
                raise NetError(f"MediaWiki API error on {lang}: {data['error'].get('info', data['error'])}")
            responses.append(data)
            if "continue" not in data:
                break
            cont = data["continue"]
        else:
            if responses and "continue" in responses[-1]:
                responses[-1]["_truncated"] = True
        return responses

    def page_info(self, lang: str, titles: list[str], max_redirects: int = 30) -> dict[str, dict[str, Any]]:
        """Canonical title, Wikidata id, disambiguation flag and incoming
        redirects for each input title (input titles may themselves be redirects)."""
        out: dict[str, dict[str, Any]] = {}
        todo = []
        for t in dict.fromkeys(titles):
            cached = self.cache.get(f"page:{lang}:{max_redirects}:{t}")
            if cached is not None:
                out[t] = cached
            else:
                todo.append(t)
        for i in range(0, len(todo), MW_BATCH):
            batch = todo[i:i + MW_BATCH]
            responses = self._mw(lang, {
                "titles": "|".join(batch),
                "redirects": "1",
                "prop": "pageprops|redirects|description",
                "ppprop": "wikibase_item|disambiguation",
                "rdprop": "title",
                "rdnamespace": "0",
                "rdlimit": "max",
            })
            mapping: dict[str, str] = {}
            pages: dict[str, dict[str, Any]] = {}
            truncated = bool(responses and responses[-1].get("_truncated"))
            for data in responses:
                q = data.get("query", {})
                for n in q.get("normalized", []):
                    mapping[n["from"]] = n["to"]
                for r in q.get("redirects", []):
                    mapping[r["from"]] = r["to"]
                for p in q.get("pages", []):
                    page = pages.setdefault(p["title"], {"title": p["title"], "redirects": []})
                    if p.get("missing") or p.get("invalid"):
                        page["missing"] = True
                    props = p.get("pageprops") or {}
                    if "wikibase_item" in props:
                        page["qid"] = props["wikibase_item"]
                    if "disambiguation" in props:
                        page["disambiguation"] = True
                    if p.get("description"):
                        page["description"] = p["description"]
                    page["redirects"].extend(r["title"] for r in p.get("redirects", []))
            for t in batch:
                canonical = t
                seen = set()
                while canonical in mapping and canonical not in seen:
                    seen.add(canonical)
                    canonical = mapping[canonical]
                page = pages.get(canonical, {"title": canonical, "missing": True, "redirects": []})
                redirects = sorted(set(page.get("redirects", [])))
                info = {
                    "input": t,
                    "title": page["title"],
                    "exists": not page.get("missing", False),
                    "qid": page.get("qid"),
                    "disambiguation": bool(page.get("disambiguation")),
                    "description": page.get("description", ""),
                    "redirects": redirects[:max_redirects],
                    "redirects_total": len(redirects),
                    "redirects_truncated": len(redirects) > max_redirects or truncated,
                    "was_redirect": canonical != t and t.replace("_", " ") != canonical,
                }
                out[t] = info
                self.cache.set(f"page:{lang}:{max_redirects}:{t}", info, ttl_days=META_TTL_DAYS)
        return out

    def search(self, lang: str, query: str, limit: int = 6) -> list[dict[str, Any]]:
        """Full-text search on one Wikipedia; returns ranked article candidates."""
        ckey = f"search:{lang}:{limit}:{query.strip().lower()}"
        cached = self.cache.get(ckey)
        if cached is not None:
            return cached
        responses = self._mw(lang, {
            "generator": "search",
            "gsrsearch": query,
            "gsrlimit": str(limit),
            "gsrnamespace": "0",
            "prop": "pageprops|description",
            "ppprop": "wikibase_item|disambiguation",
            "redirects": "1",
        }, max_continue=1)
        rows = []
        for data in responses:
            for p in data.get("query", {}).get("pages", []):
                props = p.get("pageprops") or {}
                rows.append({
                    "title": p["title"],
                    "qid": props.get("wikibase_item"),
                    "description": p.get("description", ""),
                    "disambiguation": "disambiguation" in props,
                    "index": p.get("index", 999),
                })
        rows.sort(key=lambda r: r["index"])
        for r in rows:
            r.pop("index", None)
        self.cache.set(ckey, rows, ttl_days=SEARCH_TTL_DAYS)
        return rows

    # ------------------------------------------------------------------ Wikidata
    def entities(self, qids: list[str], label_langs: list[str]) -> dict[str, dict[str, Any]]:
        """Labels, descriptions and all Wikipedia sitelinks ({lang: title})."""
        out: dict[str, dict[str, Any]] = {}
        todo = []
        want_labels = sorted(set(["en"] + list(label_langs)))
        for q in dict.fromkeys(qids):
            cached = self.cache.get(f"wd:{q}")
            if cached is not None and all(l in cached.get("label_langs", []) for l in want_labels):
                out[q] = cached
            else:
                todo.append(q)
        for i in range(0, len(todo), MW_BATCH):
            batch = todo[i:i + MW_BATCH]
            data = self.client.get_json(config.wikidata_api(), {
                "action": "wbgetentities",
                "ids": "|".join(batch),
                "props": "labels|descriptions|sitelinks",
                "languages": "|".join(want_labels),
                "languagefallback": "1",
                "format": "json",
            })
            if "error" in data:
                raise NetError(f"Wikidata error: {data['error'].get('info', data['error'])}")
            entities = data.get("entities", {})
            redirected = {}
            for ent_id, ent in entities.items():
                if isinstance(ent, dict) and ent.get("redirects"):
                    redirected[ent["redirects"].get("from")] = ent_id
            for q in batch:
                ent = entities.get(q) or entities.get(redirected.get(q, ""), {})
                if not ent or "missing" in ent:
                    info = {"qid": q, "missing": True, "labels": {}, "descriptions": {}, "sitelinks": {},
                            "label_langs": want_labels}
                else:
                    sitelinks = {}
                    for site_id, link in (ent.get("sitelinks") or {}).items():
                        code = langs.code_from_site(site_id)
                        if code:
                            sitelinks[code] = link["title"]
                    info = {
                        "qid": ent.get("id", q),
                        "labels": {k: v["value"] for k, v in (ent.get("labels") or {}).items()},
                        "descriptions": {k: v["value"] for k, v in (ent.get("descriptions") or {}).items()},
                        "sitelinks": sitelinks,
                        "label_langs": want_labels,
                    }
                out[q] = info
                self.cache.set(f"wd:{q}", info, ttl_days=META_TTL_DAYS)
        return out


def stderr_progress(message: str) -> None:
    print(f"[wikitrends] {message}", file=sys.stderr, flush=True)
