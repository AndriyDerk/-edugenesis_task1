"""Localised wording (English, Ukrainian) and number formatting.

Everything user-facing in reports is generated from codes + data here, so the
same analysis can be rendered in either language without recomputation.
"""

from __future__ import annotations

from typing import Any

from . import langs

SUPPORTED = ("en", "uk")


def ui(lang: str | None) -> str:
    return lang if lang in SUPPORTED else "en"


# ----------------------------------------------------------------- number format
def fmt_num(x: float | int | None, lang: str = "en", nd: int = 0) -> str:
    if x is None:
        return "n/a" if lang == "en" else "н/д"
    s = f"{x:,.{nd}f}"
    if lang == "uk":
        s = s.replace(",", " ").replace(".", ",")
    return s


def fmt_compact(x: float | int | None, lang: str = "en") -> str:
    if x is None:
        return "n/a" if lang == "en" else "н/д"
    ax = abs(x)
    if ax >= 1e6:
        s, suf = f"{x / 1e6:.1f}", ("M" if lang == "en" else " млн")
    elif ax >= 1e4:
        s, suf = f"{x / 1e3:.0f}", ("k" if lang == "en" else " тис.")
    elif ax >= 1e3:
        s, suf = f"{x / 1e3:.1f}", ("k" if lang == "en" else " тис.")
    else:
        s, suf = f"{x:.0f}", ""
    if lang == "uk":
        s = s.replace(".", ",")
    return s + suf


def fmt_pct(x: float | None, lang: str = "en", signed: bool = True, nd: int = 1) -> str:
    if x is None:
        return "n/a" if lang == "en" else "н/д"
    v = x * 100
    s = f"{v:+.{nd}f}%" if signed else f"{v:.{nd}f}%"
    if lang == "uk":
        s = s.replace(".", ",").replace("-", "−")
    return s


def fmt_pp(x: float | None, lang: str = "en") -> str:
    """x already in percentage points."""
    if x is None:
        return "n/a" if lang == "en" else "н/д"
    s = f"{x:+.1f}"
    if lang == "uk":
        s = s.replace(".", ",").replace("-", "−")
    return s


def fmt_p(p: float | None, lang: str = "en") -> str:
    if p is None:
        return "n/a"
    s = "<0.001" if p < 0.001 else f"{p:.3f}" if p < 0.1 else f"{p:.2f}"
    return s.replace(".", ",") if lang == "uk" else s


def fmt_month(month: str, lang: str = "en") -> str:
    year, mm = month.split("-")[:2]
    names = MONTHS[ui(lang)]
    return f"{names[int(mm) - 1]} {year}"


MONTHS = {
    "en": ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
    "uk": ["січ.", "лют.", "бер.", "квіт.", "трав.", "черв.", "лип.", "серп.", "вер.", "жовт.", "лист.", "груд."],
}


# ---------------------------------------------------------------------- words
DIRECTION = {
    "en": {"growing": "growing", "likely growing": "likely growing", "stable": "stable",
           "likely declining": "likely declining", "declining": "declining",
           "inconclusive": "no clear trend", "no-baseline": "no baseline", "new-article": "new article"},
    "uk": {"growing": "зростає", "likely growing": "імовірно зростає", "stable": "стабільно",
           "likely declining": "імовірно спадає", "declining": "спадає",
           "inconclusive": "без чіткого тренду", "no-baseline": "немає бази порівняння",
           "new-article": "нова стаття"},
}
GRADE = {"en": {"HIGH": "HIGH", "MEDIUM": "MEDIUM", "LOW": "LOW"},
         "uk": {"HIGH": "ВИСОКА", "MEDIUM": "СЕРЕДНЯ", "LOW": "НИЗЬКА"}}
SPIKE_KIND = {"en": {"bot-like": "bot-like", "event-like": "news/event-like", "unknown": "cause unknown"},
              "uk": {"bot-like": "схоже на ботів", "event-like": "схоже на новинну подію",
                     "unknown": "причина невідома"}}
PRESET = {"en": {"balanced": "balanced", "growth-first": "growth-first", "size-first": "size-first",
                 "niche-first": "niche-first"},
          "uk": {"balanced": "збалансована", "growth-first": "пріоритет зростання",
                 "size-first": "пріоритет розміру", "niche-first": "пріоритет ніші"}}
