import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

try:
    from ddgs import DDGS
except ImportError:
    DDGS = None  # type: ignore[assignment, misc]

from matcha.models import ScraperResult
from matcha.normalization import find_city_in_text
from matcha.sources.base import Source
from matcha.sources.constants import (
    ATS_PLATFORM_LABELS,
    COMPANY_EXTRACTION_PATTERNS,
    GENERIC_SUBDOMAIN_LABELS,
    MONTH_NAMES,
    NON_JOB_TITLE_PATTERNS,
    NON_JOB_URL_PATTERNS,
    SEARCH_PAGE_PATTERNS,
    SKIP_DOMAIN_PARTS,
    STOP_WORDS,
    URL_TLD_LABELS,
)

from .utils import (
    ddgs_text,
    has_query_relevance,
    is_homepage_url,
    limiter,
    resilient_get,
)

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

    # Pass 1: cheap gates only (no network). Collect rows that could be real
    # postings; the dead-link probe (network) runs once, in parallel, after.
    candidates: list[tuple[str, str, str, dict[str, Any]]] = []
    seen: set[str] = set()
    for row in rows:
        try:
            title = _clean_title(str(row.get("title") or ""))
            url = str(row.get("url") or "")
            text = str(row.get("text") or "")
            if not title or not url or url in seen:
                continue
            # Session 27: same junk gates as the DDGS path — Exa semantic
            # search can also return company homepages / unrelated postings.
            if is_homepage_url(url):
                continue
            if not has_query_relevance(title, text, query, location):
                continue
            if any(re.search(p, title) for p in NON_JOB_TITLE_PATTERNS):
                continue
            if days and _iso_older_than_days(str(row.get("publishedDate") or ""), days):
                continue
            seen.add(url)
            candidates.append((title, url, text, row))
        except (AttributeError, ValueError, TypeError) as e:
            logger.warning("Failed to parse Exa result: %s", e)
            continue

    if not candidates:
        return ScraperResult(jobs=[], source="Web Search", backend="exa", data_quality="partial")

    # Session 30: Exa returns stale ATS postings (404s, soft-404 error pages,
    # or links that redirect to the careers homepage once the posting
    # closes). Probe each surviving URL in parallel — a hung ATS must not
    # chain N×timeout inside the scraper batch budget. Only HARD dead signals
    # drop the row, so bot-walled-but-live postings (Indeed, WeWorkRemotely)
    # survive a 403.
    live: set[str] = set()
    with ThreadPoolExecutor(max_workers=min(6, len(candidates))) as pool:
        futures = {pool.submit(_url_is_live, url): url for _, url, _, _ in candidates}
        for future, url in ((f, futures[f]) for f in futures):
            if future.result():
                live.add(url)
            else:
                logger.info("Web Search: dropping dead posting link %s", url)

    jobs: list[dict[str, str]] = []
    for title, url, text, row in candidates:
        if url not in live:
            continue
        job: dict[str, Any] = {
            "title": title,
            # Session 30: Exa's ``author`` field is page-scraped noise
            # ("scale" for a Vodafone job, "Nandan Ganeyan" for GlobalLogic)
            # — derive the company from the posting's own host first
            # (opportunities.vodafone.com → Vodafone), falling back to
            # author/snippet only when the host is meaningless.
            "company": _extract_company_from_url(url)
            or str(row.get("author") or "").strip()
            or _extract_company(url, text, title),
            "location": _extract_location(text, url, title),
            "description": text[:1000],
            "url": url,
            # Session 28: every Web Search row is sourced "Web Search" —
            # the old per-row _identify_source ("Careers", "Foundit", …)
            # made source_counts disagree with the rows and flooded the
            # TUI source column with domain-derived names.
            "source": "Web Search",
        }
        if row.get("publishedDate"):
            job["listed"] = str(row["publishedDate"])[:10]
        if row.get("score") is not None:
            job["score"] = float(row["score"])
        jobs.append(job)

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
            # Session 23: shared helper — generous timeout + bounded retry, so
            # a transient ConnectTimeout/refused connection doesn't kill the
            # query (DDGS is a free metasearch; blips are normal).
            raw = ddgs_text(q, max_results=5, timelimit=timelimit, ddgs=DDGS)
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
                # Session 27: DDGS ``site:domain`` queries return company
                # HOMEPAGES as results (e.g. ``www.lever.co/?lang=fa``) — never
                # postings. A job page always has a real path.
                if is_homepage_url(url):
                    continue
                # Session 27: the generic ``{query} {location} career`` query
                # can surface career landing pages / unrelated postings — drop
                # rows that carry no query/location token and no role word.
                if not has_query_relevance(title, snippet, query, location):
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
                    # Session 28: consistent "Web Search" source (see Exa path).
                    "source": "Web Search",
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


