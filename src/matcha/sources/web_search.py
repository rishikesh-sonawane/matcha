import logging
import re
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

try:
    from ddgs import DDGS
except ImportError:
    DDGS = None

from matcha.models import ScraperResult
from matcha.sources.base import Source
from matcha.sources.constants import (
    COMPANY_EXTRACTION_PATTERNS,
    JOB_SOURCE_DOMAINS,
    MONTH_NAMES,
    NON_JOB_TITLE_PATTERNS,
    NON_JOB_URL_PATTERNS,
    SEARCH_PAGE_PATTERNS,
    SKIP_DOMAIN_PARTS,
    STOP_WORDS,
)

from .utils import limiter

logger = logging.getLogger(__name__)


def _dedup_jobs(jobs: list[dict[str, str]]) -> list[dict[str, str]]:
    seen_urls: set[str] = set()
    result: list[dict[str, str]] = []
    for j in jobs:
        if j["url"] not in seen_urls:
            seen_urls.add(j["url"])
            result.append(j)
    return result


def _is_older_than_days(text: str, max_days: int) -> bool:
    now = time.time()
    patterns = [
        (re.compile(r"(\d+)\s+(?:year|yr)s?\s+ago"), 365),
        (re.compile(r"(\d+)\s+month(?:s)?\s+ago"), 30),
        (re.compile(r"(\d+)\s+week(?:s)?\s+ago"), 7),
        (re.compile(r"(\d+)\s+day(?:s)?\s+ago"), 1),
        (re.compile(r"(?:posted|published|updated)\s+(\d+)\s+(?:year|yr)s?\s+ago"), 365),
        (re.compile(r"(?:posted|published|updated)\s+(\d+)\s+month(?:s)?\s+ago"), 30),
        (re.compile(r"(?:posted|published|updated)\s+(\d+)\s+week(?:s)?\s+ago"), 7),
        (re.compile(r"(?:posted|published|updated)\s+(\d+)\s+day(?:s)?\s+ago"), 1),
    ]
    text_lower = text.lower()
    for pat, unit_days in patterns:
        m = pat.search(text_lower)
        if m:
            num = int(m.group(1))
            if num * unit_days > max_days:
                return True
    m = re.search(
        r"(?:posted|published|updated|date)\s*:\s*(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec|january|february|march|april|may|june|july|august|september|october|november|december)\s+(\d{1,2})(?:,?\s*(\d{4}))?",
        text_lower,
    )
    if m:
        month = MONTH_NAMES.get(m.group(1), 1)
        day = int(m.group(2))
        year = int(m.group(3)) if m.group(3) else time.gmtime().tm_year
        posted = time.mktime((year, month, day, 0, 0, 0, 0, 0, 0))
        age_days = (now - posted) / 86400
        if age_days > max_days:
            return True
    return False


def search_web_for_jobs(
    query: str,
    location: str = "",
    **kwargs: Any,
) -> ScraperResult:
    """Acquire web-search jobs, preferring the Exa semantic backend.

    Phase 1 (strategy §6.2): when the Exa MCP server is configured in
    mcporter, search semantically for clean job postings; degrade to the DDGS
    keyword path on any failure (never return empty because Exa hiccuped).
    """
    backend = kwargs.pop("backend", None)
    config = kwargs.pop("config", None)
    # Exa needs no consent (it is a public search API, not the user's browser)
    # and no config beyond the mcporter server being present.
    if backend is None:
        backend = "exa" if _exa_should_run(config) else "ddgs"
    if backend == "exa":
        result = _search_web_exa(query, location, **kwargs)
        if result is not None:
            return result
        logger.info("Exa unavailable at search time; falling back to DDGS")
    return _search_web_ddgs(query, location, **kwargs)


def _exa_should_run(config: dict[str, Any] | None) -> bool:
    del config  # exa configuration lives in the mcporter config files
    from matcha.sources.backends.exa import exa_configured

    return exa_configured()