COMPONENT = {"en": {"reach": "audience size", "momentum": "growth", "intensity": "topic salience",
                    "confidence": "data reliability"},
             "uk": {"reach": "розмір аудиторії", "momentum": "зростання", "intensity": "вагомість теми",
                    "confidence": "надійність даних"}}


def direction(code: str, lang: str = "en") -> str:
    return DIRECTION[ui(lang)].get(code, code)


def grade(code: str, lang: str = "en") -> str:
    return GRADE[ui(lang)].get(code, code)


# ------------------------------------------------------------- reasons / flags
REASONS = {
    "en": {
        "very_low_volume": "very low volume ({per_day} views/day): noise dominates",
        "low_volume": "low volume ({per_day} views/day)",
        "modest_volume": "modest volume ({per_day} views/day)",
        "volume": "solid volume ({per_day} views/day)",
        "consistent": "{agree}/12 months moved the same way; 90% CI {lo}..{hi} excludes 0",
        "stable": "change is small and well-bounded (90% CI {lo}..{hi})",
        "partial_support": "only partly supported: {agree}/12 months agree, 90% CI {lo}..{hi}",
        "no_baseline": "no views in the comparison year: growth cannot be measured",
        "inconclusive": "direction unclear: {agree}/12 months agree, 90% CI {lo}..{hi}",
        "wide_ci": "wide uncertainty band ({width} pp)",
        "spike_driven": "spikes distort growth: raw {raw} vs {clean} without spikes",
        "spiky": "{share} of views came from short spikes",
        "bot_traffic": "bot-like desktop bursts ({share} of views) were removed",
        "no_wiki_baseline": "wiki-wide traffic unavailable: cannot separate topic interest from overall traffic",
        "baseline_divergence": "all of {wiki} changed {project}; relative to it the topic moved {norm}",
        "platform_divergence": "desktop ({desktop}) and mobile ({mobile}) disagree",
        "platforms_agree": "desktop ({desktop}) and mobile ({mobile}) agree",
        "late_start": "article had no views until {date} (created or renamed mid-window): early growth is an artefact",
        "dropped_to_zero": "views stop after {date} (deleted or renamed without redirect?)",
        "level_shift": "abrupt x{ratio} level change around {month} (rename/merge, main-page feature or tracking change?)",
        "incomplete_basket": "no article here for: {items}",
        "redirects_truncated": "some redirects were not counted (too many)",
        "fetch_errors": "{n} series failed to download",
        "new_item": "basket article '{title}' only appeared on {date} and makes up {share} of recent views: growth is inflated",
    },
    "uk": {
        "very_low_volume": "дуже малий обсяг ({per_day} перегл./день): домінує випадковий шум",
        "low_volume": "малий обсяг ({per_day} перегл./день)",
        "modest_volume": "помірний обсяг ({per_day} перегл./день)",
        "volume": "достатній обсяг ({per_day} перегл./день)",
        "consistent": "{agree} з 12 місяців змінились в одному напрямку; 90% ДІ {lo}…{hi} не містить 0",
        "stable": "зміна мала й добре обмежена (90% ДІ {lo}…{hi})",
        "partial_support": "підтверджено лише частково: {agree} з 12 місяців, 90% ДІ {lo}…{hi}",
        "no_baseline": "немає переглядів у базовому році: зростання не виміряти",
        "inconclusive": "напрям неясний: {agree} з 12 місяців, 90% ДІ {lo}…{hi}",
        "wide_ci": "широкий інтервал невизначеності ({width} п.п.)",
        "spike_driven": "сплески спотворюють динаміку: {raw} із ними проти {clean} без них",
        "spiky": "{share} переглядів припадає на короткі сплески",
        "bot_traffic": "вилучено схожі на ботів десктопні сплески ({share} переглядів)",
        "no_wiki_baseline": "немає даних про весь трафік вікі: не можна відділити інтерес до теми від загальної динаміки",
        "baseline_divergence": "уся {wiki} змінилась на {project}; відносно неї тема — {norm}",
        "platform_divergence": "десктоп ({desktop}) і мобільні ({mobile}) розходяться",
        "platforms_agree": "десктоп ({desktop}) і мобільні ({mobile}) узгоджуються",
        "late_start": "стаття не мала переглядів до {date} (створена чи перейменована в межах періоду): зростання — артефакт",
        "dropped_to_zero": "перегляди зникають після {date} (видалена чи перейменована без перенаправлення?)",
        "level_shift": "різка зміна рівня ×{ratio} близько {month} (перейменування, головна сторінка чи зміна обліку?)",
        "incomplete_basket": "немає статей для: {items}",
        "redirects_truncated": "частину перенаправлень не враховано (їх забагато)",
        "fetch_errors": "не вдалося завантажити рядів: {n}",
        "new_item": "стаття кошика «{title}» з’явилась лише {date} і дає {share} недавніх переглядів: зростання завищене",
    },
}

