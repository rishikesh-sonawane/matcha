"""RSS job source (strategy §6.2) — company/job-board feeds via feedparser.

Feed URLs come from settings ``sources.rss.feeds`` (default: none → the
source reports ``off`` and search returns nothing). Each feed is fetched with
a bounded timeout; entries are filtered by the query's significant terms
against title + summary and mapped to Matcha job rows with
``data_quality=\"partial\"``. Per-feed failures are isolated into
``errors`` — a dead feed can never abort the batch (failproof by
construction).
"""

import logging
import time
from typing import Any

from matcha.models import ScraperResult
from matcha.sources.base import Source
from matcha.sources.constants import STOP_WORDS
from matcha.sources.utils import limiter, resilient_get

try:
    import feedparser
except ImportError:  # pragma: no cover - dependency not installed
    feedparser = None  # type: ignore[assignment, misc]

logger = logging.getLogger(__name__)

_RSS_TIMEOUT = 12
_MAX_ENTRIES_PER_FEED = 30
_MAX_TOTAL_JOBS = 60


def feeds_from_config(config: dict[str, Any] | None) -> list[str]:
    """Pull the ``sources.rss.feeds`` list out of a settings dict."""
    if not config or not isinstance(config, dict):
        return []
    sources_cfg = config.get("sources")
    if not isinstance(sources_cfg, dict):
        return []
    rss_cfg = sources_cfg.get("rss")
    if not isinstance(rss_cfg, dict):
        return []
    feeds = rss_cfg.get("feeds", [])
    return [str(f) for f in feeds if isinstance(f, str) and f.strip()]


def _significant_terms(query: str) -> set[str]:
    terms = set(query.lower().split())
    significant = {t for t in terms if t not in STOP_WORDS and len(t) > 1}
    return significant or terms


def _entry_matches(entry: Any, terms: set[str]) -> bool:
    text = " ".join([str(entry.get("title") or ""), str(entry.get("summary") or "")]).lower()
    return any(t in text for t in terms)


def _listed_epoch(entry: Any) -> int | None:
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if parsed:
        try:
            return int(time.mktime(parsed))
        except (OverflowError, ValueError, TypeError):
            return None
    return None


def search_rss_jobs(
    query: str,
    location: str = "",
    feeds: list[str] | None = None,
    **kwargs: Any,
) -> ScraperResult:
    """Fetch configured RSS feeds and return query-matching job rows."""
    errors: list[str] = []
    jobs: list[dict[str, Any]] = []
    feed_urls = feeds or []
    if not feed_urls:
        return ScraperResult(
            jobs=jobs, errors=errors, source="RSS", backend="rss", data_quality="partial"
        )
    terms = _significant_terms(query or "")

    for feed_url in feed_urls[:10]:
        try:
            limiter.acquire("rss")
            resp = resilient_get(feed_url, timeout=_RSS_TIMEOUT)
            if resp.status_code != 200:
                errors.append(f"{feed_url}: HTTP {resp.status_code}")
                continue
            try:
                parsed = feedparser.parse(resp.text)
            except Exception as e:  # noqa: BLE001 - a bad feed is one isolated error
                errors.append(f"{feed_url}: unparseable feed ({e})")
                continue
            if getattr(parsed, "bozo", False) and not parsed.entries:
                errors.append(f"{feed_url}: unparseable feed ({parsed.bozo_exception})")
                continue
            if not getattr(parsed, "version", None) and not parsed.entries:
                errors.append(f"{feed_url}: unparseable feed (no recognized feed format)")
                continue
            feed_title = str((parsed.feed.get("title") if parsed.feed else "") or "")
            for entry in parsed.entries[:_MAX_ENTRIES_PER_FEED]:
                try:
                    title = str(entry.get("title") or "").strip()
                    if not title or not _entry_matches(entry, terms):
                        continue
                    company = str(
                        (entry.get("author") if entry.get("author") else feed_title) or ""
                    ).strip()
                    summary = str(entry.get("summary") or entry.get("description") or "")
                    jobs.append(
                        {
                            "title": title,
                            "company": company,
                            "location": location or "",
                            "description": summary[:1000],
                            "url": str(entry.get("link") or ""),
                            "source": "RSS",
                            "listed": str(entry.get("published") or entry.get("updated") or ""),
                            "listed_epoch": _listed_epoch(entry),
                        }
                    )
                    if len(jobs) >= _MAX_TOTAL_JOBS:
                        break
                except Exception as e:  # noqa: BLE001 - one bad entry must not abort
                    logger.warning("Failed to parse RSS entry from %s: %s", feed_url, e)
                    continue
            if len(jobs) >= _MAX_TOTAL_JOBS:
                break
        except Exception as e:  # noqa: BLE001 - one dead feed must not abort
            errors.append(f"{feed_url}: {e}")
            logger.warning("RSS feed failed %s: %s", feed_url, e)
            continue

    return ScraperResult(
        jobs=jobs, errors=errors, source="RSS", backend="rss", data_quality="partial"
    )


class RSSSource(Source):
    """RSS — company/job-board feeds (optional; needs sources.rss.feeds)."""

    name = "rss"
    description = "RSS — company/job-board feeds"
    backends = ["rss"]
    tier = 0
    enabled_by_default = False  # needs feeds configured to be useful

    def check(self, config: dict[str, Any] | None = None) -> tuple[str, str]:
        if feedparser is None:
            self.active_backend = None
            return "error", "feedparser not installed (pip install feedparser)"
        feeds = feeds_from_config(config)
        if not feeds:
            self.active_backend = None
            return "off", "no feeds configured (settings sources.rss.feeds)"
        self.active_backend = "rss"
        return "ok", f"{len(feeds)} feed(s) configured"

    def search(self, query: str, location: str = "", **kwargs: Any) -> ScraperResult:
        feeds = kwargs.pop("feeds", None) or feeds_from_config(kwargs.get("config"))
        return search_rss_jobs(query, location, feeds=feeds, **kwargs)
