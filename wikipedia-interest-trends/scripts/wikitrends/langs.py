"""Wikipedia language codes: validation, common-mistake aliases, display names,
and mapping to API identifiers (project, Wikidata site id)."""

from __future__ import annotations

import json
import re
from functools import lru_cache

from .config import ASSETS_DIR

CODE_RE = re.compile(r"^[a-z]{2,3}(-[a-z0-9]{2,8})*$|^simple$")

# Wikidata site ids that do not follow the "<code with _>wiki" rule.
SPECIAL_SITES = {"be-tarask": "be_x_oldwiki"}


class LangError(ValueError):
    pass


@lru_cache(maxsize=1)
def _table() -> dict:
    data = json.loads((ASSETS_DIR / "languages.json").read_text(encoding="utf-8"))
    by_code = {row["code"]: row for row in data["languages"]}
    return {"by_code": by_code, "aliases": data.get("aliases", {})}


def known_codes() -> list[str]:
    return list(_table()["by_code"].keys())


def normalize(code: str) -> tuple[str, str | None]:
    """Return (canonical_code, note). Raises LangError for malformed codes."""
    raw = code.strip().lower().replace("_", "-")
    if raw.endswith(".wikipedia.org"):
        raw = raw[: -len(".wikipedia.org")]
    elif raw.endswith(".wikipedia"):
        raw = raw[: -len(".wikipedia")]
    elif raw.endswith("wiki") and raw[:-4] in _table()["by_code"]:
        raw = raw[:-4]
    table = _table()
    if raw in table["aliases"]:
        target = table["aliases"][raw]
        return target, f"interpreted '{code}' as '{target}' ({name(target)})"
    if not CODE_RE.match(raw):
        raise LangError(f"'{code}' is not a Wikipedia language code (examples: en, uk, pl, cs, de)")
    note = None
    if raw not in table["by_code"]:
        note = f"'{raw}' is not in the built-in language list; using {raw}.wikipedia.org as given"
    return raw, note


def parse_list(value: str | list[str]) -> tuple[list[str], list[str]]:
    """Parse 'pl,cs uk' (or a list) into unique canonical codes plus notes."""
    items = value if isinstance(value, list) else [value]
    codes: list[str] = []
    notes: list[str] = []
    for item in items:
        for part in re.split(r"[,\s;]+", item):
            if not part:
                continue
            code, note = normalize(part)
            if note:
                notes.append(note)
            if code not in codes:
                codes.append(code)
    return codes, notes


def name(code: str, ui: str = "en") -> str:
    row = _table()["by_code"].get(code)
    if not row:
        return code
    return row.get(ui) or row["en"]


def label(code: str, ui: str = "en") -> str:
    """'Polish (pl)' / 'польська (pl)'."""
    return f"{name(code, ui)} ({code})"


def project(code: str) -> str:
    """Pageviews API project id, e.g. 'pl.wikipedia'."""
    return f"{code}.wikipedia"


def site(code: str) -> str:
    """Wikidata sitelink id, e.g. 'plwiki', 'zh_yuewiki'."""
    return SPECIAL_SITES.get(code, code.replace("-", "_") + "wiki")


def code_from_site(site_id: str) -> str | None:
    for code, sid in SPECIAL_SITES.items():
        if sid == site_id:
            return code
    if not site_id.endswith("wiki") or site_id in ("commonswiki", "specieswiki", "metawiki", "wikidatawiki"):
        return None
    return site_id[:-4].replace("_", "-")
