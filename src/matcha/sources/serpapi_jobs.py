import logging
import re
import time
from typing import Any

import requests

from matcha.models import ScraperResult
from matcha.sources.base import Source

from .utils import resilient_get

logger = logging.getLogger(__name__)

SERPAPI_BASE: str = "https://serpapi.com/search.json"

#: "3 days ago", "2026-08-01", "Aug 1, 2026" — used to pick the date out of
#: the ``extensions[]`` array when ``detected_extensions`` is absent.
_DATE_LIKE = re.compile(r"(\d+\s+(second|minute|hour|day|week|month|year)s?\s+ago)", re.I)


def _is_relative_date(text: str) -> bool:
    return bool(_DATE_LIKE.search(text))


#: date_posted label -> worst-case window seconds (the row is no OLDER than
#: this bound because SerpAPI filtered server-side).
_WINDOW_DAYS = {"today": 1, "3days": 3, "week": 7, "month": 30}


def _window_guarantees_age(date_posted: str, days: int | None) -> bool:
    """True when the server-side window is no looser than the requested days.

    Stamp a window only when it can't mislead the central age filter: a
    ``week`` window (7 days) vs a user-requested 5 days means a row could be
    6 days old — stamping it "within week" would then be dropped by the 5-day
    filter (or, worse, appear fresh). In that case keep the honest ``[age?]``
    tag instead. ``days=None`` means the central filter's default of 7.
    """
    window_days = _WINDOW_DAYS.get(date_posted)
    if window_days is None:
        return False
    return window_days <= (days or 7)


def _window_epoch(date_posted: str) -> int:
    """Worst-case epoch for a server-side date_posted window.

    ``date_posted=3days`` returns only rows posted within 3 days, so a row
    missing an explicit date is at most 3 days old — stamp that bound (not
    ``now``, which would lie about recency) so the central age filter can
    still judge the row honestly. A 2-minute grace covers the search-to-
    filter pipeline latency: SerpAPI guaranteed the window at REQUEST time
    (seconds before the age filter computes its cutoff), so a boundary row
    must not be dropped as "too old" by that drift.
    """
    days = _WINDOW_DAYS.get(date_posted, 7)
    return int(time.time() - days * 86400 + 120)


