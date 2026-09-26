"""SQLite cache.

Two stores:

* ``views`` + ``coverage``: time series points and the date ranges already
  fetched for each series. Past pageviews never change, so covered ranges are
  cached forever; only days newer than ``config.stable_until()`` are refetched.
  A follow-up request with a longer period or an extra language therefore only
  downloads the missing pieces.
* ``kv``: JSON metadata (search results, redirects, Wikidata sitelinks) with a TTL.
"""

from __future__ import annotations

import datetime as dt
import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Callable, Iterable

Date = dt.date

SCHEMA = """
CREATE TABLE IF NOT EXISTS views (
    skey TEXT NOT NULL,
    day TEXT NOT NULL,
    views INTEGER NOT NULL,
    PRIMARY KEY (skey, day)
);
CREATE TABLE IF NOT EXISTS coverage (
    skey TEXT NOT NULL,
    start TEXT NOT NULL,
    end TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS coverage_skey ON coverage(skey);
CREATE TABLE IF NOT EXISTS kv (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    expires REAL
);
"""


def next_day(d: Date) -> Date:
    return d + dt.timedelta(days=1)


def next_month(d: Date) -> Date:
    return Date(d.year + (d.month == 12), d.month % 12 + 1, 1)


def subtract_ranges(
    start: Date, end: Date, covered: Iterable[tuple[Date, Date]], step: Callable[[Date], Date]
) -> list[tuple[Date, Date]]:
    """Parts of [start, end] (inclusive) not covered by the given intervals."""
    missing: list[tuple[Date, Date]] = []
    cursor = start
    for c_start, c_end in sorted(covered):
        if c_end < cursor:
            continue
        if c_start > end:
            break
        if c_start > cursor:
            gap_end = min(end, _prev(c_start, step))
            if gap_end >= cursor:
                missing.append((cursor, gap_end))
        cursor = max(cursor, step(c_end))
        if cursor > end:
            break
    if cursor <= end:
        missing.append((cursor, end))
    return missing


def _prev(d: Date, step: Callable[[Date], Date]) -> Date:
    if step is next_month:
        return Date(d.year - (d.month == 1), (d.month - 2) % 12 + 1, 1)
    return d - dt.timedelta(days=1)


def merge_ranges(ranges: Iterable[tuple[Date, Date]], step: Callable[[Date], Date]) -> list[tuple[Date, Date]]:
    merged: list[tuple[Date, Date]] = []
    for s, e in sorted(ranges):
        if merged and s <= step(merged[-1][1]):
            if e > merged[-1][1]:
                merged[-1] = (merged[-1][0], e)
        else:
            merged.append((s, e))
    return merged


class Cache:
    def __init__(self, path: Path | None):
        """``path=None`` gives an in-memory cache (used by tests and --no-cache)."""
        self.path = path
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(str(path) if path else ":memory:", check_same_thread=False, timeout=30)
        with self._lock:
            try:
                self.conn.execute("PRAGMA journal_mode=WAL")
            except sqlite3.DatabaseError:
                pass
            self.conn.execute("PRAGMA synchronous=NORMAL")
            self.conn.executescript(SCHEMA)
            self.conn.commit()

    def close(self) -> None:
        with self._lock:
            self.conn.close()

    # ---- key/value metadata -------------------------------------------------
    def get(self, key: str) -> Any:
        with self._lock:
            row = self.conn.execute("SELECT value, expires FROM kv WHERE key=?", (key,)).fetchone()
        if row is None:
            return None
        value, expires = row
        if expires is not None and expires < time.time():
            return None
        return json.loads(value)

    def set(self, key: str, value: Any, ttl_days: float | None = 30) -> None:
        expires = time.time() + ttl_days * 86400 if ttl_days is not None else None
        with self._lock:
            self.conn.execute(
                "INSERT OR REPLACE INTO kv(key, value, expires) VALUES (?,?,?)",
                (key, json.dumps(value, ensure_ascii=False), expires),
            )
            self.conn.commit()

    # ---- time series ---------------------------------------------------------
    def coverage(self, skey: str) -> list[tuple[Date, Date]]:
        with self._lock:
            rows = self.conn.execute("SELECT start, end FROM coverage WHERE skey=?", (skey,)).fetchall()
        return [(Date.fromisoformat(s), Date.fromisoformat(e)) for s, e in rows]

    def missing(self, skey: str, start: Date, end: Date, monthly: bool = False) -> list[tuple[Date, Date]]:
        step = next_month if monthly else next_day
        return subtract_ranges(start, end, self.coverage(skey), step)

    def put_series(
        self,
        skey: str,
        points: dict[str, int],
        start: Date,
        end: Date,
        stable_until: Date,
        monthly: bool = False,
    ) -> None:
        """Store points fetched for [start, end]; mark as covered only the part
        that is old enough to be final."""
        step = next_month if monthly else next_day
        cover_end = min(end, stable_until)
        if monthly:
            # a month is final only once its last day is older than stable_until
            last_final = Date(stable_until.year, stable_until.month, 1)
            if next_month(last_final) - dt.timedelta(days=1) > stable_until:
                last_final = _prev(last_final, next_month)
            cover_end = min(end, last_final)
        with self._lock:
            self.conn.executemany(
                "INSERT OR REPLACE INTO views(skey, day, views) VALUES (?,?,?)",
                [(skey, day, int(v)) for day, v in points.items()],
            )
            if cover_end >= start:
                ranges = merge_ranges(self.coverage(skey) + [(start, cover_end)], step)
                self.conn.execute("DELETE FROM coverage WHERE skey=?", (skey,))
                self.conn.executemany(
                    "INSERT INTO coverage(skey, start, end) VALUES (?,?,?)",
                    [(skey, s.isoformat(), e.isoformat()) for s, e in ranges],
                )
            self.conn.commit()

    def get_series(self, skey: str, start: Date, end: Date) -> dict[str, int]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT day, views FROM views WHERE skey=? AND day>=? AND day<=?",
                (skey, start.isoformat(), end.isoformat()),
            ).fetchall()
        return {day: views for day, views in rows}

    # ---- maintenance ---------------------------------------------------------
    def info(self) -> dict[str, Any]:
        with self._lock:
            n_series = self.conn.execute("SELECT COUNT(DISTINCT skey) FROM coverage").fetchone()[0]
            n_points = self.conn.execute("SELECT COUNT(*) FROM views").fetchone()[0]
            n_meta = self.conn.execute("SELECT COUNT(*) FROM kv").fetchone()[0]
        size = self.path.stat().st_size if self.path and self.path.exists() else 0
        return {"path": str(self.path) if self.path else ":memory:", "series": n_series,
                "points": n_points, "metadata_entries": n_meta, "bytes": size}

    def clear(self, metadata_only: bool = False) -> None:
        with self._lock:
            self.conn.execute("DELETE FROM kv")
            if not metadata_only:
                self.conn.execute("DELETE FROM views")
                self.conn.execute("DELETE FROM coverage")
            self.conn.commit()
            self.conn.execute("VACUUM")