PCT_FIELDS = {"lo", "hi", "raw", "clean", "share", "project", "norm", "desktop", "mobile"}


def reason(code: str, data: dict[str, Any] | None, lang: str = "en") -> str:
    lang = ui(lang)
    template = REASONS[lang].get(code)
    if template is None:
        return code
    data = dict(data or {})
    fmt: dict[str, Any] = {}
    for k, v in data.items():
        if k in PCT_FIELDS:
            fmt[k] = fmt_pct(v, lang, signed=k not in ("share",), nd=0 if k == "share" else 1)
        elif k == "per_day":
            fmt[k] = fmt_num(v, lang, 1 if v < 10 else 0)
        elif k == "width":
            fmt[k] = fmt_num(v, lang)
        elif k == "ratio":
            fmt[k] = fmt_num(v, lang, 1)
        elif k == "items":
            fmt[k] = ", ".join(v)
        elif k == "wiki_lang":
            fmt["wiki"] = f"{v}.wikipedia"
        else:
            fmt[k] = v
    try:
        return template.format(**fmt)
    except (KeyError, IndexError):
        return template


# --------------------------------------------------------------- display names
def cell_name(cell: dict[str, Any], lang: str = "en", topic_labels: dict[str, str] | None = None) -> str:
    lang = ui(lang)
    topic = (topic_labels or {}).get(cell["topic_id"], cell["topic"])
    if cell["label"] == cell["lang"]:
        return langs.label(cell["lang"], lang)
    if cell["label"] == cell["topic"]:
        return topic
    return f"{topic} · {langs.name(cell['lang'], lang)}"


TEXT = {
    "en": {
        "headline": "{name} — {direction}: {yoy} year over year without spikes (90% CI {lo}…{hi}; "
                    "{agree}/12 months {updown}), ≈{avg} views/month; confidence {grade}.",
        "headline_na": "{name} — cannot be measured: {reason}.",
        "headline_new": "{name} — new article (first views {date}): year-over-year growth is not meaningful yet; "
                        "≈{avg} views/month recently; confidence {grade}.",
        "up": "higher", "down": "lower",
        "normalized": "Relative to all traffic of {wiki} ({project} YoY), interest in {name} changed {norm}.",
        "compare": "{a} vs {b}: growth differs by {diff} pp (90% CI {lo}…{hi}) → {verdict}.",
        "faster": "{x} grew faster", "no_difference": "no clear difference",
        "not_comparable": "not comparable",
        "ranking": "Most promising {dimension}: {label} (score {score}/100){stability}.",
        "rank_stable": "; it wins under all {n} weighting schemes",
        "rank_unstable": "; the winner depends on priorities ({alts})",
        "dimension": {"language": "language", "topic": "topic", "topic x language": "option"},
        "spike": "Largest spike: {date} in {name} (x{ratio} of normal, {kind}); excluded from the trend.",
        "accelerating": "accelerating", "slowing": "slowing",
        "momentum": "Momentum in {name} is {accel}: last 3 months {last3} YoY vs {yoy} over 12 months.",
        "longrun": "Long-run trend for {name} over {n} months: {sen}/year (seasonal Kendall p={p}).",
        "missing": "{name}: no article exists, so this language cannot be measured for the topic.",
        "geo": "Readers of {wiki} are mostly in: {countries}.",
    },
    "uk": {
        "headline": "{name} — {direction}: {yoy} рік до року без сплесків (90% ДІ {lo}…{hi}; "
                    "{agree} з 12 міс. {updown}, ніж роком раніше), ≈{avg} перегл./міс.; довіра {grade}.",
        "headline_na": "{name} — виміряти неможливо: {reason}.",
        "headline_new": "{name} — нова стаття (перші перегляди {date}): порівняння рік до року ще неможливе; "
                        "≈{avg} перегл./міс. останнім часом; довіра {grade}.",
        "up": "вище", "down": "нижче",
        "normalized": "Відносно всього трафіку {wiki} ({project} р/р) інтерес до «{name}» змінився на {norm}.",
        "compare": "{a} проти {b}: різниця зростання {diff} п.п. (90% ДІ {lo}…{hi}) → {verdict}.",
        "faster": "{x} зростає швидше", "no_difference": "чіткої різниці немає",
        "not_comparable": "непорівнювано",
        "ranking": "Найперспективніший варіант ({dimension}): {label} (бал {score}/100){stability}.",
        "rank_stable": "; перемагає за всіх {n} схем ваг",
        "rank_unstable": "; переможець залежить від пріоритетів ({alts})",
        "dimension": {"language": "мова", "topic": "тема", "topic x language": "тема × мова"},
        "spike": "Найбільший сплеск: {date}, {name} (×{ratio} від норми, {kind}); виключено з тренду.",
        "accelerating": "прискорюється", "slowing": "сповільнюється",
        "momentum": "Динаміка «{name}» {accel}: останні 3 міс. {last3} р/р проти {yoy} за 12 міс.",
        "longrun": "Довгостроковий тренд «{name}» за {n} міс.: {sen}/рік (сезонний тест Кендалла p={p}).",
        "missing": "{name}: статті немає, тож цю мову для теми виміряти неможливо.",
        "geo": "Читачі {wiki} переважно з: {countries}.",
    },
}