def _extract_company_from_url(url: str) -> str:
    """Company name from a posting's own host, skipping ATS subdomains.

    ``koch.avature.net`` → Koch, ``opportunities.vodafone.com`` → Vodafone,
    ``jobs.sanofi.com`` → Sanofi. More trustworthy than page text, whose
    ``at/by`` patterns routinely capture the wrong noun ("at scale", "at
    OpenShift Certificatio") and than Exa's ``author`` field (a person's
    name, a snippet fragment…). Returns "" when the host is meaningless
    (``boards.greenhouse.io/<company>`` — the company lives in the path, not
    the host), so the caller can fall back to other signals.
    """
    domain = urlparse((url or "").strip()).netloc.lower()
    domain = re.sub(r"^www\d*\.", "", domain)
    labels = [label for label in domain.split(".") if label]
    if not labels:
        return ""
    # Walk left→right: skip TLDs (sanofi.com) and generic career-site
    # subdomains (opportunities.) until a real company label appears. A label
    # on a known ATS platform (koch.avature.net) is skipped too — the company
    # is the label BEFORE it, so returning it from the path would be wrong.
    # ``wd5.``-style Workday host prefixes (wd5.myworkdayjobs.com) carry no
    # company name either.
    for label in labels[:-1]:
        if label in URL_TLD_LABELS or label in GENERIC_SUBDOMAIN_LABELS:
            continue
        if label in ATS_PLATFORM_LABELS:
            continue
        if re.fullmatch(r"wd\d+", label):
            continue
        return label.title()
    # Only TLDs/generic/platform labels left: trust the last meaningful label
    # before any TLD, unless the whole host is a platform
    # (boards.greenhouse.io — the company lives in the path, not the host) or
    # carries only Workday host prefixes (wd5.myworkdayjobs.com).
    meaningful = [
        label
        for label in labels
        if label not in URL_TLD_LABELS
        and label not in GENERIC_SUBDOMAIN_LABELS
        and not re.fullmatch(r"wd\d+", label)
    ]
    if not meaningful or set(meaningful) <= ATS_PLATFORM_LABELS:
        return ""
    return meaningful[-1].title()


#: Body markers that mean a posting is closed even though the ATS returned
#: HTTP 200 (soft-404s — e.g. Avature shows "Page not found" with a 200).
_DEAD_BODY_MARKERS: tuple[str, ...] = (
    "page not found",
    "job not found",
    "posting not found",
    "position not found",
    "not found or expired",
    "no longer accepting",
    "no longer available",
    "has been removed",
    "has been filled",
    "job expired",
    "job has expired",
    "position has been filled",
    "we're sorry",
)

#: Path segments that mean a posting is dead even when the ATS returns a
#: non-404 status. Avature/Koch bounces a closed posting to a literal
#: ``/Error`` page and THEN 403s the request — the redirect is the dead
#: signal, the bot-wall status just hides it. Matched as whole path segments
#: (``/Error``, ``/not-found``) so a real job slug like ``/error-handling-
#: engineer`` or ``/errors-in-payments`` is never misread.
_DEAD_PATH_SEGMENTS: tuple[str, ...] = (
    "error",
    "errors",
    "not-found",
    "notfound",
    "page-not-found",
    "pagenotfound",
    "404",
    "expired",
    "job-expired",
    "job-expired-page",
    "jobnotfound",
    "job-not-found",
    "position-not-found",
    "posting-not-found",
    "vacancy-not-found",
    "no-longer-available",
)


