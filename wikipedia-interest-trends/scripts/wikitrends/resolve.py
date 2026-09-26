"""Turn user topics into concrete Wikipedia articles in every target language.

A *topic* is a basket of one or more *items*. Each item is given as

* a Wikidata id (``Q1368167``),
* a specific article (``en:Intermittent fasting``, ``uk:Астрономія``), or
* free text, searched on ``search_lang`` Wikipedia (``intermittent fasting``).

Items are mapped to other languages through Wikidata sitelinks, never by
translating titles, so the same concept is compared across languages.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from . import langs
from .wiki import Wiki

QID_RE = re.compile(r"^[Qq][1-9]\d*$")
WIKI_RE = re.compile(r"^([a-z]{2,3}(?:-[a-z0-9]{2,8})*|simple):\s*(.+)$")


class ResolveError(ValueError):
    pass


@dataclass
class TopicSpec:
    label: str | None
    items: list[str]


@dataclass
class ItemSpec:
    raw: str
    kind: str  # "qid" | "title" | "query"
    value: str
    lang: str | None = None


def parse_item(raw: str) -> ItemSpec:
    text = raw.strip()
    if not text:
        raise ResolveError("empty topic item")
    if QID_RE.match(text):
        return ItemSpec(text, "qid", text.upper())
    m = WIKI_RE.match(text)
    if m:
        try:
            code, _ = langs.normalize(m.group(1))
            return ItemSpec(text, "title", m.group(2).strip(), code)
        except langs.LangError:
            pass
    return ItemSpec(text, "query", text)


def _norm(s: str) -> str:
    return re.sub(r"[\W_]+", " ", s.casefold()).strip()


@dataclass
class _Picked:
    qid: str | None
    title: str | None
    title_lang: str | None
    description: str = ""
    method: str = ""
    alternatives: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _resolve_query(wiki: Wiki, lang: str, query: str) -> _Picked:
    info = wiki.page_info(lang, [query])[query]
    candidates = wiki.search(lang, query)
    usable = [c for c in candidates if c.get("qid") and not c.get("disambiguation")]
    picked: _Picked | None = None
    if info["exists"] and not info["disambiguation"] and info.get("qid"):
        picked = _Picked(info["qid"], info["title"], lang, info.get("description", ""), "exact title")
    elif usable:
        top = usable[0]
        picked = _Picked(top["qid"], top["title"], lang, top.get("description", ""), "top search result")
        if info["exists"] and info["disambiguation"]:
            picked.warnings.append(
                f"'{query}' is ambiguous on {lang}.wikipedia (disambiguation page); picked "
                f"'{top['title']}' - check the alternatives"
            )
        elif _norm(top["title"]) != _norm(query):
            picked.warnings.append(
                f"no article titled '{query}' on {lang}.wikipedia; picked top search result "
                f"'{top['title']}' - check the alternatives"
            )
    if picked is None:
        raise ResolveError(
            f"nothing found for '{query}' on {lang}.wikipedia. Try an English name, another "
            f"--search-lang, an explicit article like '{lang}:Title', or a Wikidata id (Q...)"
        )
    picked.alternatives = [
        {"title": c["title"], "qid": c["qid"], "description": c.get("description", "")}
        for c in usable if c["qid"] != picked.qid
    ][:4]
    return picked


def _resolve_item(wiki: Wiki, spec: ItemSpec, search_lang: str) -> _Picked:
    if spec.kind == "qid":
        return _Picked(spec.value, None, None, method="wikidata id")
    if spec.kind == "title":
        info = wiki.page_info(spec.lang, [spec.value])[spec.value]
        if not info["exists"]:
            picked = _resolve_query(wiki, spec.lang, spec.value)
            picked.warnings.insert(0, f"article '{spec.lang}:{spec.value}' does not exist; searched instead")
            return picked
        picked = _Picked(info.get("qid"), info["title"], spec.lang, info.get("description", ""), "explicit article")
        if info["disambiguation"]:
            picked.warnings.append(f"'{spec.lang}:{info['title']}' is a disambiguation page - pick a specific article")
        if not info.get("qid"):
            picked.warnings.append(
                f"'{spec.lang}:{info['title']}' has no Wikidata item, so it can only be analysed in '{spec.lang}'"
            )
        return picked
    return _resolve_query(wiki, search_lang, spec.value)


def resolve_topics(
    wiki: Wiki,
    topics: list[TopicSpec],
    target_langs: list[str],
    search_lang: str = "en",
    include_redirects: bool = True,
    max_redirects: int = 10,
    ui_lang: str = "en",
) -> dict[str, Any]:
    if not topics:
        raise ResolveError("no topics given")
    warnings: list[str] = []
    resolved_topics: list[dict[str, Any]] = []
    all_qids: list[str] = []

    for t_index, topic in enumerate(topics, start=1):
        items = []
        for raw in topic.items:
            spec = parse_item(raw)
            try:
                picked = _resolve_item(wiki, spec, search_lang)
            except ResolveError as exc:
                warnings.append(str(exc))
                continue
            items.append({
                "spec": raw,
                "qid": picked.qid,
                "title": picked.title,
                "title_lang": picked.title_lang,
                "description": picked.description,
                "method": picked.method,
                "alternatives": picked.alternatives,
                "warnings": picked.warnings,
            })
            warnings.extend(picked.warnings)
            if picked.qid:
                all_qids.append(picked.qid)
        if not items:
            warnings.append(f"topic '{topic.label or ', '.join(topic.items)}' could not be resolved and was skipped")
            continue
        resolved_topics.append({"id": f"t{t_index}", "label": topic.label, "items": items})

    if not resolved_topics:
        raise ResolveError("none of the topics could be resolved:\n  " + "\n  ".join(warnings))

    label_langs = sorted(set(target_langs + [ui_lang, search_lang, "en", "uk"]))
    entities = wiki.entities(all_qids, label_langs=label_langs) if all_qids else {}

    # Fill labels / sitelinks, then collect per-language titles.
    wanted: dict[str, list[str]] = {lang: [] for lang in target_langs}
    for topic in resolved_topics:
        for item in topic["items"]:
            ent = entities.get(item["qid"] or "", {})
            if item["qid"] and ent.get("missing"):
                msg = f"Wikidata item {item['qid']} does not exist"
                item["warnings"].append(msg)
                warnings.append(msg)
            labels = ent.get("labels", {})
            item["label"] = labels.get("en") or item.get("title") or item["qid"] or item["spec"]
            item["labels"] = {code: labels.get(code) or item["label"] for code in ("en", "uk")}
            if not item["description"]:
                item["description"] = ent.get("descriptions", {}).get("en", "")
            sitelinks = dict(ent.get("sitelinks", {}))
            if item.get("title") and item.get("title_lang"):
                sitelinks.setdefault(item["title_lang"], item["title"])
            item["sitelinks"] = {lang: sitelinks[lang] for lang in target_langs if lang in sitelinks}
            for lang, title in item["sitelinks"].items():
                wanted[lang].append(title)
        if not topic["label"]:
            first = topic["items"][0]
            topic["label"] = _cap(first["label"])
            topic["labels"] = {code: _cap(v) for code, v in first["labels"].items()}
        else:
            topic["labels"] = {"en": topic["label"], "uk": topic["label"]}

    page_infos: dict[str, dict[str, dict[str, Any]]] = {}
    for lang, titles in wanted.items():
        if titles:
            page_infos[lang] = wiki.page_info(lang, titles, max_redirects=max_redirects)

    for topic in resolved_topics:
        cells: dict[str, Any] = {}
        for lang in target_langs:
            articles: list[dict[str, Any]] = []
            missing: list[str] = []
            seen: set[str] = set()
            for item in topic["items"]:
                title = item["sitelinks"].get(lang)
                if not title:
                    missing.append(item["label"])
                    continue
                info = page_infos.get(lang, {}).get(title, {"title": title, "exists": True, "redirects": []})
                if not info.get("exists", True):
                    missing.append(item["label"])
                    continue
                canonical = info["title"]
                if canonical in seen:
                    continue
                seen.add(canonical)
                redirects = [r for r in info.get("redirects", []) if r not in seen] if include_redirects else []
                seen.update(redirects)
                articles.append({
                    "qid": item["qid"],
                    "item": item["label"],
                    "title": canonical,
                    "redirects": redirects,
                    "redirects_total": info.get("redirects_total", len(redirects)) if include_redirects else 0,
                    "redirects_truncated": bool(info.get("redirects_truncated")) and include_redirects,
                })
            cells[lang] = {"articles": articles, "missing": missing}
        topic["cells"] = cells
        for lang, cell in cells.items():
            if not cell["articles"]:
                warnings.append(f"'{topic['label']}': no {langs.name(lang)} ({lang}) article exists for any item")
            elif cell["missing"]:
                warnings.append(
                    f"'{topic['label']}' in {lang}: missing article(s) for {', '.join(cell['missing'])} - "
                    f"basket is not fully comparable across languages"
                )

    return {
        "search_lang": search_lang,
        "langs": target_langs,
        "include_redirects": include_redirects,
        "max_redirects": max_redirects,
        "topics": resolved_topics,
        "warnings": list(dict.fromkeys(warnings)),
    }


def _cap(s: str) -> str:
    return s[:1].upper() + s[1:] if s else s


def parse_topics(topic_args: list[str] | None, basket_args: list[list[str]] | None) -> list[TopicSpec]:
    """CLI helper: ``--topic X`` (one item) and ``--basket NAME ITEM [ITEM...]``."""
    specs: list[TopicSpec] = []
    for t in topic_args or []:
        specs.append(TopicSpec(label=None, items=[t]))
    for b in basket_args or []:
        if len(b) < 2:
            raise ResolveError("--basket needs a name and at least one item: --basket \"Name\" Q123 en:Title")
        specs.append(TopicSpec(label=b[0], items=b[1:]))
    return specs
