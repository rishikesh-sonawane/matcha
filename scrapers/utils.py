import random
import time
from collections import defaultdict
from pathlib import Path
from threading import Lock
from typing import Any, Optional
from urllib.parse import urlparse

import requests_cache
from requests import Response
from requests.exceptions import ConnectionError, Timeout

RETRYABLE_STATUSES: set[int] = {429, 502, 503, 504}

CACHE_DIR: Path = Path.home() / ".matcha"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

_session: requests_cache.CachedSession = requests_cache.CachedSession(
    cache_name=str(CACHE_DIR / "http_cache"),
    backend="sqlite",
    expire_after=1800,
    allowable_codes=(200,),
)


class TokenBucket:
    def __init__(self, rate_per_minute: int) -> None:
        self.max_tokens: int = rate_per_minute
        self.tokens: float = float(rate_per_minute)
        self.rate: float = rate_per_minute / 60.0
        self.ts: float = time.monotonic()


class RateLimiter:
    def __init__(self) -> None:
        self._buckets: dict[str, TokenBucket] = {}
        self._locks: dict[str, Lock] = defaultdict(Lock)

    def set_rate(self, domain: str, rpm: int) -> None:
        with self._locks[domain]:
            self._buckets[domain] = TokenBucket(rpm)

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
                time.sleep(wait * random.uniform(0.5, 1.5))
                bucket.ts = time.monotonic()
                bucket.tokens = 0.0
            else:
                bucket.tokens -= 1.0


_limiter: RateLimiter = RateLimiter()
_limiter.set_rate("linkedin.com", 3)
_limiter.set_rate("indeed.com", 5)
_limiter.set_rate("remoteok.com", 10)
_limiter.set_rate("serpapi.com", 8)
_limiter.set_rate("duckduckgo.com", 6)


def _get_domain(url: str) -> str:
    return urlparse(url).netloc.lower().removeprefix("www.")


def resilient_get(
    url: str,
    session: Optional[requests_cache.CachedSession] = None,
    **kwargs: Any,
) -> Response:
    _limiter.acquire(_get_domain(url))
    http = session if session is not None else _session
    timeout = kwargs.pop("timeout", 15)
    for attempt in range(3):
        try:
            resp: Response = http.get(url, timeout=timeout, **kwargs)
            if resp.status_code in RETRYABLE_STATUSES and attempt < 2:
                time.sleep(2**attempt)
                continue
            return resp
        except (ConnectionError, Timeout):
            if attempt < 2:
                time.sleep(2**attempt)
                continue
            raise
    return http.get(url, timeout=timeout, **kwargs)
