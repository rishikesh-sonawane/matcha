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
limiter.set_rate("duckduckgo.com", 6)


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
