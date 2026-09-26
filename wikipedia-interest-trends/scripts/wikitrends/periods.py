"""Analysis windows made of complete calendar months."""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass

from . import config

MIN_MONTHS = 24  # needed for a seasonally fair year-over-year comparison
MAX_MONTHS = 132


class PeriodError(ValueError):
    pass


@dataclass(frozen=True)
class Window:
    start: dt.date  # first day of first month
    end: dt.date  # last day of last month
    notes: tuple[str, ...] = ()

    @property
    def months(self) -> list[str]:
        return month_range(self.start, self.end)

    @property
    def n_months(self) -> int:
        return len(self.months)

    def label(self) -> str:
        return f"{self.start:%Y-%m}..{self.end:%Y-%m}"


def first_of_month(d: dt.date) -> dt.date:
    return d.replace(day=1)


def last_of_month(d: dt.date) -> dt.date:
    nxt = dt.date(d.year + (d.month == 12), d.month % 12 + 1, 1)
    return nxt - dt.timedelta(days=1)


def add_months(d: dt.date, n: int) -> dt.date:
    idx = d.year * 12 + (d.month - 1) + n
    return dt.date(idx // 12, idx % 12 + 1, 1)


def month_range(start: dt.date, end: dt.date) -> list[str]:
    out = []
    cur = first_of_month(start)
    while cur <= end:
        out.append(f"{cur:%Y-%m}")
        cur = add_months(cur, 1)
    return out


def parse_month(text: str) -> dt.date:
    m = re.fullmatch(r"\s*(\d{4})-(\d{1,2})(?:-\d{1,2})?\s*", text)
    if not m:
        raise PeriodError(f"expected YYYY-MM, got '{text}'")
    year, month = int(m.group(1)), int(m.group(2))
    if not 1 <= month <= 12:
        raise PeriodError(f"invalid month in '{text}'")
    return dt.date(year, month, 1)


def last_complete_month_end(today: dt.date | None = None) -> dt.date:
    today = today or config.today()
    ref = today - dt.timedelta(days=config.DATA_LAG_DAYS)
    return first_of_month(ref) - dt.timedelta(days=1)


def make_window(
    months: int | None = None,
    start: str | None = None,
    end: str | None = None,
    today: dt.date | None = None,
    min_months: int = MIN_MONTHS,
) -> Window:
    """Resolve CLI period options into a window of complete months.

    Priority: explicit start/end, else the last ``months`` complete months
    (default 24). Windows shorter than ``min_months`` are extended backwards so
    that the latest 12 months can be compared with the 12 before them.
    """
    notes: list[str] = []
    latest_end = last_complete_month_end(today)
    if end:
        end_d = last_of_month(parse_month(end))
        if end_d > latest_end:
            notes.append(f"end {end} is not complete yet; using {latest_end:%Y-%m}")
            end_d = latest_end
    else:
        end_d = latest_end
    if start:
        start_d = parse_month(start)
    else:
        n = months if months is not None else MIN_MONTHS
        if n < 1:
            raise PeriodError("--months must be >= 1")
        start_d = add_months(first_of_month(end_d), -(n - 1))
    if start_d > end_d:
        raise PeriodError(f"start {start_d:%Y-%m} is after end {end_d:%Y-%m}")
    n_months = len(month_range(start_d, end_d))
    if n_months < min_months:
        new_start = add_months(first_of_month(end_d), -(min_months - 1))
        notes.append(
            f"period extended from {n_months} to {min_months} months "
            f"({new_start:%Y-%m}..{end_d:%Y-%m}) so the last 12 months can be compared with the 12 before"
        )
        start_d = new_start
    if n_months > MAX_MONTHS:
        start_d = add_months(first_of_month(end_d), -(MAX_MONTHS - 1))
        notes.append(f"period capped at {MAX_MONTHS} months")
    if start_d < config.PAGEVIEWS_START:
        start_d = add_months(config.PAGEVIEWS_START, 0)
        notes.append("pageview data starts in 2015-07; period clipped")
        if len(month_range(start_d, end_d)) < min_months:
            raise PeriodError("not enough history: need at least 24 months after 2015-07")
    return Window(start=start_d, end=end_d, notes=tuple(notes))


def days(start: dt.date, end: dt.date) -> list[dt.date]:
    n = (end - start).days + 1
    return [start + dt.timedelta(days=i) for i in range(n)]