def _has_dead_path_segment(path: str) -> bool:
    """True when any whole path segment names a dead-posting error page."""
    segments = [segment for segment in path.lower().split("/") if segment]
    return any(segment in _DEAD_PATH_SEGMENTS for segment in segments)


def _is_root_or_locale_path(path: str) -> bool:
    """True for a bare root path or a locale-prefix-only root (``/en``, ``/de/``).

    Expired postings bounce to the careers homepage — often a LOCALIZED one
    (``jobs.sanofi.com/en``), which ``is_homepage_url`` (bare root only) would
    miss. ``/en``/``/en-us``-style paths are homepages, not postings.
    """
    if path in ("", "/"):
        return True
    return bool(re.fullmatch(r"/([a-z]{2}|[a-z]{2}-[a-z]{2})(?:/)?", path))


def _url_is_live(url: str, timeout: float = 4.0) -> bool:
    """Conservative dead-link probe: False only for HARD dead signals.

    Drops a URL when it returns 404/410, when the redirect chain ends on a
    bare or locale-prefixed site root (the classic "posting closed → careers
    homepage" bounce), when it redirects to a literal dead-posting path
    (``/Error`` — Avature/Koch does this BEHIND a 403 bot wall, so the check
    runs for every status), or when a 200 response body carries a clear
    "not found / expired" marker (soft-404s). Everything else — 403/Cloudflare
    bot walls that DON'T redirect to an error path, 5xx, network errors,
    slow timeouts — is treated as alive, because blocking a scraper's probe
    is NOT proof the posting is gone (Indeed and WeWorkRemotely both 403
    curl, in place, with no error-page redirect).

    Reads only a bounded body prefix (the stream is closed right after), so
    a probe never downloads a whole ATS page.
    """
    try:
        resp = resilient_get(url, timeout=timeout, stream=True)
    except Exception as e:  # noqa: BLE001 — flaky network must not kill a live posting
        logger.debug("Dead-link probe failed for %s: %s", url, e)
        return True
    try:
        if resp.status_code in (404, 410):
            return False
        final_path = urlparse(resp.url).path
        orig_path = urlparse(url).path
        # Error-path redirects are dead regardless of status — they are the
        # bot-walled ATS's way of showing a closed posting (Koch → /Error, 403).
        # The orig-path guard (an error URL that arrived as-is, no redirect,
        # e.g. a requisition literally named "error") is intentionally kept.
        if _has_dead_path_segment(final_path) and not _has_dead_path_segment(orig_path):
            return False
        if resp.status_code < 400 and _is_root_or_locale_path(final_path):
            if not _is_root_or_locale_path(orig_path):
                return False
        if resp.status_code == 200:
            body = next(resp.iter_content(4096), b"").decode("utf-8", "replace").lower()
            if body and any(marker in body for marker in _DEAD_BODY_MARKERS):
                return False
    finally:
        resp.close()
    return True


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
    # Session 28: Exa highlights read like "in Managing cloud infrastructure"
    # — the loose regex below would return that garbage as the location and
    # the location filter would drop a real posting. Prefer a known city /
    # remote marker anywhere in title+URL+snippet first.
    known = find_city_in_text(f"{title} {url} {snippet}")
    if known:
        return known
    patterns = [
        re.compile(r"in\s+([A-Z][a-zA-Z\s]+(?:,\s*[A-Z]{2})?)", re.IGNORECASE),
        re.compile(r"([A-Z][a-zA-Z\s]+(?:,\s*[A-Z]{2}))(?:\s+[.…]|\s*$)", re.IGNORECASE),
    ]
    for p in patterns:
        m = p.search(snippet or "")
        if m:
            loc = m.group(1).strip()
            # A regex candidate is only trusted when it names a known city —
            # "in Managing cloud infrastructure" must not become a location.
            if len(loc) < 40 and find_city_in_text(loc):
                return loc
    return "Remote / Unspecified"