def _search_web_exa(
    query: str,
    location: str = "",
    **kwargs: Any,
) -> ScraperResult | None:
    """Run an Exa semantic search; None = could not run (caller falls back)."""
    from matcha.sources.backends.exa import exa_search

    days = kwargs.get("days")
    rows = exa_search(query, location=location, days=days, num=int(kwargs.get("num") or 5))
    if rows is None:
        return None

    jobs: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in rows:
        try:
            title = _clean_title(str(row.get("title") or ""))
            url = str(row.get("url") or "")
            text = str(row.get("text") or "")
            if not title or not url or url in seen:
                continue
            if days and _iso_older_than_days(str(row.get("publishedDate") or ""), days):
                continue
            seen.add(url)
            job: dict[str, str] = {
                "title": title,
                "company": str(row.get("author") or "").strip()
                or _extract_company(url, text, title),
                "location": _extract_location(text, url, title),
                "description": text[:1000],
                "url": url,
                "source": _identify_source(url),
            }
            if row.get("publishedDate"):
                job["listed"] = str(row["publishedDate"])[:10]
            if row.get("score") is not None:
                job["score"] = float(row["score"])
            jobs.append(job)
        except (AttributeError, ValueError, TypeError) as e:
            logger.warning("Failed to parse Exa result: %s", e)
            continue

    return ScraperResult(jobs=jobs, source="Web Search", backend="exa", data_quality="partial")


def _iso_older_than_days(iso: str, days: int) -> bool:
    """True when an ISO-8601 date is older than ``days`` (client-side recency)."""
    if not iso:
        return False
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return False
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    age_days = (datetime.now(timezone.utc) - dt).total_seconds() / 86400
    return age_days > days


def _search_web_ddgs(
    query: str,
    location: str = "",
    **kwargs: Any,
) -> ScraperResult:
    errors: list[str] = []
    if DDGS is None:
        return ScraperResult(
            errors=["ddgs library not available"], source="Web Search", backend="ddgs"
        )

    jobs: list[dict[str, str]] = []
    days = kwargs.get("days")
    timelimit = ""
    if days:
        if days <= 1:
            timelimit = "d"
        elif days <= 7:
            timelimit = "w"
        else:
            timelimit = "m"

    site_queries: list[str] = [
        f"site:greenhouse.io {query} {location}",
        f"site:lever.co {query} {location}",
        f"site:jobs.ashbyhq.com {query} {location}",
        f"site:boards.greenhouse.io {query} {location}",
    ]
    site_queries.append(f"{query} {location} career")

    logger.info("Searching Web Search: q=%s location=%s", query, location)

    for q in site_queries:
        limiter.acquire("duckduckgo.com")
        try:
            with DDGS() as ddgs:
                raw = (
                    ddgs.text(q, max_results=5, timelimit=timelimit)
                    if timelimit
                    else ddgs.text(q, max_results=5)
                )
        except Exception as e:
            logger.warning("Web search DDGS query failed (%s): %s", q, e)
            errors.append(f"DDGS query failed: {q[:50]}")
            continue

        for item in raw:
            try:
                title = item.get("title", "")
                url = item.get("href", "")
                snippet = item.get("body", "")

                if not title or not url:
                    continue
                if _is_search_page(title, url):
                    continue
                if any(re.search(p, url) for p in NON_JOB_URL_PATTERNS):
                    continue
                if any(re.search(p, title) for p in NON_JOB_TITLE_PATTERNS):
                    continue
                if days and _is_older_than_days(snippet, days):
                    continue

                job = {
                    "title": _clean_title(title),
                    "company": _extract_company(url, snippet, title),
                    "location": _extract_location(snippet, url, title),
                    "description": snippet[:1000],
                    "url": url,
                    "source": _identify_source(url),
                }
                if job["title"] and not _is_search_page(job["title"], url):
                    jobs.append(job)
            except Exception as e:
                logger.warning("Failed to parse web search result: %s", e)
                continue

        if len(jobs) >= 10:
            break

    return ScraperResult(
        jobs=_dedup_jobs(jobs),
        errors=errors,
        source="Web Search",
        backend="ddgs",
        data_quality="snippet",
    )


