"""Shareable outputs: one-page PDF (reportlab) + Markdown, and a numeric claim
checker that flags percentages in agent-written text that do not match the
analysis (a guard against hallucinated or mis-copied numbers)."""

from __future__ import annotations

import html
import re
from pathlib import Path
from typing import Any

from . import i18n, langs
from .findings import caveats, findings, name_of, ordered_cells

# ----------------------------------------------------------------- claim check
_NUM = r"[+\-−–]?\s?\d{1,4}(?:[.,]\d+)?"
PCT_RE = re.compile(rf"(?<![\w.,])({_NUM})\s?(%|\s?pp\b|\s?п\.\s?п\.|\s?в\.\s?п\.)", re.IGNORECASE)
CI_WORDS = re.compile(r"\b(ci|ді|conf\w*|uncertaint\w*|interval\w*|довір\w*|інтервал\w*|невизначен\w*|"
                      r"bootstrap|бутстреп\w*)", re.IGNORECASE)


def is_ci_level(value: float, text: str, start: int, end: int) -> bool:
    """'90% CI', 'довірчий інтервал 90%' etc. name the interval level, not a result."""
    return abs(value) in (80.0, 90.0, 95.0, 99.0) and bool(CI_WORDS.search(text[max(0, start - 30):end + 25]))


def _num(s: str) -> float:
    return float(s.replace("−", "-").replace("–", "-").replace(" ", "").replace(",", "."))


def known_values(results: dict[str, Any]) -> tuple[list[tuple[float, str]], list[tuple[float, str]]]:
    """Every percentage and every percentage-point figure the analysis produced."""
    vals: list[tuple[float, str]] = []
    pps: list[tuple[float, str]] = []

    def add(v: float | None, what: str, scale: float = 100.0, pool: list | None = None) -> None:
        if v is not None:
            (vals if pool is None else pool).append((v * scale, what))

    for c in results["cells"]:
        if c.get("error"):
            continue
        mt = c["metrics"]
        tag = c["label"]
        for key in ("yoy", "yoy_raw", "yoy_normalized"):
            block = mt.get(key)
            if block:
                add(block.get("value"), f"{tag} {key}")
                for bound in block.get("ci") or []:
                    add(bound, f"{tag} {key} CI bound")
        add(mt.get("project_yoy"), f"{c['lang']}.wikipedia overall YoY")
        add(mt.get("last3_yoy"), f"{tag} last-3-months YoY")
        add(mt.get("cagr"), f"{tag} CAGR")
        add(mt["trend"].get("sen_annual_growth"), f"{tag} Sen annual growth")
        add(mt.get("spike_excess_share"), f"{tag} spike share")
        plat = mt.get("platform") or {}
        add(plat.get("desktop_share_last12"), f"{tag} desktop share")
        add(plat.get("desktop_yoy"), f"{tag} desktop YoY")
        add(plat.get("mobile_yoy"), f"{tag} mobile YoY")
        if plat.get("desktop_share_last12") is not None:
            add(1 - plat["desktop_share_last12"], f"{tag} mobile share")
        for r in c["confidence"]["reasons"]:
            for k, v in (r.get("data") or {}).items():
                if isinstance(v, (int, float)) and k in ("share", "lo", "hi", "raw", "clean", "norm", "project",
                                                          "desktop", "mobile"):
                    add(v, f"{tag} {r['code']}")
        for ev in c["spikes"]["events"]:
            total = mt["total_views_raw"] or 1
            add(ev["excess_views"] / total, f"{tag} spike {ev['peak_day']} share")
        for r in c["confidence"]["reasons"]:
            if r["code"] == "wide_ci":
                add(r["data"]["width"], f"{tag} CI width", 1.0, pps)
    for comp in results.get("comparisons", []):
        add(comp.get("diff_pp"), f"{comp['a_label']} vs {comp['b_label']} difference", 1.0, pps)
        for b in comp.get("ci_pp") or []:
            add(b, f"{comp['a_label']} vs {comp['b_label']} difference CI", 1.0, pps)
    # a difference is sometimes written with % instead of pp: accept those too
    return vals + pps, pps


