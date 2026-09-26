"""Data-driven findings and caveats, generated from a results dict.

These sentences are the backbone of every summary: the agent should relay or
lightly rephrase them instead of inventing new numbers.
"""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from . import i18n
from .analysis import growth_valid
from .config import ASSETS_DIR


@lru_cache(maxsize=1)
def _countries() -> dict[str, list[str]]:
    data = json.loads((ASSETS_DIR / "countries.json").read_text(encoding="utf-8"))
    data.pop("_comment", None)
    return data


def country_name(code: str | None, lang: str = "en") -> str:
    if not code:
        return "?"
    names = _countries().get(code.upper())
    if not names:
        return code
    return names[1] if i18n.ui(lang) == "uk" else names[0]


def topic_labels(results: dict[str, Any], lang: str) -> dict[str, str]:
    lang = i18n.ui(lang)
    return {t["id"]: t.get("labels", {}).get(lang, t["label"]) for t in results["resolution"]["topics"]}


def name_of(results: dict[str, Any], cell: dict[str, Any], lang: str) -> str:
    return i18n.cell_name(cell, lang, topic_labels(results, lang))


def ordered_cells(results: dict[str, Any]) -> list[dict[str, Any]]:
    """Ranked order when a ranking exists, else input order; failed cells last."""
    cells = results["cells"]
    ranking = results.get("ranking")
    if ranking:
        pos = {row["cell"]: row["rank"] for row in ranking["rows"]}
        return sorted(cells, key=lambda c: (c.get("error") is not None, pos.get(c["id"], 999)))
    return sorted(cells, key=lambda c: c.get("error") is not None)


def headline(results: dict[str, Any], cell: dict[str, Any], lang: str) -> str:
    name = name_of(results, cell, lang)
    if cell.get("error"):
        return i18n.text("headline_na", lang, name=name, reason=cell["error"])
    mt = cell["metrics"]
    y = mt["yoy"]
    if mt["direction"] == "new-article":
        return i18n.text("headline_new", lang, name=name, date=cell.get("new_article", "?"),
                         avg=i18n.fmt_compact(mt["avg_monthly_last12"], lang),
                         grade=i18n.grade(cell["confidence"]["grade"], lang))
    if y["value"] is None:
        return i18n.text("headline_na", lang, name=name, reason=i18n.reason("no_baseline", {}, lang))
    growing = y["value"] >= 0
    return i18n.text(
        "headline", lang, name=name, direction=i18n.direction(mt["direction"], lang),
        yoy=i18n.fmt_pct(y["value"], lang), lo=i18n.fmt_pct(y["ci"][0], lang), hi=i18n.fmt_pct(y["ci"][1], lang),
        agree=y["months_up"] if growing else y["months_down"],
        updown=i18n.text("up" if growing else "down", lang),
        avg=i18n.fmt_compact(mt["avg_monthly_last12"], lang),
        grade=i18n.grade(cell["confidence"]["grade"], lang))


