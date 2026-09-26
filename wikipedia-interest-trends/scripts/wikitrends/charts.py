"""Charts (matplotlib, Agg backend). Generated from a results dict so they can be
re-rendered in another language without refetching."""

from __future__ import annotations

import math
import textwrap
from pathlib import Path
from typing import Any

from . import i18n
from .analysis import growth_valid
from .findings import name_of, ordered_cells

PALETTE = ["#2563eb", "#dc2626", "#16a34a", "#9333ea", "#ea580c", "#0891b2", "#be185d", "#4d7c0f",
           "#475569", "#b45309"]
GRADE_COLORS = {"HIGH": "#16a34a", "MEDIUM": "#f59e0b", "LOW": "#dc2626"}
MAX_LINES = 8


def available() -> bool:
    try:
        import matplotlib  # noqa: F401
        return True
    except ImportError:
        return False


def _plt():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({
        "font.family": "DejaVu Sans",
        "font.size": 8,
        "axes.titlesize": 9,
        "axes.titleweight": "bold",
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.edgecolor": "#94a3b8",
        "axes.labelcolor": "#334155",
        "xtick.color": "#475569",
        "ytick.color": "#475569",
        "axes.grid": True,
        "grid.color": "#e2e8f0",
        "grid.linewidth": 0.6,
        "legend.frameon": False,
        "legend.fontsize": 7,
        "savefig.dpi": 200,
        "svg.fonttype": "none",
    })
    return plt


def _month_ticks(months: list[str], lang: str) -> tuple[list[int], list[str]]:
    n = len(months)
    step = 3 if n <= 30 else 6 if n <= 60 else 12
    idx = [i for i, m in enumerate(months) if (int(m[5:7]) - 1) % step == 0]
    return idx, [i18n.fmt_month(months[i], lang) for i in idx]


def _pct_formatter(lang: str):
    from matplotlib.ticker import FuncFormatter
    return FuncFormatter(lambda v, _: i18n.fmt_pct(v, lang, signed=True, nd=0))


def trend_chart(results: dict[str, Any], path: Path, lang: str) -> Path | None:
    plt = _plt()
    cells = [c for c in ordered_cells(results) if not c.get("error")][:MAX_LINES]
    if not cells:
        return None
    months = cells[0]["monthly"]["months"]
    n = len(months)
    x = list(range(n))
    fig, ax = plt.subplots(figsize=(7.4, 2.6))
    single = len(cells) == 1
    if single:
        c = cells[0]
        ax.plot(x, c["monthly"]["raw"], color=PALETTE[0], alpha=0.35, lw=1, ls="--", label="raw")
        ax.plot(x, c["monthly"]["clean"], color=PALETTE[0], lw=2, label=name_of(results, c, lang))
        ax.set_title(i18n.label("chart_trend_abs", lang), loc="left")
        from matplotlib.ticker import FuncFormatter
        ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: i18n.fmt_compact(v, lang)))
        ax.set_ylim(bottom=0)
    else:
        for i, c in enumerate(cells):
            clean = c["monthly"]["clean"]
            base = sum(clean[:12]) / 12.0
            if base <= 0 or c["metrics"]["direction"] == "new-article":
                continue  # an index against a near-empty first year is meaningless
            ax.plot(x, [v / base * 100 for v in clean], color=PALETTE[i % len(PALETTE)], lw=1.8,
                    label=name_of(results, c, lang))
        ax.axhline(100, color="#64748b", lw=0.8, ls=":")
        ax.set_title(i18n.label("chart_trend_idx", lang), loc="left")
    if n >= 24:
        ax.axvspan(n - 12 - 0.5, n - 0.5, color="#dbeafe", alpha=0.45, lw=0, zorder=0)
        ax.axvspan(n - 24 - 0.5, n - 12 - 0.5, color="#f1f5f9", alpha=0.6, lw=0, zorder=0)
        for x0, key in ((n - 24, "period_prev"), (n - 12, "period_last")):
            ax.text(x0 - 0.3, 1.0, i18n.label(key, lang), transform=ax.get_xaxis_transform(), fontsize=6.5,
                    color="#475569", va="top", ha="left")
    ticks, labels = _month_ticks(months, lang)
    ax.set_xticks(ticks)
    ax.set_xticklabels(labels)
    ax.set_xlim(-0.5, n - 0.5)
    ax.legend(loc="upper left", bbox_to_anchor=(0.0, -0.13), ncol=min(5, len(cells) + (1 if single else 0)))
    fig.tight_layout()
    fig.savefig(path, bbox_inches="tight", pad_inches=0.05)
    plt.close(fig)
    return path


