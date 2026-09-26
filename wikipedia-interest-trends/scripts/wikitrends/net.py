"""Minimal, polite HTTP JSON client (stdlib only).

* identifies itself with a policy-compliant User-Agent,
* spaces requests with a process-wide rate limiter,
* retries 429/5xx/network errors with Retry-After or exponential backoff,
* turns 404 into ``NotFound`` (the pageviews API uses it for "no data").
"""

from __future__ import annotations

import gzip
import http.client
import json
import random
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable

RETRY_STATUSES = {429, 500, 502, 503, 504}


class NetError(Exception):
    def __init__(self, message: str, status: int | None = None, url: str | None = None):
        super().__init__(message)
        self.status = status
        self.url = url


class NotFound(NetError):
    pass


class OfflineError(NetError):
    pass


class RateLimiter:
    """Guarantees a minimum interval between request starts (thread-safe)."""

    def __init__(self, rps: float):
        self.interval = 1.0 / rps if rps > 0 else 0.0
        self._lock = threading.Lock()
        self._next = 0.0

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            slot = max(now, self._next)
            self._next = slot + self.interval
        delay = slot - now
        if delay > 0:
            time.sleep(delay)


def _retry_after(headers: Any) -> float | None:
    if headers is None:
        return None
    value = headers.get("Retry-After")
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        return None


class Client:
    def __init__(
        self,
        user_agent: str,
        rps: float = 2.5,
        retries: int = 5,
        timeout: float = 30.0,
        offline: bool = False,
        opener: Callable[..., Any] | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.user_agent = user_agent
        self.limiter = RateLimiter(rps)
        self.retries = retries
        self.timeout = timeout
        self.offline = offline
        self._open = opener or urllib.request.urlopen
        self._sleep = sleep
        self._stats_lock = threading.Lock()
        self.stats = {"requests": 0, "retries": 0}

    def _count(self, key: str) -> None:
        with self._stats_lock:
            self.stats[key] += 1

    def _backoff(self, attempt: int, retry_after: float | None) -> float:
        if retry_after is not None:
            return min(retry_after, 60.0)
        return min(30.0, (2 ** attempt)) * (0.75 + random.random() * 0.5)

    def get_json(self, url: str, params: dict[str, Any] | None = None) -> Any:
        if params:
            url = url + ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
        if self.offline:
            raise OfflineError(f"offline mode (WIKITRENDS_OFFLINE=1): not fetching {url}", url=url)
        headers = {
            "User-Agent": self.user_agent,
            "Api-User-Agent": self.user_agent,
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
        }
        attempt = 0
        while True:
            self.limiter.wait()
            request = urllib.request.Request(url, headers=headers)
            try:
                with self._open(request, timeout=self.timeout) as resp:
                    raw = resp.read()
                    if (resp.headers.get("Content-Encoding") or "").lower() == "gzip":
                        raw = gzip.decompress(raw)
                self._count("requests")
                try:
                    return json.loads(raw.decode("utf-8"))
                except (ValueError, UnicodeDecodeError) as exc:
                    raise NetError(f"invalid JSON from {url}: {exc}", url=url) from exc
            except urllib.error.HTTPError as exc:
                self._count("requests")
                body = ""
                try:
                    body = exc.read().decode("utf-8", "replace")[:300]
                except Exception:  # noqa: BLE001 - best effort diagnostics only
                    pass
                if exc.code == 404:
                    raise NotFound(f"404 for {url}", status=404, url=url) from None
                if exc.code in RETRY_STATUSES and attempt < self.retries:
                    self._count("retries")
                    self._sleep(self._backoff(attempt, _retry_after(exc.headers)))
                    attempt += 1
                    continue
                hint = ""
                if exc.code == 403:
                    hint = " (Wikimedia rejects clients without a descriptive User-Agent; set WIKITRENDS_CONTACT)"
                if exc.code == 429:
                    hint = " (rate limited: lower WIKITRENDS_MAX_RPS or retry later)"
                raise NetError(f"HTTP {exc.code} for {url}{hint}: {body}", status=exc.code, url=url) from None
            except (urllib.error.URLError, http.client.HTTPException, TimeoutError, ConnectionError, OSError) as exc:
                reason = getattr(exc, "reason", exc)
                text = str(reason)
                if "Tunnel connection failed: 403" in text or "403 Forbidden" in text:
                    host = urllib.parse.urlsplit(url).hostname
                    raise NetError(
                        f"network access to {host} is blocked by a proxy/firewall (403). "
                        f"Allow {host} in the environment's network settings.",
                        status=403,
                        url=url,
                    ) from None
                if attempt < self.retries:
                    self._count("retries")
                    self._sleep(self._backoff(attempt, None))
                    attempt += 1
                    continue
                raise NetError(f"network error for {url}: {text}", url=url) from None
