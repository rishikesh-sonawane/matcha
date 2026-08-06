import logging
import re
from typing import Any

try:
    from ddgs import DDGS
except ImportError:
    DDGS = None

from matcha.models import ScraperResult
from matcha.sources.base import Source
from matcha.sources.constants import NAUKRI_NON_JOB_PATHS, NON_JOB_TITLE_PATTERNS, STOP_WORDS

from .utils import limiter

logger = logging.getLogger(__name__)

HEADERS: dict[str, str] = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
}


def _is_job_url(url: str) -> bool:
    return bool(re.search(r"/job-listings-", url))


def search_naukri_jobs(
    query: str,
    location: str = "",
    **kwargs: Any,
) -> ScraperResult:
    errors: list[str] = []
    if DDGS is None:
        return ScraperResult(errors=["ddgs library not available"], source="Naukri", backend="ddgs")

    days = kwargs.get("days")
    timelimit = ""
    if days:
        if days <= 1:
            timelimit = "d"
        elif days <= 7:
            timelimit = "w"
        else:
            timelimit = "m"

    search_query = f"{query} {location}".strip()
    site_query = f"site:naukri.com {search_query}"
    seen_urls: set[str] = set()
    jobs: list[dict[str, str]] = []

    logger.info("Searching Naukri: q=%s location=%s", query, location)
    limiter.acquire("duckduckgo.com")
    try:
        with DDGS() as ddgs:
            raw = list(
                ddgs.text(site_query, max_results=20, timelimit=timelimit)
                if timelimit
                else ddgs.text(site_query, max_results=20)
            )
    except Exception as e:
        msg = f"Naukri DDGS search failed: {e}"
        logger.warning(msg)
        errors.append(msg)
        return ScraperResult(errors=errors, source="Naukri", backend="ddgs")

    for item in raw:
        try:
            url = item.get("href", "")
            title = item.get("title", "")
            body = item.get("body", "")

            if not title or not url or "naukri.com" not in url.lower():
                continue
            if any(p in url for p in NAUKRI_NON_JOB_PATHS):
                continue
            if any(re.search(p, title) for p in NON_JOB_TITLE_PATTERNS):
                continue
            if url in seen_urls:
                continue
            seen_urls.add(url)

            job = _build_job(title, body, url, location, query)
            if job and job["title"]:
                jobs.append(job)
        except Exception as e:
            logger.warning("Failed to parse Naukri result: %s", e)
            continue

    return ScraperResult(
        jobs=jobs, errors=errors, source="Naukri", backend="ddgs", data_quality="snippet"
    )


class NaukriSource(Source):
    """Naukri — jobs via DDGS site search."""

    name = "naukri"
    description = "Naukri — jobs via DDGS site search"
    backends = ["ddgs"]
    tier = 0

    def check(self, config: dict[str, Any] | None = None) -> tuple[str, str]:
        status, msg = self._ddgs_status(DDGS is not None)
        self.active_backend = "ddgs" if status == "ok" else None
        return status, msg

    def search(self, query: str, location: str = "", **kwargs: Any) -> ScraperResult:
        return search_naukri_jobs(query, location, **kwargs)


def _build_job(
    title: str,
    snippet: str,
    url: str,
    search_location: str,
    query: str,
) -> dict[str, str]:
    title_clean = _clean_title(title)
    if not title_clean or title_clean.startswith("naukri"):
        title_clean = _title_from_url(url) or title_clean or title

    company = _extract_company(url, snippet, title, title_clean)
    location = _extract_location(snippet, search_location)

    return {
        "title": title_clean or title,
        "company": company,
        "location": location,
        "description": snippet[:1000],
        "url": url,
        "source": "Naukri",
    }


def _clean_title(title: str) -> str:
    if not title:
        return ""
    title = re.sub(r"\s*[-–|]\s*Naukri\.?com.*", "", title, flags=re.IGNORECASE)
    title = re.sub(r"\s*[-–|]\s*(?:Hiring|Job|Opening|Vacancy).*", "", title, flags=re.IGNORECASE)
    title = re.sub(r"\s*[-–]\s*\d+.*", "", title)
    title = re.sub(r"Apply\s+To\s*\d*", "", title, flags=re.IGNORECASE).strip()
    title = re.sub(r"^\d+\s+", "", title)
    title = re.sub(r"\s+-\s+\d+.*", "", title)
    title = re.sub(r"\s*\d+\s*(?:Job|Vacanc)", "", title, flags=re.IGNORECASE)
    title = re.sub(r"\s*[-–|]\s*(?:naukri\s*(?:job|opening).*)", "", title, flags=re.IGNORECASE)
    title = re.sub(r"\s+Jobs\s+(?:In\s+)?.*", "", title, flags=re.IGNORECASE).strip()
    title = re.sub(r"\s+-\s+.*", "", title).strip()
    title = re.sub(
        r"^(?:How to|Career in|Internship In|Careers in)\s+.*", "", title, flags=re.IGNORECASE
    ).strip()
    return title.strip(" ,-–")


def _title_from_url(url: str) -> str:
    m = re.search(r"/job-listings-([^/]+?)-\d", url)
    if m:
        return m.group(1).replace("-", " ").title().strip()
    m = re.search(r"naukri\.com/([^/]+?)(?:-jobs|$)", url)
    if m:
        raw = m.group(1).replace("-", " ").title().strip()
        raw = re.sub(r"\s+In\s+\w.*", "", raw).strip()
        return raw
    return ""


def _extract_company(url: str, snippet: str, title: str, title_clean: str = "") -> str:
    from matcha.sources.constants import COMPANY_EXTRACTION_PATTERNS

    for p in COMPANY_EXTRACTION_PATTERNS:
        m = re.search(p, snippet or "")
        if m:
            candidate = m.group(1).strip()
            first_word = candidate.split()[0].lower()
            if len(candidate) >= 3 and first_word not in STOP_WORDS:
                return candidate

    m = re.search(r"^([A-Z][A-Za-z0-9\s&.]+?)\s+(?:is\s+)?hiring\s+", title or "", re.IGNORECASE)
    if m:
        return m.group(1).strip()

    m = re.search(r"/job-listings-[^/]+?-([a-z]+(?:-[a-z]+)*)-\d", url or "")
    if m:
        return m.group(1).replace("-", " ").title().strip()

    if title_clean:
        m = re.search(r"[-–]\s*([A-Z][A-Za-z0-9\s&.]+?)\s*$", title_clean)
        if m:
            return m.group(1).strip()

    return "Naukri"


def _extract_location(snippet: str, search_location: str) -> str:
    patterns = [
        re.compile(r"in\s+([A-Z][a-zA-Z\s]+(?:,\s*[A-Z]{2})?)", re.IGNORECASE),
        re.compile(r"([A-Z][a-zA-Z\s]+(?:,\s*[A-Z]{2}))(?:\s+[.…]|\s*$)", re.IGNORECASE),
    ]
    for p in patterns:
        m = re.search(p, snippet or "")
        if m:
            loc = m.group(1).strip()
            if len(loc) < 30:
                return loc
    return search_location or "India"