def text(key: str, lang: str = "en", **kw: Any) -> str:
    return TEXT[ui(lang)][key].format(**kw)


LIMITATIONS = {
    "en": [
        "Pageviews measure curiosity, not willingness to pay: use them to choose what to validate next, not as demand.",
        "A language edition is not a country: many people read another language's Wikipedia (often English), "
        "and one language can span many countries.",
        "Human traffic (agent=user) still contains some undetected bots; short spikes are replaced by a rolling "
        "median before trends are computed.",
        "Overall Wikipedia traffic is shifting (AI answers, search changes, 2025 bot reclassification), so growth is "
        "also shown relative to all views of the same language edition.",
    ],
    "uk": [
        "Перегляди відображають цікавість, а не готовність платити: це сигнал, що перевіряти далі, а не попит.",
        "Мовний розділ — не країна: багато людей читають Вікіпедію іншою мовою (часто англійською), "
        "а однією мовою можуть говорити в багатьох країнах.",
        "Людський трафік (agent=user) усе ще містить частину непомічених ботів; короткі сплески замінено "
        "ковзною медіаною до розрахунку трендів.",
        "Загальний трафік Вікіпедії змінюється (ШІ-відповіді, пошук, перекласифікація ботів у 2025 р.), тому "
        "зростання показано й відносно всіх переглядів того самого мовного розділу.",
    ],
}

METHOD = {
    "en": "Method: Wikimedia Pageviews API, human views (agent=user), article + redirects summed; growth = last 12 "
          "months vs previous 12 (same calendar months) after spike removal; 90% CI = paired month bootstrap; "
          "trend test = seasonal Mann-Kendall; confidence = explainable rule score (volume, consistency, spikes, "
          "platform agreement, data artefacts).",
    "uk": "Метод: Wikimedia Pageviews API, людські перегляди (agent=user), стаття + перенаправлення; зростання = "
          "останні 12 міс. проти попередніх 12 (ті самі календарні місяці) після вилучення сплесків; 90% ДІ = "
          "парний бутстреп місяців; тест тренду = сезонний Манна–Кендалла; довіра = прозора бальна оцінка "
          "(обсяг, узгодженість, сплески, платформи, артефакти даних).",
}

