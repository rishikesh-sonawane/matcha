import logging
import os
import random
import time
from collections import defaultdict
from pathlib import Path
from threading import Lock
from typing import Any
from urllib.parse import urlparse

import requests
import requests_cache
from requests import Response
from requests.exceptions import ConnectionError, Timeout

logger = logging.getLogger(__name__)

RETRYABLE_STATUSES: set[int] = {429, 502, 503, 504}

CACHE_DIR: Path = Path.home() / ".matcha"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

#: HTTP cache TTL in seconds — default 0 (OFF). Session 21: the user wants
#: fresh postings on every run, not replayed snapshots of the same pages
#: ("i dont want jobs cached"). Set MATCHA_HTTP_CACHE_TTL (e.g. 300) to
#: re-enable a bounded cache when repeat runs hammer a source.
_HTTP_CACHE_TTL = int(os.environ.get("MATCHA_HTTP_CACHE_TTL", "0"))

if _HTTP_CACHE_TTL > 0:
    _session: requests.Session = requests_cache.CachedSession(
        cache_name=str(CACHE_DIR / "http_cache"),
        backend="sqlite",
        expire_after=_HTTP_CACHE_TTL,
        allowable_codes=(200,),
    )
else:
    _session = requests.Session()


class TokenBucket:
    def __init__(self, rate_per_minute: int) -> None:
        self.max_tokens: int = rate_per_minute
        self.tokens: float = float(rate_per_minute)
        self.rate: float = rate_per_minute / 60.0
        self.ts: float = time.monotonic()

    def __repr__(self) -> str:
        return f"TokenBucket(tokens={self.tokens:.1f}/{self.max_tokens})"


class RateLimiter:
    def __init__(self) -> None:
        self._buckets: dict[str, TokenBucket] = {}
        self._locks: dict[str, Lock] = defaultdict(Lock)

    def set_rate(self, domain: str, rpm: int) -> None:
        with self._locks[domain]:
            self._buckets[domain] = TokenBucket(rpm)
            logger.debug("Rate limiter set %s -> %d rpm", domain, rpm)

    def acquire(self, domain: str) -> None:
        lock = self._locks[domain]
        with lock:
            bucket = self._buckets.get(domain)
            if bucket is None:
                return
            now = time.monotonic()
            bucket.tokens = min(
                bucket.max_tokens,
                bucket.tokens + (now - bucket.ts) * bucket.rate,
            )
            bucket.ts = now
            if bucket.tokens < 1:
                wait = (1 - bucket.tokens) / bucket.rate
                actual_wait = wait * random.uniform(0.5, 1.5)
                logger.debug("Rate limit wait %.2fs for %s", actual_wait, domain)
                time.sleep(actual_wait)
                bucket.ts = time.monotonic()
                bucket.tokens = 0.0
            else:
                bucket.tokens -= 1.0


limiter: RateLimiter = RateLimiter()
limiter.set_rate("linkedin.com", 3)
limiter.set_rate("indeed.com", 5)
limiter.set_rate("naukri.com", 6)
limiter.set_rate("remoteok.com", 10)
limiter.set_rate("serpapi.com", 8)
# Session 23: 6 rpm (1 req/10s) was starving the Web Search source — a single
# run fires ~15 DDGS calls (5 site queries × up to 3 app queries) plus Naukri
# and Indeed fallbacks, all through THIS bucket, so the batch timed out before
# it finished. A direct probe sustained ~20 rpm with zero failures; 30 rpm
# (1 req/2s) is the minimum that keeps ~35 total DDGS calls inside the 75s
# batch budget (35 × 2s = 70s worst-case pacing) and is still polite to
# DuckDuckGo. All DDGS consumers share one bucket so total load stays bounded.
limiter.set_rate("duckduckgo.com", 30)


def ddgs_text(
    query: str,
    *,
    max_results: int = 5,
    timelimit: str = "",
    timeout: float = 12.0,
    retries: int = 1,
    ddgs: Any = None,
) -> list[dict[str, Any]]:
    """One DDGS text search with a real timeout and a bounded retry.

    DDGS (DuckDuckGo metasearch) is free and occasionally flaky: connection
    timeouts, refused connections (the startpage fallback), and "ddgs down"
    are TRANSIENT. Session 23: give every call a generous timeout (the
    library's 5s default sits right at the observed latency edge) and retry
    once with a short backoff so a single blip cannot kill the query. The
    caller is responsible for ``limiter.acquire`` (rate pacing) and for
    checking ``DDGS is not None`` first.

    ``ddgs`` is the DDGS class/factory (defaults to the installed library).
    Tests pass a fake factory; production callers pass their module-level
    ``DDGS`` so the library stays an optional dependency.
    """
    if ddgs is None:
        from ddgs import DDGS as _DDGS  # type: ignore[assignment]

        ddgs = _DDGS
    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        try:
            with ddgs(timeout=timeout) as client:  # type: ignore[operator]
                if timelimit:
                    return list(client.text(query, max_results=max_results, timelimit=timelimit))
                return list(client.text(query, max_results=max_results))
        except Exception as e:  # noqa: BLE001 — transient network/backend errors
            last_exc = e
            if attempt < retries:
                wait = 1.0 + attempt
                logger.warning(
                    "DDGS query failed (attempt %d/%d, retry in %.0fs): %s",
                    attempt + 1,
                    retries + 1,
                    wait,
                    e,
                )
                time.sleep(wait)
    raise last_exc if last_exc is not None else RuntimeError("ddgs query failed")


def _get_domain(url: str) -> str:
    return urlparse(url).netloc.lower().removeprefix("www.")


def resilient_get(
    url: str,
    session: requests.Session | None = None,
    **kwargs: Any,
) -> Response:
    limiter.acquire(_get_domain(url))
    http = session if session is not None else _session
    timeout = kwargs.pop("timeout", 15)
    last_exc: Exception | None = None
    for attempt in range(3):
        try:
            resp: Response = http.get(url, timeout=timeout, **kwargs)
            if resp.status_code in RETRYABLE_STATUSES and attempt < 2:
                wait = 2**attempt
                logger.warning(
                    "Retryable status %d on %s, retrying in %ds (attempt %d/3)",
                    resp.status_code,
                    url,
                    wait,
                    attempt + 1,
                )
                time.sleep(wait)
                continue
            if resp.status_code != 200:
                logger.debug("Non-200 response %d from %s", resp.status_code, url)
            return resp
        except (ConnectionError, Timeout) as e:
            last_exc = e
            if attempt < 2:
                wait = 2**attempt
                logger.warning(
                    "Request failed %s on %s, retrying in %ds (attempt %d/3): %s",
                    type(e).__name__,
                    url,
                    wait,
                    attempt + 1,
                    e,
                )
                time.sleep(wait)
                continue
            raise
    raise last_exc if last_exc else ConnectionError("Max retries exceeded")