def check_claims(text: str, results: dict[str, Any]) -> list[dict[str, Any]]:
    """Return claims (percentages / pp) that match no computed figure."""
    known_pct, known_pp = known_values(results)
    problems = []
    for m in PCT_RE.finditer(text or ""):
        raw = m.group(1)
        try:
            v = _num(raw)
        except ValueError:
            continue
        if is_ci_level(v, text, m.start(), m.end()):
            continue
        is_pp = m.group(2).strip().lower() != "%"
        best = None
        for k, what in (known_pp if is_pp else known_pct):
            d = abs(abs(v) - abs(k))
            if best is None or d < best[0]:
                best = (d, k, what)
        tol = max(1.05, 0.03 * abs(best[1])) if best else 0
        if best is None or best[0] > tol:
            problems.append({
                "claim": m.group(0).strip(),
                "closest": None if best is None else round(best[1], 1),
                "closest_is": None if best is None else best[2],
            })
    return problems


# ------------------------------------------------------------ attribution check
VIEWS_RE = re.compile(r"(?<![\w.,])(\d{1,3}(?:[.,]\d)?)\s?(k\b|тис\.?|тисяч\w*|thousand)|"
                      r"(?<![\w.,])(\d{1,3}[ \u202f,]\d{3})(?![\d%])", re.IGNORECASE)


def _cell_values(cell: dict[str, Any]) -> list[float]:
    mt = cell["metrics"]
    out: list[float] = []
    for key in ("yoy", "yoy_raw", "yoy_normalized"):
        block = mt.get(key) or {}
        for v in [block.get("value")] + list(block.get("ci") or []):
            if v is not None:
                out.append(v * 100)
    for v in (mt.get("last3_yoy"), mt.get("cagr"), (mt.get("trend") or {}).get("sen_annual_growth")):
        if v is not None:
            out.append(v * 100)
    return out


COUNTRY_STEMS = {  # a sentence naming a country talks about that market too: do not judge it
    "uk": ["Україн", "Ukrain"], "pl": ["Польщ", "Poland", "Polish"], "cs": ["Чехі", "Czech"],
    "sk": ["Словаччин", "Slovak"], "de": ["Німеччин", "Австрі", "German", "Austria"],
    "fr": ["Франці", "France", "French"], "es": ["Іспані", "Мексик", "Spain", "Mexic"],
    "pt": ["Португалі", "Бразилі", "Portug", "Brazil"], "tr": ["Туреччин", "Turkey", "Türkiye"],
    "it": ["Італі", "Ital"], "ru": ["Росі", "Russia"], "en": ["США", "Британі", "USA", "Britain"],
}


def _lang_stems(code: str) -> list[str]:
    stems = []
    for ui in ("en", "uk"):
        name = langs.name(code, ui)
        if name and name != code:
            stem = name.split(" (")[0]
            stems.append(stem[:-2] if ui == "uk" and len(stem) > 5 else stem)  # українська -> українськ(а/ої)
    return stems