LABELS = {
    "en": {
        "key_findings": "Key findings", "summary": "Summary", "recommendation": "Recommendation & next steps",
        "limitations": "Method & limitations", "table_lang": "Option", "table_avg": "Views / month",
        "table_yoy": "YoY w/o spikes (90% CI)", "table_norm": "vs wiki", "table_dir": "Trend",
        "table_conf": "Confidence", "table_score": "Score", "generated": "Generated", "period": "Period",
        "source": "Data: Wikimedia Pageviews API", "human": "human views",
        "chart_trend_idx": "Monthly views, index (first 12 months = 100), spikes removed",
        "chart_trend_abs": "Monthly views (spikes removed; dashed = raw)",
        "chart_growth": "Growth, last 12 vs previous 12 months",
        "growth_raw": "without spikes (90% CI)", "growth_norm": "relative to whole wiki",
        "chart_opp": "Opportunity map", "opp_x": "Avg monthly views (log)", "opp_y": "Growth vs whole wiki",
        "period_prev": "previous 12 mo", "period_last": "last 12 mo",
        "color_conf": "bar colour = confidence: green high, amber medium, red low",
        "questions": "Question", "caveats": "Caveats", "auto_next": [
            "Validate the top option with a cheap demand test (landing page, ads, waitlist) before building.",
            "Check search-engine and app-store keyword volumes for the same topic and languages.",
            "Re-run in 3 months to confirm the trend; add related articles to the basket for robustness.",
        ],
    },
    "uk": {
        "key_findings": "Ключові висновки", "summary": "Підсумок", "recommendation": "Рекомендація та наступні кроки",
        "limitations": "Метод і обмеження", "table_lang": "Варіант", "table_avg": "Перегл./міс.",
        "table_yoy": "Р/р без сплесків (90% ДІ)", "table_norm": "відн. вікі", "table_dir": "Тренд",
        "table_conf": "Довіра", "table_score": "Бал", "generated": "Згенеровано", "period": "Період",
        "source": "Дані: Wikimedia Pageviews API", "human": "людські перегляди",
        "chart_trend_idx": "Перегляди за місяць, індекс (перші 12 міс. = 100), без сплесків",
        "chart_trend_abs": "Перегляди за місяць (без сплесків; пунктир — сирі)",
        "chart_growth": "Зростання: останні 12 міс. проти попередніх 12",
        "growth_raw": "без сплесків (90% ДІ)", "growth_norm": "відносно всієї вікі",
        "period_prev": "попередні 12 міс.", "period_last": "останні 12 міс.",
        "color_conf": "колір стовпця = довіра: зелений висока, жовтий середня, червоний низька",
        "chart_opp": "Карта можливостей", "opp_x": "Середні перегляди/міс. (лог.)",
        "opp_y": "Зростання відносно вікі",
        "questions": "Питання", "caveats": "Застереження", "auto_next": [
            "Перевірте найкращий варіант дешевим тестом попиту (лендинг, реклама, лист очікування) до розробки.",
            "Порівняйте з обсягами пошукових запитів і ключових слів у магазинах застосунків для тих самих мов.",
            "Повторіть аналіз через 3 місяці; додайте споріднені статті до кошика для надійності.",
        ],
    },
}


def label(key: str, lang: str = "en") -> Any:
    return LABELS[ui(lang)][key]


_NOTE_PATTERNS = [
    (r"no article titled '(?P<q>.+)' on (?P<w>[\w-]+\.wikipedia); picked top search result '(?P<t>.+)' - check the alternatives",
     "на {w} немає статті «{q}»; обрано перший результат пошуку «{t}» — перевірте альтернативи"),
    (r"'(?P<q>.+)' is ambiguous on (?P<w>[\w-]+\.wikipedia) \(disambiguation page\); picked '(?P<t>.+)' - check the alternatives",
     "«{q}» — неоднозначна назва на {w}; обрано «{t}» — перевірте альтернативи"),
    (r"period extended from (?P<a>\d+) to (?P<b>\d+) months \((?P<r>[^)]+)\).*",
     "період розширено з {a} до {b} міс. ({r}), щоб порівняти останні 12 місяців із попередніми 12"),
    (r"'(?P<t>.+)' in (?P<l>[\w-]+): missing article\(s\) for (?P<i>.+) - basket is not fully comparable across languages",
     "«{t}» ({l}): немає статей для {i} — кошик не повністю порівнюваний між мовами"),
]


def note(text_: str, lang: str = "en") -> str:
    """Translate the English free-text notes produced by the resolver/period logic."""
    if ui(lang) != "uk":
        return text_
    import re
    for pattern, template in _NOTE_PATTERNS:
        m = re.fullmatch(pattern, text_)
        if m:
            return template.format(**m.groupdict())
    return text_