class WebSearchSource(Source):
    """Web Search — Exa semantic backend (via mcporter), DDGS fallback."""

    name = "web_search"
    description = "Web Search — Exa semantic, DDGS keyword fallback"
    backends = ["exa", "ddgs"]
    tier = 0

    def check(self, config: dict[str, Any] | None = None) -> tuple[str, str]:
        from matcha.sources.backends.exa import exa_status

        for backend in self.ordered_backends(config):
            if backend == "exa":
                status, msg = exa_status(config)
                if status in ("ok", "warn"):
                    self.active_backend = "exa"
                    return status, msg
                self.active_backend = None  # off/error — try the next backend
            elif backend == "ddgs":
                status, msg = self._ddgs_status(DDGS is not None)
                self.active_backend = "ddgs" if status == "ok" else None
                return status, msg
        self.active_backend = None
        return "error", "Web Search unavailable via any backend"

    def search(self, query: str, location: str = "", **kwargs: Any) -> ScraperResult:
        return search_web_for_jobs(query, location, **kwargs)


def _is_search_page(title: str, url: str) -> bool:
    for p in SEARCH_PAGE_PATTERNS:
        if p.search(title):
            return True
    if re.search(r"/search\?", url, re.IGNORECASE):
        return True
    return False


def _clean_title(title: str) -> str:
    title = re.sub(
        r"\s*[-–|]\s*(?:LinkedIn|Indeed|Glassdoor|Monster|ZipRecruiter).*",
        "",
        title,
        flags=re.IGNORECASE,
    )
    title = re.sub(r"\s*[-–|]\s*(?:Hiring|Job|Opening|Vacancy).*", "", title, flags=re.IGNORECASE)
    m = re.search(r"^\s*[A-Z][A-Za-z0-9&.]+\s+(?:is\s+)?hiring\s+", title, re.IGNORECASE)
    if m:
        title = title[m.end() :].strip()
        title = re.sub(r"\s+in\s+[A-Z][a-zA-Z\s,]*$", "", title).strip()
    segments = re.split(r"\s*[-–|]\s*", title)
    return segments[0].strip() if segments[0].strip() else title.strip()


def _extract_company(url: str, snippet: str, title: str) -> str:
    for p in COMPANY_EXTRACTION_PATTERNS:
        m = p.search(snippet or "")
        if m:
            candidate = m.group(1).strip()
            first_word = candidate.split()[0].lower()
            if len(candidate) >= 3 and first_word not in STOP_WORDS:
                return candidate

    m = re.search(r"^([A-Z][A-Za-z0-9\s&.]+?)\s+(?:is\s+)?hiring\s+", title or "", re.IGNORECASE)
    if m:
        return m.group(1).strip()

    domain = urlparse(url).netloc.lower()
    domain = re.sub(r"^www\d*\.", "", domain)
    parts = [p for p in domain.split(".") if p not in SKIP_DOMAIN_PARTS]
    return parts[0].title() if parts else domain.split(".")[0].title()


def _extract_location(snippet: str, url: str, title: str) -> str:
    patterns = [
        re.compile(r"in\s+([A-Z][a-zA-Z\s]+(?:,\s*[A-Z]{2})?)", re.IGNORECASE),
        re.compile(r"([A-Z][a-zA-Z\s]+(?:,\s*[A-Z]{2}))(?:\s+[.…]|\s*$)", re.IGNORECASE),
    ]
    for p in patterns:
        m = p.search(snippet or "")
        if m:
            loc = m.group(1).strip()
            if len(loc) < 40:
                return loc
    return "Remote / Unspecified"


def _identify_source(url: str) -> str:
    domain = urlparse(url).netloc.lower()
    for pattern, name in JOB_SOURCE_DOMAINS.items():
        if pattern in domain:
            return name
    clean = re.sub(r"^www\d*\.", "", domain)
    parts = clean.split(".")
    return parts[0].title() if parts else clean.title()