def check_attribution(text: str, results: dict[str, Any]) -> list[dict[str, Any]]:
    """Numbers stated for one language that actually belong to another one
    (e.g. 'Portuguese: 98k views/month' when 98k is Spanish).

    Conservative on purpose: a line/sentence is judged only when it *starts*
    with a language name (a bullet like '- Polish (pl): +2.7%...') and mentions
    no other language or country anywhere."""
    cells = [c for c in results.get("cells", []) if not c.get("error") and c.get("metrics")]
    if len({c["lang"] for c in cells}) < 2 or len({c["topic_id"] for c in cells}) > 1:
        return []
    info = []
    for c in cells:
        names = _lang_stems(c["lang"])
        subject = re.compile("|".join([rf"\({re.escape(c['lang'])}\)"] + [rf"\b{re.escape(n)}" for n in names]),
                             re.IGNORECASE)
        any_ref = re.compile("|".join([subject.pattern] + [re.escape(x) for x in COUNTRY_STEMS.get(c["lang"], [])]),
                             re.IGNORECASE)
        info.append((c, subject, any_ref, _cell_values(c), c["metrics"]["avg_monthly_last12"]))
    problems = []
    for sentence in re.split(r"\n+|(?<=[.;!?])\s+", text or ""):
        head = re.sub(r"^[\s>*#\-•\d.)|]+", "", sentence)[:20]
        subjects = [x for x in info if x[1].search(head)]
        if len(subjects) != 1:
            continue
        cell, _, _, own_pct, own_views = subjects[0]
        if any(x[2].search(sentence) for x in info if x[0] is not cell):
            continue
        others = [x for x in info if x[0] is not cell]
        for m in PCT_RE.finditer(sentence):
            if m.group(2).strip() != "%":
                continue
            v = _num(m.group(1))
            if is_ci_level(v, sentence, m.start(), m.end()):
                continue
            if any(abs(abs(v) - abs(k)) <= max(1.05, 0.03 * abs(k)) for k in own_pct):
                continue
            owner = next((o for o in others if any(abs(abs(v) - abs(k)) <= 0.15 for k in o[3])), None)
            if owner:
                problems.append({"claim": m.group(0).strip(), "said_for": cell["label"],
                                 "belongs_to": owner[0]["label"]})
        for m in VIEWS_RE.finditer(sentence):
            v = _num(m.group(1)) * 1000 if m.group(1) else float(re.sub(r"[ \u202f,]", "", m.group(3)))
            if abs(v - own_views) <= max(0.08 * own_views, 600):
                continue
            owner = next((o for o in others if abs(v - o[4]) <= max(0.08 * o[4], 600)), None)
            if owner:
                problems.append({"claim": m.group(0).strip(), "said_for": cell["label"],
                                 "belongs_to": owner[0]["label"]})
    return problems


# ----------------------------------------------------------------------- PDF
def _font_paths() -> dict[str, str]:
    import matplotlib
    base = Path(matplotlib.get_data_path()) / "fonts" / "ttf"
    return {
        "regular": str(base / "DejaVuSans.ttf"),
        "bold": str(base / "DejaVuSans-Bold.ttf"),
        "italic": str(base / "DejaVuSans-Oblique.ttf"),
        "bolditalic": str(base / "DejaVuSans-BoldOblique.ttf"),
    }


_CMAP: set[int] | None = None


def _register_fonts() -> None:
    global _CMAP
    from reportlab.lib.fonts import addMapping
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    if "WT" in pdfmetrics.getRegisteredFontNames():
        return
    paths = _font_paths()
    pdfmetrics.registerFont(TTFont("WT", paths["regular"]))
    pdfmetrics.registerFont(TTFont("WT-Bold", paths["bold"]))
    pdfmetrics.registerFont(TTFont("WT-Italic", paths["italic"]))
    pdfmetrics.registerFont(TTFont("WT-BoldItalic", paths["bolditalic"]))
    addMapping("WT", 0, 0, "WT")
    addMapping("WT", 1, 0, "WT-Bold")
    addMapping("WT", 0, 1, "WT-Italic")
    addMapping("WT", 1, 1, "WT-BoldItalic")
    try:
        from fontTools.ttLib import TTFont as FTFont
        _CMAP = set(FTFont(paths["regular"]).getBestCmap().keys())
    except Exception:  # noqa: BLE001 - glyph filtering is best effort
        _CMAP = None


def _safe(text: str) -> str:
    """Drop characters the embedded font cannot draw (e.g. CJK) instead of
    printing empty boxes."""
    if _CMAP is None:
        return text
    out = []
    for ch in text:
        out.append(ch if ord(ch) in _CMAP or ch in "\n\t" else "?")
    s = "".join(out)
    return re.sub(r"\?{2,}", "…", s)


def _md_inline(text: str) -> str:
    """Escape for reportlab Paragraph and support **bold** / *italic*."""
    s = html.escape(_safe(text), quote=False)
    s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
    s = re.sub(r"(?<!\*)\*(?!\s)(.+?)(?<!\s)\*(?!\*)", r"<i>\1</i>", s)
    return s


