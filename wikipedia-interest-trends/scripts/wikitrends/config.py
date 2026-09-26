"""Paths, endpoints and tunables. Everything is read at call time so tests and
users can override behaviour with environment variables."""

from __future__ import annotations

import datetime as dt
import os
from pathlib import Path

from . import __version__

PACKAGE_DIR = Path(__file__).resolve().parent
SKILL_ROOT = PACKAGE_DIR.parent.parent
ASSETS_DIR = SKILL_ROOT / "assets"
PROJECT_URL = "https://github.com/AndriyDerk/-edugenesis_task1"

# First day with per-article pageview data (agent-type split) in the API.
PAGEVIEWS_START = dt.date(2015, 7, 1)
# Daily data is published with a lag; newer days are refetched on later runs.
DATA_LAG_DAYS = 3


def _env(name: str, default: str) -> str:
    value = os.environ.get(name, "").strip()
    return value or default


def home_dir() -> Path:
    """Directory for the SQLite cache and the dependency venv."""
    explicit = os.environ.get("WIKITRENDS_HOME")
    if explicit:
        return Path(explicit).expanduser()
    xdg = os.environ.get("XDG_CACHE_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".cache"
    return base / "wikitrends"


def cache_path() -> Path:
    return home_dir() / "cache.sqlite"


def user_agent() -> str:
    """Wikimedia's User-Agent policy requires a tool name and contact info;
    clients without it are throttled to a few requests per minute."""
    contact = os.environ.get("WIKITRENDS_CONTACT", "").strip()
    extra = f"; {contact}" if contact else ""
    return f"wikipedia-interest-trends/{__version__} (+{PROJECT_URL}{extra}) python-urllib"


def rest_base() -> str:
    return _env("WIKITRENDS_REST_BASE", "https://wikimedia.org/api/rest_v1").rstrip("/")


def wiki_api(lang: str) -> str:
    template = _env("WIKITRENDS_WIKI_API", "https://{lang}.wikipedia.org/w/api.php")
    return template.replace("{lang}", lang)


def wikidata_api() -> str:
    return _env("WIKITRENDS_WIKIDATA_API", "https://www.wikidata.org/w/api.php")


def max_rps() -> float:
    """Requests per second across all Wikimedia hosts. The 2026 global limit for
    an identified client is ~200 requests/minute; stay comfortably below."""
    try:
        return max(0.1, float(_env("WIKITRENDS_MAX_RPS", "2.5")))
    except ValueError:
        return 2.5


def workers() -> int:
    try:
        return max(1, int(_env("WIKITRENDS_WORKERS", "4")))
    except ValueError:
        return 4


def offline() -> bool:
    return os.environ.get("WIKITRENDS_OFFLINE", "") not in ("", "0", "false", "no")


def today() -> dt.date:
    """Overridable 'today' (WIKITRENDS_TODAY=YYYY-MM-DD) for reproducible runs."""
    raw = os.environ.get("WIKITRENDS_TODAY", "").strip()
    if raw:
        return dt.date.fromisoformat(raw)
    return dt.date.today()


def stable_until() -> dt.date:
    """Data up to this day is considered final and cached permanently."""
    return today() - dt.timedelta(days=DATA_LAG_DAYS)