def findings(results: dict[str, Any], lang: str = "en", max_cells: int = 6) -> list[str]:
    """Most decision-relevant sentences first (the PDF shows only the first few)."""
    lang = i18n.ui(lang)
    out: list[str] = []
    cells = ordered_cells(results)
    by_id = {c["id"]: c for c in cells}
    ok = [c for c in cells if growth_valid(c)]
    ranking = results.get("ranking")
    comps = list(results.get("comparisons", []))

    def comparison_line(comp: dict[str, Any]) -> str:
        a, b = by_id[comp["a"]], by_id[comp["b"]]
        if comp["verdict"] == "faster":
            verdict = i18n.text("faster", lang, x=name_of(results, by_id[comp["winner"]], lang))
        else:
            verdict = i18n.text(comp["verdict"], lang)
        return i18n.text("compare", lang, a=name_of(results, a, lang), b=name_of(results, b, lang),
                         diff=i18n.fmt_pp(comp["diff_pp"], lang), lo=i18n.fmt_pp(comp["ci_pp"][0], lang),
                         hi=i18n.fmt_pp(comp["ci_pp"][1], lang), verdict=verdict)

    # 1. the answer to "which one?": ranking (3+ options) or the head-to-head comparison (2 options)
    if ranking and len(ranking["rows"]) >= 3:
        top = ranking["rows"][0]
        if ranking["top_stable"]:
            stability = i18n.text("rank_stable", lang, n=len(ranking["sensitivity"]))
        else:
            alts = []
            for preset, cid in ranking["sensitivity"].items():
                alts.append(f"{i18n.PRESET[lang].get(preset, preset)}: {name_of(results, by_id[cid], lang)}")
            stability = i18n.text("rank_unstable", lang, alts="; ".join(alts))
        out.append(i18n.text("ranking", lang, dimension=i18n.TEXT[lang]["dimension"][ranking["dimension"]],
                             label=name_of(results, by_id[top["cell"]], lang), score=f"{top['score']:.0f}",
                             stability=stability))
        scores = {r["cell"]: r["score"] for r in ranking["rows"]}
        for group in ranking.get("ties", [])[:2]:
            names = ", ".join(f"{name_of(results, by_id[c], lang)} ({scores[c]:.0f})" for c in group)
            out.append(i18n.text("tie", lang, names=names))
        parts = []
        for row in ranking["rows"][:6]:
            good = ", ".join(i18n.COMPONENT[lang][k] for k in row.get("strong", []))
            bad = ", ".join(i18n.COMPONENT[lang][k] for k in row.get("weak", []))
            desc = "; ".join(x for x in (f"+ {good}" if good else "", f"− {bad}" if bad else "") if x)
            if desc:
                parts.append(f"{name_of(results, by_id[row['cell']], lang)}: {desc}")
        if parts:
            out.append(i18n.text("why", lang, parts=" | ".join(parts)))
    elif comps:
        out.append(comparison_line(comps.pop(0)))

    # 2. one line per option
    for cell in cells[:max_cells]:
        out.append(headline(results, cell, lang))
    if len(cells) > max_cells:
        out.append(f"(+{len(cells) - max_cells} more in the table)" if lang == "en"
                   else f"(ще {len(cells) - max_cells} — у таблиці)")

    # 3. supporting detail
    for comp in comps[: (2 if ranking else 3)]:
        out.append(comparison_line(comp))
    shown = 0
    for cell in ok:
        mt = cell["metrics"]
        norm = mt.get("yoy_normalized") or {}
        proj = mt.get("project_yoy")
        if norm.get("value") is None or proj is None:
            continue
        if True:  # always state it: "vs wiki" alone is easy to misread
            out.append(i18n.text("normalized", lang, wiki=f"{cell['lang']}.wikipedia", project=i18n.fmt_pct(proj, lang),
                                 name=name_of(results, cell, lang), norm=i18n.fmt_pct(norm["value"], lang)))
            shown += 1
            if shown >= 2:
                break

    for cell in ok[:2]:
        mt = cell["metrics"]
        if mt["last3_yoy"] is not None and abs(mt["last3_yoy"] - mt["yoy"]["value"]) >= 0.20:
            accel = "accelerating" if mt["last3_yoy"] > mt["yoy"]["value"] else "slowing"
            out.append(i18n.text("momentum", lang, name=name_of(results, cell, lang),
                                 accel=i18n.text(accel, lang), last3=i18n.fmt_pct(mt["last3_yoy"], lang),
                                 yoy=i18n.fmt_pct(mt["yoy"]["value"], lang)))

    if ok and ok[0]["metrics"]["trend"]["months"] >= 36:
        c = ok[0]
        tr = c["metrics"]["trend"]
        out.append(i18n.text("longrun", lang, name=name_of(results, c, lang), n=tr["months"],
                             sen=i18n.fmt_pct(tr["sen_annual_growth"], lang), p=i18n.fmt_p(tr["seasonal_kendall_p"], lang)))

    best = None
    for cell in ok:
        total = cell["metrics"]["total_views_raw"] or 1
        for ev in cell["spikes"]["events"][:1]:
            if ev["excess_views"] / total >= 0.02 and (best is None or ev["excess_views"] / total > best[0]):
                best = (ev["excess_views"] / total, cell, ev)
    if best:
        _, cell, ev = best
        out.append(i18n.text("spike", lang, date=ev["peak_day"], name=name_of(results, cell, lang),
                             ratio=i18n.fmt_num(ev["ratio"], lang, 1), kind=i18n.SPIKE_KIND[lang][ev["kind"]]))

    if ranking and len({c["lang"] for c in ok}) > 1:
        top_lang = by_id[ranking["rows"][0]["cell"]]["lang"]
        geo = results.get("geo", {}).get(top_lang)
        if geo and geo.get("top"):
            countries = ", ".join(country_name(r["country"], lang) for r in geo["top"][:4])
            out.append(i18n.text("geo", lang, wiki=f"{top_lang}.wikipedia", countries=countries))
    return out


def caveats(results: dict[str, Any], lang: str = "en", max_items: int = 6) -> list[str]:
    lang = i18n.ui(lang)
    out: list[str] = []
    for cell in ordered_cells(results):
        if cell.get("error"):
            continue
        name = name_of(results, cell, lang)
        negatives = sorted((r for r in cell["confidence"]["reasons"] if r["effect"] < 0),
                           key=lambda r: r["effect"])
        for r in negatives[:2]:
            out.append(f"{name}: {i18n.reason(r['code'], r.get('data'), lang)}")
    for w in results["resolution"].get("warnings", []):
        if "ambiguous" in w or "picked top search result" in w or "does not exist" in w:
            out.append(i18n.note(w, lang))
    for note in results["window"].get("notes", []):
        out.append(i18n.note(note, lang))
    return list(dict.fromkeys(out))[:max_items]
