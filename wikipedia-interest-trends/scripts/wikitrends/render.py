"""Text outputs: compact console summary for the agent, Markdown summary for
people, CSV of the monthly data."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from . import i18n, langs
from .findings import caveats, findings, name_of, ordered_cells


def _yoy_cell(y: dict[str, Any] | None, lang: str = "en") -> str:
    if not y or y.get("value") is None:
        return "n/a"
    lo, hi = y["ci"]
    return f"{i18n.fmt_pct(y['value'], lang)} [{i18n.fmt_pct(lo, lang)}..{i18n.fmt_pct(hi, lang)}]"


def _articles_line(cell: dict[str, Any]) -> str:
    if cell.get("error"):
        return f"  {cell['lang']}: -- {cell['error']}"
    parts = []
    for a in cell["articles"]:
        extra = f" +{a['redirects']} redirects" if a["redirects"] else ""
        if a.get("redirects_truncated"):
            extra += f" (of {a['redirects_total']})"
        parts.append(f"\"{a['title']}\"{extra}")
    missing = f"; missing: {', '.join(cell['missing_items'])}" if cell.get("missing_items") else ""
    topic = "" if cell["label"] == cell["lang"] else f"[{cell['topic']}] "
    return f"  {cell['lang']}: {topic}{'; '.join(parts)}{missing}"


def console_summary(results: dict[str, Any], files: dict[str, str] | None = None) -> str:
    """Compact English summary (~40 lines) designed for an LLM agent to read."""
    lines: list[str] = []
    w = results["window"]
    p = results["params"]
    lines.append("== wikitrends analysis ==")
    for t in results["resolution"]["topics"]:
        items = []
        for it in t["items"]:
            desc = f" ({it['description']})" if it.get("description") else ""
            items.append(f"{it['qid'] or it['title']} \"{it['label']}\"{desc} via {it['method']}")
        lines.append(f"Topic \"{t['label']}\": " + "; ".join(items))
        for it in t["items"]:
            if it.get("alternatives") and it["method"] != "wikidata id":
                alts = "; ".join(f"{a['qid']} {a['title']}" for a in it["alternatives"][:3])
                lines.append(f"  other candidates for '{it['spec']}': {alts}")
    lines.append(
        f"Period {w['label']} ({w['months']} months). Growth compares {w['last12']} with {w['prev12']}. "
        f"Views: agent={p['agent']}, redirects {'included' if p['include_redirects'] else 'excluded'}.")
    lines.append("Articles:")
    for cell in results["cells"]:
        lines.append(_articles_line(cell))

    lines.append("")
    lines.append("| option | views/mo | YoY w/o spikes [90% CI] | months up | vs wiki | trend | confidence |")
    lines.append("|---|---|---|---|---|---|---|")
    for cell in ordered_cells(results):
        if cell.get("error"):
            lines.append(f"| {cell['label']} | - | n/a | - | - | {cell['error']} | - |")
            continue
        mt = cell["metrics"]
        y = mt["yoy"]
        norm = (mt.get("yoy_normalized") or {}).get("value")
        if mt["direction"] == "new-article":
            lines.append(f"| {cell['label']} | {i18n.fmt_compact(mt['avg_monthly_last12'])} | n/a: article "
                         f"started {cell.get('new_article')} | - | - | new-article | "
                         f"{cell['confidence']['grade']} {cell['confidence']['score']} |")
            continue
        lines.append(
            f"| {cell['label']} | {i18n.fmt_compact(mt['avg_monthly_last12'])} | {_yoy_cell(y)} | "
            f"{y['months_up']}/12 | {i18n.fmt_pct(norm)} | {mt['direction']} | "
            f"{cell['confidence']['grade']} {cell['confidence']['score']} |")

    comps = results.get("comparisons") or []
    if comps:
        lines.append("")
        lines.append("Comparisons (difference in YoY growth, 90% CI):")
        for c in comps[:5]:
            verdict = c["verdict"].replace("_", " ")
            if c["winner"]:
                winner = c["a_label"] if c["winner"] == c["a"] else c["b_label"]
                verdict = f"{winner} grew faster"
            lines.append(f"- {c['a_label']} vs {c['b_label']}: {i18n.fmt_pp(c['diff_pp'])} pp "
                         f"[{i18n.fmt_pp(c['ci_pp'][0])}..{i18n.fmt_pp(c['ci_pp'][1])}] -> {verdict}")

    ranking = results.get("ranking")
    if ranking:
        wts = " ".join(f"{k}={v:g}" for k, v in ranking["weights"].items())
        lines.append("")
        lines.append(f"Ranking by {ranking['dimension']} (weights {wts}):")
        for row in ranking["rows"][:8]:
            why = []
            if row["strengths"]:
                why.append("strong: " + ", ".join(row["strengths"]))
            if row["weaknesses"]:
                why.append("weak: " + ", ".join(row["weaknesses"]))
            lines.append(f"  {row['rank']}. {row['label']}  score {row['score']:.0f}  " + "; ".join(why))
        if ranking["top_stable"]:
            lines.append(f"  top pick is the same under all {ranking['top_agreement']} weighting presets (robust)")
        else:
            alts = ", ".join(f"{k}->{v.split(':')[-1]}" for k, v in ranking["sensitivity"].items())
            lines.append(f"  top pick depends on weights ({ranking['top_agreement']} presets agree): {alts}")

    lines.append("")
    lines.append("Findings (quote these; do not invent numbers):")
    for f in findings(results, "en"):
        lines.append(f"- {f}")
    cav = caveats(results, "en")
    if cav:
        lines.append("Caveats:")
        for c in cav:
            lines.append(f"- {c}")
    other = [x for x in results.get("warnings", []) if x not in cav]
    if other:
        lines.append("Warnings:")
        for x in other[:5]:
            lines.append(f"- {x}")
    fetch = results.get("fetch", {})
    lines.append(f"(network requests this run: {fetch.get('requests', 0)}; everything else came from cache)")
    if files:
        lines.append("Files:")
        for k, v in files.items():
            lines.append(f"  {k}: {v}")
    return "\n".join(lines)


def markdown_summary(results: dict[str, Any], lang: str = "en", title: str | None = None,
                     question: str | None = None, summary: str | None = None,
                     recommendation: str | None = None, charts: dict[str, str] | None = None) -> str:
    lang = i18n.ui(lang)
    L = lambda k: i18n.label(k, lang)  # noqa: E731
    w = results["window"]
    out: list[str] = []
    topics = ", ".join(t.get("labels", {}).get(lang, t["label"]) for t in results["resolution"]["topics"])
    out.append(f"# {title or topics}")
    if question:
        out.append(f"*{L('questions')}: {question}*")
    out.append(f"{L('period')}: {i18n.fmt_month(w['start'][:7], lang)} – {i18n.fmt_month(w['end'][:7], lang)} · "
               f"{', '.join(langs.label(c, lang) for c in results['params']['langs'])} · {L('human')}")
    if summary:
        out.append(f"\n## {L('summary')}\n\n{summary}")
    out.append(f"\n## {L('key_findings')}\n")
    for f in findings(results, lang):
        out.append(f"- {f}")
    out.append(f"\n| {L('table_lang')} | {L('table_avg')} | {L('table_yoy')} | {L('table_norm')} | "
               f"{L('table_dir')} | {L('table_conf')} |")
    out.append("|---|---:|---|---:|---|---|")
    for cell in ordered_cells(results):
        name = name_of(results, cell, lang)
        if cell.get("error"):
            out.append(f"| {name} | – | – | – | {cell['error']} | – |")
            continue
        mt = cell["metrics"]
        norm = (mt.get("yoy_normalized") or {}).get("value")
        if mt["direction"] == "new-article":
            norm = None
        yoy_txt = "–" if mt["direction"] == "new-article" else _yoy_cell(mt["yoy"], lang)
        out.append(f"| {name} | {i18n.fmt_compact(mt['avg_monthly_last12'], lang)} | {yoy_txt} | "
                   f"{i18n.fmt_pct(norm, lang)} | {i18n.direction(mt['direction'], lang)} | "
                   f"{i18n.grade(cell['confidence']['grade'], lang)} ({cell['confidence']['score']}) |")
    if charts:
        out.append("")
        for name, path in charts.items():
            out.append(f"![{name}]({Path(path).name})")
    out.append(f"\n## {L('recommendation')}\n")
    if recommendation:
        out.append(recommendation)
    else:
        for step in L("auto_next"):
            out.append(f"- {step}")
    cav = caveats(results, lang)
    if cav:
        out.append(f"\n## {L('caveats')}\n")
        for c in cav:
            out.append(f"- {c}")
    out.append(f"\n## {L('limitations')}\n")
    out.append(i18n.METHOD[lang])
    for lim in i18n.LIMITATIONS[lang]:
        out.append(f"- {lim}")
    out.append(f"\n_{L('source')} · {L('generated')} {results['generated_at'][:10]} · wikitrends {results['tool_version']}_")
    return "\n".join(out) + "\n"


def write_csv(results: dict[str, Any], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        wr = csv.writer(fh)
        wr.writerow(["topic", "lang", "month", "days", "views_raw", "views_clean", "project_views",
                     "per_million", "main_titles_all_access", "main_titles_desktop"])
        for cell in results["cells"]:
            if cell.get("error"):
                continue
            m = cell["monthly"]
            proj = m.get("project") or [None] * len(m["months"])
            desk = m.get("desktop_main") or [None] * len(m["months"])
            for i, month in enumerate(m["months"]):
                per_million = (m["clean"][i] / proj[i] * 1e6) if proj[i] else None
                wr.writerow([cell["topic"], cell["lang"], month, m["days"][i], m["raw"][i], m["clean"][i], proj[i],
                             None if per_million is None else round(per_million, 3), m["main_all"][i], desk[i]])
