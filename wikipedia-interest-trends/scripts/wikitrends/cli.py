"""Command line interface. Run via ``python scripts/wt.py <command> ...``."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any

from . import __version__, analysis, config, i18n, langs, periods
from .cache import Cache
from .net import Client, NetError
from .resolve import ResolveError, parse_topics, resolve_topics
from .wiki import SeriesKey, Wiki, stderr_progress

EXIT_INPUT, EXIT_NET, EXIT_DEPS = 2, 3, 4


class UserError(Exception):
    pass


# ------------------------------------------------------------------ plumbing
def _make_wiki(args: argparse.Namespace) -> Wiki:
    cache = Cache(None if getattr(args, "no_cache", False) else config.cache_path())
    client = Client(config.user_agent(), rps=config.max_rps(), offline=config.offline(), token=config.api_token(),
                    on_wait=stderr_progress)
    return Wiki(client, cache, progress=None if getattr(args, "quiet", False) else stderr_progress)


def _out_root() -> Path:
    return Path(os.environ.get("WIKITRENDS_OUT", "wikitrends-out")).resolve()


_TRANSLIT = dict(zip("абвгґдеєжзиіїйклмнопрстуфхцчшщьюяыэёъ",
                     ["a", "b", "v", "h", "g", "d", "e", "ie", "zh", "z", "y", "i", "i", "i", "k", "l", "m", "n",
                      "o", "p", "r", "s", "t", "u", "f", "kh", "ts", "ch", "sh", "shch", "", "iu", "ia", "y", "e",
                      "io", ""]))


def _slug(text: str, limit: int = 60) -> str:
    text = "".join(_TRANSLIT.get(ch, ch) for ch in text.lower())
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_text).strip("-").lower()
    return s[:limit].strip("-") or "topic"


def _results_path(target: str) -> Path:
    p = Path(target)
    if p.is_dir():
        p = p / "results.json"
    if not p.exists():
        raise UserError(f"no results at '{target}' (pass the analysis folder or its results.json)")
    return p


def _load(target: str) -> tuple[dict[str, Any], Path]:
    path = _results_path(target)
    return json.loads(path.read_text(encoding="utf-8")), path


def _save(results: dict[str, Any], path: Path) -> None:
    path.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")


def _read_text_arg(value: str | None, file_value: str | None) -> str | None:
    if file_value:
        return Path(file_value).read_text(encoding="utf-8").strip()
    return value.strip() if value else None


def _log_history(root: Path, entry: dict[str, Any]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    with (root / "history.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _window(args: argparse.Namespace) -> periods.Window:
    return periods.make_window(months=args.months, start=args.start, end=args.end)


def _langs(value: str) -> tuple[list[str], list[str]]:
    codes, notes = langs.parse_list(value)
    if not codes:
        raise UserError("--langs is empty; example: --langs pl,cs")
    if len(codes) > 25:
        raise UserError("too many languages (max 25 per run); split the question into several runs")
    return codes, notes


# ------------------------------------------------------------------ commands
def cmd_resolve(args: argparse.Namespace) -> int:
    codes, notes = _langs(args.langs)
    topics = parse_topics(args.topic, args.basket)
    if not topics:
        raise UserError("give at least one --topic or --basket")
    wiki = _make_wiki(args)
    res = resolve_topics(wiki, topics, codes, search_lang=args.search_lang, include_redirects=True,
                         max_redirects=args.max_redirects)
    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=1))
        return 0
    for n in notes:
        print(f"note: {n}")
    for t in res["topics"]:
        print(f"Topic \"{t['label']}\"")
        for it in t["items"]:
            desc = f" - {it['description']}" if it.get("description") else ""
            print(f"  item {it['qid'] or '-'} \"{it['label']}\"{desc}  [{it['method']}: {it['spec']}]")
            for a in it.get("alternatives", [])[:4]:
                d = f" - {a['description']}" if a.get("description") else ""
                print(f"    alternative: {a['qid']} {a['title']}{d}")
        for lang in codes:
            cell = t["cells"][lang]
            if not cell["articles"]:
                print(f"  {lang}: NO ARTICLE")
                continue
            arts = "; ".join(f"{a['title']} (+{len(a['redirects'])} redirects)" for a in cell["articles"])
            miss = f"  | missing: {', '.join(cell['missing'])}" if cell["missing"] else ""
            print(f"  {lang}: {arts}{miss}")
    for w in res["warnings"]:
        print(f"warning: {w}")
    return 0


def cmd_analyze(args: argparse.Namespace) -> int:
    codes, notes = _langs(args.langs)
    topics = parse_topics(args.topic, args.basket)
    if not topics:
        raise UserError("give at least one --topic or --basket (see --help)")
    if len(topics) * len(codes) > 60:
        raise UserError("too many topic x language combinations (max 60); narrow the question")
    window = _window(args)
    weights = analysis.parse_weights(args.weights)
    ui = i18n.ui(args.lang)
    params = analysis.Params(
        topics=topics, langs=codes, window=window, search_lang=args.search_lang, agent=args.agent,
        include_redirects=not args.no_redirects, max_redirects=args.max_redirects, max_requests=args.max_requests,
        platform_split=not args.no_platform, geo=not args.no_geo, weights=weights, ui_lang=ui, notes=notes)
    wiki = _make_wiki(args)
    results = analysis.run(wiki, params)

    if args.out:
        outdir = Path(args.out).resolve()
    else:
        topic_part = "+".join(_slug(t["label"], 30) for t in results["resolution"]["topics"])
        outdir = _out_root() / f"{topic_part}_{'-'.join(codes)}_{window.start:%Y%m}-{window.end:%Y%m}"[:120]
    outdir.mkdir(parents=True, exist_ok=True)
    results_path = outdir / "results.json"
    _save(results, results_path)

    from .render import console_summary, markdown_summary, write_csv
    write_csv(results, outdir / "monthly.csv")
    files: dict[str, str] = {"results": str(results_path), "data": str(outdir / "monthly.csv")}

    from . import charts
    made: dict[str, str] = {}
    if not args.no_charts:
        if charts.available():
            made = charts.make_charts(results, outdir, ui)
            files.update(made)
        else:
            files["charts"] = "skipped (matplotlib missing: run `python scripts/wt.py setup`)"
    (outdir / "summary.md").write_text(markdown_summary(results, ui, args.title, args.question, charts=made),
                                       encoding="utf-8")
    files["summary"] = str(outdir / "summary.md")
    if args.pdf:
        files.update(_make_report(results, outdir, ui, args.title, args.question, None, None))

    _log_history(_out_root() if not args.out else outdir.parent, {
        "time": dt.datetime.now().isoformat(timespec="seconds"), "dir": str(outdir),
        "topics": [t["label"] for t in results["resolution"]["topics"]], "langs": codes,
        "period": window.label(), "argv": sys.argv[1:],
    })
    if args.json:
        print(json.dumps({"results": str(results_path), "files": files}, ensure_ascii=False))
    else:
        print(console_summary(results, files, ui))
        print(f"\nNext: share -> python scripts/wt.py report {outdir} --lang {ui} --summary \"...\" ; "
              f"re-weight -> python scripts/wt.py rank {outdir} --weights growth-first")
    return 0


def _make_report(results: dict[str, Any], outdir: Path, lang: str, title: str | None, question: str | None,
                 summary: str | None, recommendation: str | None) -> dict[str, str]:
    try:
        from .report import write_report
        import reportlab  # noqa: F401
    except ImportError:
        return {"pdf": "skipped (reportlab/matplotlib missing: run `python scripts/wt.py setup`)"}
    info = write_report(results, outdir, lang, title, question, summary, recommendation)
    out = {"pdf": info["pdf"], "report_markdown": info["markdown"]}
    out.update(info["charts"])
    return out


def cmd_report(args: argparse.Namespace) -> int:
    results, path = _load(args.results)
    summary = _read_text_arg(args.summary, args.summary_file)
    recommendation = _read_text_arg(args.recommendation, args.recommendation_file)
    from .report import check_attribution, check_claims
    text = "\n".join(x for x in (summary, recommendation, args.title, args.question) if x)
    problems = check_claims(text, results)
    misattributed = check_attribution(text, results)
    for p in misattributed:
        print(f"ATTRIBUTION CHECK: '{p['claim']}' is written next to {p['said_for']} but is the figure of "
              f"{p['belongs_to']}")
    if misattributed and args.strict:
        print("Fix the text and run again. No PDF written (--strict).")
        return EXIT_INPUT
    if problems:
        print("NUMBER CHECK: these figures in your text do not match the analysis:")
        for p in problems:
            hint = f" (closest computed: {p['closest']} = {p['closest_is']})" if p["closest"] is not None else ""
            print(f"  - '{p['claim']}'{hint}")
        if args.strict:
            print("Fix the text (use numbers from results/summary) and run again. No PDF written (--strict).")
            return EXIT_INPUT
    else:
        print("number check: all percentages in the text match the analysis")
    outdir = path.parent
    files = _make_report(results, outdir, i18n.ui(args.lang), args.title, args.question, summary, recommendation)
    for k, v in files.items():
        print(f"{k}: {v}")
    return 0


def cmd_rank(args: argparse.Namespace) -> int:
    results, path = _load(args.results)
    weights = analysis.parse_weights(args.weights)
    analysis.rerank(results, weights)
    _save(results, path)
    ranking = results["ranking"]
    if not ranking:
        print("ranking needs at least two measurable options")
        return 0
    wts = " ".join(f"{k}={v:g}" for k, v in ranking["weights"].items())
    print(f"Ranking by {ranking['dimension']} (weights {wts}); results.json updated:")
    for row in ranking["rows"]:
        inp = row["inputs"]
        tie = "  (≈ tie)" if row.get("tied") else ""
        print(f"  {row['rank']}. {row['label']:<24} score {row['score']:5.1f} | views/mo "
              f"{i18n.fmt_compact(inp['avg_monthly_views'])} | growth {i18n.fmt_pct(inp['growth'])} | "
              f"topic share of wiki {i18n.fmt_pct(inp['growth_vs_wiki'])} | {inp['confidence']}{tie}")
    print(f"top pick agreement across presets: {ranking['top_agreement']} "
          f"({'robust' if ranking['top_stable'] else 'depends on priorities'})")
    by_id = {c["id"]: c for c in results["cells"]}
    for group in ranking.get("ties", []):
        print("practically tied (within 3 points, choose by priority): "
              + ", ".join(by_id[c]["label"] for c in group))
    print("Views are page views, not unique people. Quote scores and numbers exactly as printed.")
    return 0


def cmd_views(args: argparse.Namespace) -> int:
    m = re.match(r"^([a-z][a-z0-9-]*):(.+)$", args.article)
    if not m:
        raise UserError("article must look like lang:Title, e.g. uk:Астрономія")
    lang, _ = langs.normalize(m.group(1))
    title = m.group(2).strip()
    window = periods.make_window(months=args.months, start=args.start, end=args.end, min_months=1)
    wiki = _make_wiki(args)
    info = wiki.page_info(lang, [title])[title]
    if not info["exists"]:
        raise UserError(f"{lang}:{title} does not exist")
    key = SeriesKey(langs.project(lang), info["title"], args.access, args.agent, args.granularity)
    data, errors = wiki.fetch_series([key], window.start, window.end)
    if errors:
        raise NetError(errors[key])
    points = data[key]
    if args.granularity == "daily":
        rows = [(d.isoformat(), points.get(d.isoformat(), 0)) for d in periods.days(window.start, window.end)]
    else:
        rows = [(m_ + "-01", points.get(m_ + "-01", 0)) for m_ in window.months]
    print(f"# {lang}:{info['title']} {args.access} {args.agent} {args.granularity} {window.label()}")
    print("date,views")
    for d, v in rows:
        print(f"{d},{v}")
    return 0


def cmd_history(args: argparse.Namespace) -> int:
    path = _out_root() / "history.jsonl"
    if not path.exists():
        print("no previous analyses in", path.parent)
        return 0
    lines = path.read_text(encoding="utf-8").strip().splitlines()[-args.limit:]
    for line in lines:
        e = json.loads(line)
        print(f"{e['time']}  {', '.join(e['topics'])} [{','.join(e['langs'])}] {e['period']}\n    {e['dir']}")
    return 0


def cmd_cache(args: argparse.Namespace) -> int:
    cache = Cache(config.cache_path())
    if args.action == "clear":
        cache.clear(metadata_only=args.metadata_only)
        print("cache cleared" + (" (metadata only)" if args.metadata_only else ""))
    info = cache.info()
    print(json.dumps(info, indent=1))
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    ok = True
    print(f"wikitrends {__version__} | python {sys.version.split()[0]} | {sys.executable}")
    for mod in ("matplotlib", "reportlab"):
        try:
            m = __import__(mod)
            print(f"  [ok] {mod} {getattr(m, '__version__', getattr(m, 'Version', ''))}")
        except ImportError:
            ok = False
            print(f"  [!!] {mod} missing -> charts/PDF disabled; run: python scripts/wt.py setup")
    try:
        cache = Cache(config.cache_path())
        print(f"  [ok] cache {cache.info()['path']}")
    except Exception as exc:  # noqa: BLE001
        ok = False
        print(f"  [!!] cache not writable: {exc} (set WIKITRENDS_HOME)")
    client = Client(config.user_agent(), rps=config.max_rps(), retries=1, timeout=15)
    checks = [
        ("pageviews API", f"{config.rest_base()}/metrics/pageviews/aggregate/en.wikipedia/all-access/user/monthly/2024010100/2024013100"),
        ("en.wikipedia API", config.wiki_api("en") + "?action=query&meta=siteinfo&format=json"),
        ("Wikidata API", config.wikidata_api() + "?action=wbgetentities&ids=Q2&props=labels&languages=en&format=json"),
    ]
    if config.offline():
        print("  [--] offline mode (WIKITRENDS_OFFLINE=1): network checks skipped")
    else:
        for name, url in checks:
            try:
                client.get_json(url)
                print(f"  [ok] {name} reachable")
            except NetError as exc:
                ok = False
                print(f"  [!!] {name}: {exc}")
    print(f"  user-agent: {config.user_agent()}")
    print("all good" if ok else "problems found (see [!!] lines)")
    return 0 if ok else 1


# ------------------------------------------------------------------ parser
def _add_topic_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--topic", action="append", metavar="TOPIC",
                   help="topic as free text ('intermittent fasting'), a Wikidata id (Q11002) or an article "
                        "('en:Astronomy', 'uk:Астрономія'). Repeat to compare topics.")
    p.add_argument("--basket", action="append", nargs="+", metavar="ITEM",
                   help="one topic made of several articles (all arguments are articles; optional "
                        "name=\"...\" labels it): --basket \"English language\" \"English as a second or foreign "
                        "language\" name=\"Learning English\". Items: free text, Q-ids or lang:Title. Repeatable.")
    p.add_argument("--langs", required=True, help="Wikipedia language codes, comma separated: pl,cs,uk")
    p.add_argument("--search-lang", default="en", help="wiki used to search free-text topics (default en)")
    p.add_argument("--max-redirects", type=int, default=10,
                   help="redirects counted per article, oldest first (default 10)")


def _add_period_args(p: argparse.ArgumentParser, default_months: int | None = 24) -> None:
    p.add_argument("--months", type=int, default=None,
                   help=f"last N complete months (default {default_months}; minimum 24 for analyze)")
    p.add_argument("--start", help="first month YYYY-MM (overrides --months)")
    p.add_argument("--end", help="last month YYYY-MM (default: last complete month)")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="wt.py",
        description="Wikipedia pageview research: trends, cross-language comparison, confidence, charts, PDF.")
    p.add_argument("--version", action="version", version=f"wikitrends {__version__}")
    p.add_argument("--quiet", action="store_true", help="no progress messages on stderr")
    p.add_argument("--no-cache", action="store_true", help="use a throwaway in-memory cache")
    # the same flags are accepted after the sub-command too (agents put them anywhere)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--quiet", action="store_true", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    common.add_argument("--no-cache", action="store_true", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    sub = p.add_subparsers(dest="command", required=True)

    a = sub.add_parser("analyze", parents=[common], help="full analysis: resolve, fetch, stats, charts (+PDF with --pdf)")
    _add_topic_args(a)
    _add_period_args(a)
    a.add_argument("--agent", default="user", choices=["user", "all-agents", "automated", "spider"],
                   help="traffic type (default user = humans)")
    a.add_argument("--no-redirects", action="store_true", help="count only the main article titles")
    a.add_argument("--no-platform", action="store_true", help="skip desktop/mobile split (fewer requests)")
    a.add_argument("--max-requests", type=int, default=400,
                   help="upper bound on pageview series per run; redirects are trimmed to fit (default 400)")
    a.add_argument("--no-geo", action="store_true", help="skip reader-country lookup")
    a.add_argument("--weights", help="ranking weights: preset (balanced, growth-first, size-first, niche-first) "
                                     "or reach=0.3,momentum=0.4,intensity=0.2,confidence=0.1")
    a.add_argument("--lang", default="en", choices=list(i18n.SUPPORTED), help="language of charts/summary/PDF")
    a.add_argument("--title", help="report title")
    a.add_argument("--question", help="the user's question, printed under the title")
    a.add_argument("--pdf", action="store_true", help="also build the one-page PDF report")
    a.add_argument("--no-charts", action="store_true")
    a.add_argument("--out", help="output folder (default wikitrends-out/<topic>_<langs>_<period>)")
    a.add_argument("--json", action="store_true", help="print only paths as JSON")
    a.set_defaults(func=cmd_analyze)

    r = sub.add_parser("report", parents=[common], help="one-page PDF + Markdown from a previous analysis")
    r.add_argument("results", help="analysis folder or results.json")
    r.add_argument("--lang", default="en", choices=list(i18n.SUPPORTED))
    r.add_argument("--title")
    r.add_argument("--question")
    r.add_argument("--summary", help="2-4 sentence executive summary written from the findings")
    r.add_argument("--summary-file")
    r.add_argument("--recommendation", help="recommendation / next steps (Markdown bullets allowed)")
    r.add_argument("--recommendation-file")
    r.add_argument("--strict", action="store_true", help="refuse to build if the text has unverified numbers")
    r.set_defaults(func=cmd_report)

    k = sub.add_parser("rank", parents=[common], help="re-rank options with other weights (no refetch)")
    k.add_argument("results")
    k.add_argument("--weights", required=True)
    k.set_defaults(func=cmd_rank)

    s = sub.add_parser("resolve", parents=[common], help="show which articles would be analysed in each language")
    _add_topic_args(s)
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_resolve)

    v = sub.add_parser("views", parents=[common], help="raw pageviews of one article as CSV")
    v.add_argument("article", help="lang:Title, e.g. uk:Астрономія")
    _add_period_args(v, default_months=24)
    v.add_argument("--granularity", default="monthly", choices=["daily", "monthly"])
    v.add_argument("--access", default="all-access", choices=["all-access", "desktop", "mobile-web", "mobile-app"])
    v.add_argument("--agent", default="user", choices=["user", "all-agents", "automated", "spider"])
    v.set_defaults(func=cmd_views)

    h = sub.add_parser("history", parents=[common], help="list previous analyses (for follow-up questions)")
    h.add_argument("--limit", type=int, default=10)
    h.set_defaults(func=cmd_history)

    c = sub.add_parser("cache", parents=[common], help="cache info / clear")
    c.add_argument("action", choices=["info", "clear"])
    c.add_argument("--metadata-only", action="store_true", help="clear only titles/redirects/search cache")
    c.set_defaults(func=cmd_cache)

    d = sub.add_parser("doctor", parents=[common], help="check dependencies, cache and network access")
    d.set_defaults(func=cmd_doctor)
    return p


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except (AttributeError, ValueError):
            pass
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (UserError, ResolveError, periods.PeriodError, langs.LangError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return EXIT_INPUT
    except NetError as exc:
        print(f"NETWORK ERROR: {exc}", file=sys.stderr)
        print("hint: run `python scripts/wt.py doctor`; cached data still works offline (WIKITRENDS_OFFLINE=1).",
              file=sys.stderr)
        return EXIT_NET