def search_serpapi_jobs(
    query: str,
    location: str = "",
    **kwargs: Any,
) -> ScraperResult:
    errors: list[str] = []
    config = get_serpapi_config()
    api_key = config.get("serpapi_key")
    if not api_key:
        return ScraperResult(
            errors=["SerpAPI key not configured"], source="Google Jobs", backend="serpapi"
        )

    search_query = f"{query} job"
    if location:
        search_query += f" {location}"

    days = kwargs.get("days")
    date_map = {1: "today", 3: "3days", 7: "week", 30: "month"}
    date_posted = "week"
    if days:
        for threshold, label in sorted(date_map.items()):
            if days <= threshold:
                date_posted = label
                break
        else:
            date_posted = "month"

    max_pages = kwargs.get("max_pages", 1)

    params = {
        "engine": "google_jobs",
        "q": search_query,
        "api_key": api_key,
        "hl": "en",
        "date_posted": date_posted,
    }

    logger.info("Searching Google Jobs: q=%s location=%s max_pages=%s", query, location, max_pages)
    try:
        jobs: list[dict[str, str]] = []

        for page in range(max_pages):
            page_params = dict(params)
            if page > 0:
                page_params["start"] = str(page * 10)

            resp = resilient_get(SERPAPI_BASE, params=page_params, timeout=15)
            if resp.status_code != 200:
                msg = f"SerpAPI page {page + 1} returned status {resp.status_code}"
                logger.warning(msg)
                errors.append(msg)
                break

            data = resp.json()
            error = data.get("error")
            if error:
                if "hasn't returned any results" in str(error):
                    # Soft "no results" for this query — not a failure; log
                    # it and move on instead of surfacing an error state.
                    logger.info("Google Jobs: no results for query")
                else:
                    logger.warning("SerpAPI error: %s", error)
                    errors.append(str(error))
                break

            jobs_results = data.get("jobs_results", [])
            if not jobs_results:
                logger.info("Google Jobs page %d: no results, stopping pagination", page + 1)
                break

            for item in jobs_results:
                try:
                    title = item.get("title") or ""
                    company = item.get("company_name") or ""
                    location_text = item.get("location") or "Remote"
                    description = item.get("description") or ""

                    # Session 21: current google_jobs responses carry the apply
                    # URL under ``apply_options`` (``related_links`` is null) —
                    # without it every row lost its URL and the quality gate
                    # silently dropped the whole source.
                    url = ""
                    for link in item.get("apply_options", []) or []:
                        candidate = link.get("link") or ""
                        if candidate and "google.com/search" not in candidate:
                            url = candidate
                            break
                    if not url:
                        url = item.get("source_link") or ""
                    if not url or "google.com/search" in url:
                        # last resort: a share link is a google search page, not
                        # a posting — only use it when nothing better exists.
                        share = item.get("share_link") or ""
                        url = share if not url else url

                    job: dict[str, Any] = {
                        "title": title,
                        "company": company,
                        "location": location_text,
                        "description": description[:2000],
                        "url": url,
                        "source": "Google Jobs",
                    }
                    # Session 22: google_jobs reports the posting date under
                    # detected_extensions.posted_at ("3 days ago") — without it
                    # every row carried [age?] and skipped the age filter. Some
                    # responses omit detected_extensions entirely, so fall back
                    # to the extensions[] array (first element = the date).
                    posted = (item.get("detected_extensions") or {}).get("posted_at")
                    if not posted:
                        ext = item.get("extensions") or []
                        if ext and _is_relative_date(str(ext[0])):
                            posted = ext[0]
                    if posted:
                        job["listed"] = str(posted)
                    elif _window_guarantees_age(date_posted, days):
                        # Session 22: SerpAPI omits the date on some rows, but
                        # the ``date_posted`` param is applied SERVER-SIDE — a
                        # row returned under date_posted=3days IS within 3 days.
                        # Don't tag it [age?] (misleading — the source already
                        # guaranteed freshness); stamp the window truthfully and
                        # give the central age filter a worst-case epoch. Only
                        # when the window is no looser than the requested days
                        # (else the stamp would lie about a wider window and the
                        # central filter would silently drop the row).
                        job["listed"] = f"within {date_posted}"
                        job["listed_epoch"] = _window_epoch(date_posted)
                    jobs.append(job)
                except Exception as e:
                    logger.warning("Failed to parse SerpAPI result: %s", e)
                    continue

            logger.info(
                "Google Jobs page %d: %d jobs parsed (total %d)",
                page + 1,
                len(jobs_results),
                len(jobs),
            )

        return ScraperResult(
            jobs=jobs,
            errors=errors,
            source="Google Jobs",
            backend="serpapi",
            data_quality="partial",
        )

    except requests.RequestException as e:
        msg = f"SerpAPI request failed: {e}"
        logger.warning(msg)
        errors.append(msg)
        return ScraperResult(errors=errors, source="Google Jobs", backend="serpapi")


class SerpapiSource(Source):
    """Google Jobs — via SerpAPI (needs a key, tier 1)."""

    name = "serpapi"
    description = "Google Jobs — via SerpAPI"
    backends = ["serpapi"]
    tier = 1

    def check(self, config: dict[str, Any] | None = None) -> tuple[str, str]:
        if check_serpapi_available():
            self.active_backend = "serpapi"
            return "ok", "SerpAPI key configured"
        self.active_backend = None
        return "off", "No SerpAPI key — run `matcha --configure` (free tier: 100/mo)"

    def search(self, query: str, location: str = "", **kwargs: Any) -> ScraperResult:
        return search_serpapi_jobs(query, location, **kwargs)


def check_serpapi_available() -> bool:
    config = get_serpapi_config()
    return bool(config.get("serpapi_key"))


def get_serpapi_config() -> dict[str, Any]:
    try:
        from matcha.config import load_config

        return load_config()
    except ImportError:
        return {}