def growth_chart(results: dict[str, Any], path: Path, lang: str) -> Path | None:
    plt = _plt()
    cells = [c for c in ordered_cells(results) if growth_valid(c)][:10]
    if not cells:
        return None
    names = [name_of(results, c, lang) for c in cells]
    vals = [c["metrics"]["yoy"]["value"] for c in cells]
    los = [c["metrics"]["yoy"]["ci"][0] for c in cells]
    his = [c["metrics"]["yoy"]["ci"][1] for c in cells]
    norms = [(c["metrics"].get("yoy_normalized") or {}).get("value") for c in cells]
    height = max(2.2, 0.42 * len(cells) + 1.5)
    fig, ax = plt.subplots(figsize=(4.3, height))
    y = list(range(len(cells)))[::-1]
    colors = [GRADE_COLORS[c["confidence"]["grade"]] for c in cells]
    ax.barh(y, vals, color=colors, alpha=0.8, height=0.55)
    for yi, lo, hi in zip(y, los, his):
        if lo is not None and hi is not None:
            ax.plot([lo, hi], [yi, yi], color="#0f172a", lw=1.1)
            ax.plot([lo, lo], [yi - 0.12, yi + 0.12], color="#0f172a", lw=1.1)
            ax.plot([hi, hi], [yi - 0.12, yi + 0.12], color="#0f172a", lw=1.1)
    ny = [yi for yi, nv in zip(y, norms) if nv is not None]
    nv = [v for v in norms if v is not None]
    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch
    handles = [Patch(color="#94a3b8", label=i18n.label("growth_raw", lang))]
    if nv:
        ax.scatter(nv, ny, marker="D", s=22, color="#0f172a", zorder=5)
        handles.append(Line2D([], [], marker="D", color="#0f172a", lw=0, markersize=5,
                              label=i18n.label("growth_norm", lang)))
    ax.axvline(0, color="#334155", lw=0.8)
    ax.set_yticks(y)
    ax.set_yticklabels(names)
    ax.xaxis.set_major_formatter(_pct_formatter(lang))
    ax.grid(axis="y", visible=False)
    ax.set_title(textwrap.fill(i18n.label("chart_growth", lang), 42), loc="left")
    # fixed space in inches under the axes for the legend and the colour note
    reserve = 0.62
    fig.tight_layout(rect=(0, reserve / height, 1, 1))
    fig.legend(handles=handles, loc="lower left", bbox_to_anchor=(0.01, 0.24 / height), fontsize=6.5, ncol=2,
               frameon=False)
    fig.text(0.015, 0.04 / height, textwrap.fill(i18n.label("color_conf", lang), 80), fontsize=6,
             color="#64748b", va="bottom")
    fig.savefig(path)
    plt.close(fig)
    return path


def opportunity_chart(results: dict[str, Any], path: Path, lang: str) -> Path | None:
    ranking = results.get("ranking")
    if not ranking:
        return None
    by_id_all = {c["id"]: c for c in results["cells"]}
    if sum(1 for row in ranking["rows"] if growth_valid(by_id_all[row["cell"]])) < 3:
        return None
    plt = _plt()
    by_id = {c["id"]: c for c in results["cells"]}
    fig, ax = plt.subplots(figsize=(3.1, 2.7))
    xs, ys = [], []
    placed: list[tuple[float, float]] = []
    for row in ranking["rows"][:12]:
        c = by_id[row["cell"]]
        if not growth_valid(c):
            continue
        mt = c["metrics"]
        xv = max(mt["avg_monthly_last12"], 1.0)
        norm = (mt.get("yoy_normalized") or {}).get("value")
        yv = norm if norm is not None else mt["yoy"]["value"]
        if yv is None:
            continue
        pm = mt.get("per_million_last12") or 1.0
        size = 30 + 120 * min(1.0, math.sqrt(pm) / 10.0)
        ax.scatter([xv], [yv], s=size, color=GRADE_COLORS[c["confidence"]["grade"]], alpha=0.75,
                   edgecolor="#0f172a", linewidth=0.5, zorder=3)
        # nudge labels that would overlap an earlier one (positions in log-x / linear-y space)
        pos = (math.log10(xv), yv)
        dy = 4
        for px, py in placed:
            if abs(px - pos[0]) < 0.25 and abs(py - pos[1]) < 0.04:
                dy -= 9
        placed.append(pos)
        ax.annotate(f"{row['rank']}. {c['label'] if c['label'] == c['lang'] else name_of(results, c, lang)[:18]}",
                    (xv, yv), textcoords="offset points", xytext=(5, dy), fontsize=6.5)
        xs.append(xv)
        ys.append(yv)
    if not xs:
        plt.close(fig)
        return None
    ax.set_xscale("log")
    from matplotlib.ticker import FixedLocator, FuncFormatter, NullFormatter
    lo_x, hi_x = min(xs) / 2.2, max(xs) * 3.5
    nice = [m * 10 ** e for e in range(0, 9) for m in (1, 2, 5) if lo_x <= m * 10 ** e <= hi_x]
    if len(nice) > 5:
        nice = [v for v in nice if str(int(v))[0] in "1"] or nice[::2]
    ax.xaxis.set_major_locator(FixedLocator(nice))
    ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: i18n.fmt_compact(v, lang)))
    ax.xaxis.set_minor_formatter(NullFormatter())
    ax.axhline(0, color="#334155", lw=0.8)
    ax.yaxis.set_major_formatter(_pct_formatter(lang))
    ax.set_xlabel(i18n.label("opp_x", lang), fontsize=7)
    ax.set_ylabel(i18n.label("opp_y", lang), fontsize=7)
    ax.set_title(i18n.label("chart_opp", lang), loc="left")
    pad = (max(ys) - min(ys)) * 0.25 + 0.05
    ax.set_ylim(min(ys) - pad, max(ys) + pad)
    ax.set_xlim(lo_x, hi_x)
    fig.tight_layout()
    fig.savefig(path, bbox_inches="tight", pad_inches=0.05)
    plt.close(fig)
    return path


def make_charts(results: dict[str, Any], outdir: Path, lang: str = "en") -> dict[str, str]:
    lang = i18n.ui(lang)
    outdir.mkdir(parents=True, exist_ok=True)
    made: dict[str, str] = {}
    for name, fn in (("trend", trend_chart), ("growth", growth_chart), ("opportunity", opportunity_chart)):
        path = outdir / f"{name}.png"
        if fn(results, path, lang):
            made[name] = str(path)
        elif path.exists():
            path.unlink()
    return made