def _md_blocks(text: str) -> list[tuple[str, str]]:
    """Split simple Markdown into ('p'|'li', text) blocks."""
    blocks: list[tuple[str, str]] = []
    para: list[str] = []
    for line in (text or "").splitlines():
        stripped = line.strip()
        if re.match(r"^([-*•]|\d+[.)])\s+", stripped):
            if para:
                blocks.append(("p", " ".join(para)))
                para = []
            blocks.append(("li", re.sub(r"^([-*•]|\d+[.)])\s+", "", stripped)))
        elif not stripped:
            if para:
                blocks.append(("p", " ".join(para)))
                para = []
        else:
            para.append(stripped.lstrip("#").strip())
    if para:
        blocks.append(("p", " ".join(para)))
    return blocks


def build_pdf(results: dict[str, Any], path: Path, lang: str = "en", title: str | None = None,
              question: str | None = None, summary: str | None = None, recommendation: str | None = None,
              charts: dict[str, str] | None = None) -> dict[str, Any]:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import (Image, KeepInFrame, ListFlowable, ListItem, Paragraph, SimpleDocTemplate,
                                    Spacer, Table, TableStyle)

    lang = i18n.ui(lang)
    _register_fonts()
    charts = charts or {}
    L = lambda k: i18n.label(k, lang)  # noqa: E731
    ink, muted, accent = colors.HexColor("#0f172a"), colors.HexColor("#64748b"), colors.HexColor("#2563eb")

    def style(name: str, size: float, leading: float | None = None, color=ink, font: str = "WT",
              space_after: float = 0, **kw: Any) -> ParagraphStyle:
        return ParagraphStyle(name, fontName=font, fontSize=size, leading=leading or size * 1.28,
                              textColor=color, spaceAfter=space_after, alignment=TA_LEFT, **kw)

    s_title = style("title", 15.5, font="WT-Bold", space_after=1)
    s_q = style("q", 8.6, color=colors.HexColor("#334155"), font="WT-Italic")
    s_meta = style("meta", 7, color=muted)
    s_h = style("h", 9.4, font="WT-Bold", color=accent, space_after=1.5)
    s_body = style("body", 8.1, leading=10.1)
    s_small = style("small", 6.9, leading=8.4, color=colors.HexColor("#334155"))
    s_tiny = style("tiny", 6.2, leading=7.6, color=muted)
    s_cell = style("cell", 7, leading=8.4)
    s_cellb = style("cellb", 7, leading=8.4, font="WT-Bold")

    page_w, page_h = A4
    margin_x, margin_y = 13 * mm, 11 * mm
    frame_w = page_w - 2 * margin_x
    frame_h = page_h - 2 * margin_y

    w = results["window"]
    topics = ", ".join(t.get("labels", {}).get(lang, t["label"]) for t in results["resolution"]["topics"])
    lang_list = ", ".join(langs.label(c, lang) for c in results["params"]["langs"])

    def bullets(items: list[str], st: ParagraphStyle) -> ListFlowable:
        return ListFlowable([ListItem(Paragraph(_md_inline(t), st), leftIndent=8, value="•") for t in items],
                            bulletType="bullet", start="•", leftIndent=8, bulletFontName="WT",
                            bulletFontSize=st.fontSize, spaceBefore=0, spaceAfter=0)

    def md(text: str, st: ParagraphStyle) -> list[Any]:
        out: list[Any] = []
        pending: list[str] = []
        for kind, t in _md_blocks(text):
            if kind == "li":
                pending.append(t)
                continue
            if pending:
                out.append(bullets(pending, st))
                pending = []
            out.append(Paragraph(_md_inline(t), st))
        if pending:
            out.append(bullets(pending, st))
        return out

    def image(path_: str, width: float) -> Image:
        from reportlab.lib.utils import ImageReader
        iw, ih = ImageReader(path_).getSize()
        return Image(path_, width=width, height=width * ih / iw)

    def metrics_table(max_rows: int) -> Table:
        header = [L("table_lang"), L("table_avg"), L("table_yoy"), L("table_norm"), L("table_dir"),
                  L("table_conf")]
        has_rank = bool(results.get("ranking"))
        if has_rank:
            header.append(L("table_score"))
        rows = [[Paragraph(html.escape(h), s_cellb) for h in header]]
        rank_score = {r["cell"]: r["score"] for r in (results.get("ranking") or {}).get("rows", [])}
        for cell in ordered_cells(results)[:max_rows]:
            name = _safe(name_of(results, cell, lang))
            if cell.get("error"):
                row = [name, "–", "–", "–", _safe(cell["error"]), "–"] + (["–"] if has_rank else [])
            else:
                mt = cell["metrics"]
                y = mt["yoy"]
                norm = (mt.get("yoy_normalized") or {}).get("value")
                yoy_txt = (f"{i18n.fmt_pct(y['value'], lang)} ({i18n.fmt_pct(y['ci'][0], lang)}…"
                           f"{i18n.fmt_pct(y['ci'][1], lang)})") if y["value"] is not None else "–"
                if mt["direction"] == "new-article":
                    yoy_txt, norm = "–", None
                row = [name, i18n.fmt_compact(mt["avg_monthly_last12"], lang), yoy_txt, i18n.fmt_pct(norm, lang),
                       i18n.direction(mt["direction"], lang),
                       f"{i18n.grade(cell['confidence']['grade'], lang)} ({cell['confidence']['score']})"]
                if has_rank:
                    sc = rank_score.get(cell["id"])
                    row.append("–" if sc is None else f"{sc:.0f}")
            rows.append([Paragraph(html.escape(str(v)), s_cell) for v in row])
        widths = [0.24, 0.12, 0.25, 0.1, 0.15, 0.14] + ([0.07] if has_rank else [])
        scale = 1.0 / sum(widths)
        t = Table(rows, colWidths=[frame_w * x * scale for x in widths], repeatRows=1)
        st = [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e2e8f0")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LINEBELOW", (0, 0), (-1, 0), 0.6, colors.HexColor("#94a3b8")),
            ("TOPPADDING", (0, 0), (-1, -1), 1.6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 1.6),
            ("LEFTPADDING", (0, 0), (-1, -1), 3),
            ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ]
        for r in range(1, len(rows)):
            if r % 2 == 0:
                st.append(("BACKGROUND", (0, r), (-1, r), colors.HexColor("#f8fafc")))
        grade_col = 5
        for r, cell in enumerate(ordered_cells(results)[:max_rows], start=1):
            if not cell.get("error"):
                color = {"HIGH": "#dcfce7", "MEDIUM": "#fef3c7", "LOW": "#fee2e2"}[cell["confidence"]["grade"]]
                st.append(("BACKGROUND", (grade_col, r), (grade_col, r), colors.HexColor(color)))
        t.setStyle(TableStyle(st))
        return t

    def articles_line() -> str:
        parts = []
        for cell in results["cells"]:
            if cell.get("error"):
                continue
            titles = ", ".join(_safe(a["title"]) + (f" (+{a['redirects']})" if a["redirects"] else "")
                               for a in cell["articles"])
            parts.append(f"{cell['lang']}: {titles}")
        prefix = "Articles (+redirects): " if lang == "en" else "Статті (+перенаправлення): "
        return prefix + "; ".join(parts)

    def build(level: int) -> list[Any]:
        """level 0 = full, 1 = compact, 2 = minimal."""
        story: list[Any] = []
        story.append(Paragraph(_md_inline(title or topics), s_title))
        if question:
            story.append(Paragraph(_md_inline(question), s_q))
        meta = (f"{L('period')}: {i18n.fmt_month(w['start'][:7], lang)} – {i18n.fmt_month(w['end'][:7], lang)} · "
                f"{_safe(lang_list)} · {L('human')} · {L('generated')} {results['generated_at'][:10]}")
        story.append(Paragraph(html.escape(meta), s_meta))
        story.append(Spacer(1, 4))
        if summary:
            box = Table([[md(summary, s_body)]], colWidths=[frame_w])
            box.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#eff6ff")),
                ("LINEBEFORE", (0, 0), (0, -1), 2.2, accent),
                ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]))
            story.append(box)
            story.append(Spacer(1, 4))
        f_items = findings(results, lang, max_cells=6 if level == 0 else 4)
        story.append(Paragraph(html.escape(L("key_findings")), s_h))
        story.append(bullets(f_items[: (9 if level == 0 else 6 if level == 1 else 4)], s_body))
        story.append(Spacer(1, 4))
        if "trend" in charts:
            story.append(image(charts["trend"], frame_w * (1.0 if level == 0 else 0.85)))
        side = []
        if "growth" in charts:
            side.append(image(charts["growth"], frame_w * (0.56 if "opportunity" in charts and level < 2 else 0.62)))
        if "opportunity" in charts and level < 2:
            side.append(image(charts["opportunity"], frame_w * 0.42))
        if side:
            row = Table([side], colWidths=[frame_w * 0.57, frame_w * 0.43][: len(side)] if len(side) == 2 else [frame_w])
            row.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                                     ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
            story.append(row)
        story.append(Spacer(1, 3))
        story.append(metrics_table(10 if level == 0 else 7 if level == 1 else 5))
        story.append(Spacer(1, 5))
        story.append(Paragraph(html.escape(L("recommendation")), s_h))
        if recommendation:
            story.extend(md(recommendation, s_body))
        else:
            story.append(bullets(L("auto_next"), s_body))
        cav = caveats(results, lang, max_items=5 if level == 0 else 3)
        if cav:
            story.append(Spacer(1, 3))
            story.append(Paragraph(html.escape(L("caveats")), s_h))
            story.append(bullets(cav, s_small))
        story.append(Spacer(1, 3))
        story.append(Paragraph(html.escape(L("limitations")), s_h))
        story.append(Paragraph(html.escape(i18n.METHOD[lang]), s_tiny))
        lims = i18n.LIMITATIONS[lang] if level < 2 else i18n.LIMITATIONS[lang][:2]
        story.append(Paragraph(html.escape(" ".join(lims)), s_tiny))
        story.append(Paragraph(html.escape(articles_line()), s_tiny))
        story.append(Paragraph(html.escape(f"{L('source')} (wikimedia.org/api/rest_v1) · wikitrends "
                                           f"{results['tool_version']}"), s_tiny))
        return story

    import io
    from reportlab.pdfgen.canvas import Canvas
    measure = Canvas(io.BytesIO(), pagesize=A4)

    def height_of(story: list[Any]) -> float:
        total = 0.0
        for f in story:
            _, h = f.wrapOn(measure, frame_w, frame_h)
            total += h + getattr(f, "spaceAfter", 0) + getattr(f, "spaceBefore", 0)
        return total

    level = 0
    story = build(0)
    natural = height_of(story)
    while natural > frame_h * 1.18 and level < 2:
        level += 1
        story = build(level)
        natural = height_of(story)

    doc = SimpleDocTemplate(str(path), pagesize=A4, leftMargin=margin_x, rightMargin=margin_x,
                            topMargin=margin_y, bottomMargin=margin_y,
                            title=_safe(title or topics), author="wikipedia-interest-trends",
                            subject="Wikipedia pageview interest report")
    doc.build([KeepInFrame(frame_w, frame_h, story, mode="shrink")])
    return {"path": str(path), "detail_level": level, "shrink": round(min(1.0, frame_h / natural), 3) if natural else 1.0}


def write_report(results: dict[str, Any], outdir: Path, lang: str = "en", title: str | None = None,
                 question: str | None = None, summary: str | None = None, recommendation: str | None = None,
                 pdf_name: str = "report.pdf") -> dict[str, Any]:
    from . import charts as charts_mod
    from .render import markdown_summary

    outdir.mkdir(parents=True, exist_ok=True)
    made = charts_mod.make_charts(results, outdir, lang)
    md_path = outdir / "report.md"
    md_path.write_text(markdown_summary(results, lang, title, question, summary, recommendation, made),
                       encoding="utf-8")
    info = build_pdf(results, outdir / pdf_name, lang, title, question, summary, recommendation, made)
    return {"pdf": info["path"], "markdown": str(md_path), "charts": made, "detail_level": info["detail_level"],
            "shrink": info["shrink"]}
