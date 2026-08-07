import logging
import re
from typing import Any
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

from matcha.models import ScraperResult
from matcha.sources.backends.opencli import _opencli_should_run, run_opencli
from matcha.sources.base import Source, probe_url

from .utils import resilient_get

logger = logging.getLogger(__name__)

HEADERS: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

SECONDS_PER_DAY: int = 86400

#: Ephemeral LinkedIn apply-session links (``/job-apply/<id>``) 404 for
#: everyone except the browser inside a live apply flow (verified live in
#: Session 20). Matcha always applies via the stable job page instead.
_JOB_APPLY_RE = re.compile(r"/job-apply/(\d+)")


def stable_apply_url(url: str, apply_url: str = "") -> str:
    """Return a stable LinkedIn apply URL.

    OpenCLI returns a canonical ``/jobs/view/<id>`` URL plus an ephemeral
    ``/job-apply/<id>`` apply link. The job page is the real apply
    destination, so ephemeral job-apply links are replaced with the
    canonical jobs/view URL; any other apply link passes through untouched.
    """
    candidate = (apply_url or url or "").strip()
    m = _JOB_APPLY_RE.search(candidate)
    if not m:
        return candidate
    if url:
        return url
    return f"https://www.linkedin.com/jobs/view/{m.group(1)}"


def search_linkedin_jobs(
    query: str,
    location: str = "",
    **kwargs: Any,
) -> ScraperResult:
    """Acquire LinkedIn jobs, preferring the consented OpenCLI backend.

    Phase 1 (strategy §6.3): when the user opted in (``linkedin_consent`` in
    config) and the OpenCLI browser bridge is healthy, search through the
    user's logged-in Chrome for rich cards (salary, listed date, stable
    URLs). If OpenCLI is consented but fails at call time, degrade to the
    guest API instead of returning empty (graceful degradation rule).
    """
    backend = kwargs.pop("backend", None)
    config = kwargs.pop("config", None)
    # An explicit backend= override is the caller opting in — it intentionally
    # skips the consent+health gate (the opencli search still falls back to
    # guest-api when it cannot run). Implicit routing below always gates.
    if backend is None:
        backend = "opencli" if _opencli_should_run(config, "linkedin") else "guest-api"
    if backend == "opencli":
        result = _search_linkedin_opencli(query, location, **kwargs)
        if result is not None:
            return result
        logger.info("OpenCLI LinkedIn unavailable at search time; falling back to guest API")
    return _search_linkedin_guest_api(query, location, **kwargs)


def _search_linkedin_opencli(
    query: str,
    location: str = "",
    **kwargs: Any,
) -> ScraperResult | None:
    """Run ``opencli linkedin search``; None = could not run (caller falls back)."""
    # F-08 (user-confirmed): blank location searches the home market.
    loc = location if location else "India"
    days = max(1, kwargs.get("days") or 7)
    limit = min(int(kwargs.get("limit") or 25), 100)

    args = [
        "linkedin",
        "search",
        query,
        "--location",
        loc,
        "--limit",
        str(limit),
        "--date-posted",
        _date_posted_flag(days),
    ]
    if kwargs.get("details"):
        args.append("--details")

    result = run_opencli(args, timeout=int(kwargs.get("timeout") or 60))
    if not result["ok"]:
        logger.warning("OpenCLI LinkedIn search failed: %s", result["error"])
        return None

    jobs = _parse_linkedin_rows(result["rows"], loc)
    data_quality = "full" if kwargs.get("details") else "partial"
    return ScraperResult(jobs=jobs, source="LinkedIn", backend="opencli", data_quality=data_quality)


def _date_posted_flag(days: int) -> str:
    """Map matcha's ``days`` filter onto LinkedIn's --date-posted set."""
    if days <= 7:
        return "week"
    if days <= 30:
        return "month"
    return "any"


def _parse_linkedin_rows(rows: list[dict[str, Any]], default_location: str) -> list[dict[str, Any]]:
    """Map OpenCLI LinkedIn search rows onto matcha job dicts.

    OpenCLI row shape: {rank, title, company, location, listed, salary, url}
    (+ description/apply_url when run with --details). Extra fields like
    salary/listed are kept for the Phase 1+ enrichment/data-quality work.
    """
    jobs: list[dict[str, Any]] = []
    for row in rows:
        title = str(row.get("title") or "").strip()
        if not title:
            continue
        job: dict[str, Any] = {
            "title": title,
            "company": str(row.get("company") or "").strip(),
            "location": str(row.get("location") or "").strip() or default_location,
            "description": str(row.get("description") or "").strip(),
            "url": str(row.get("url") or "").strip(),
            "source": "LinkedIn",
        }
        for extra in ("salary", "listed", "apply_url", "workplace_type", "job_type", "applicants"):
            if row.get(extra):
                job[extra] = str(row[extra]).strip()
        # Session 20: OpenCLI search rows can carry an ephemeral job-apply
        # link that 404s outside a live session — always keep the stable
        # jobs/view URL as the apply destination (and label it apply_url so
        # the detail panel + `o` open the real posting).
        job["apply_url"] = stable_apply_url(job.get("url", ""), job.get("apply_url", ""))
        jobs.append(job)
    return jobs


def _search_linkedin_guest_api(
    query: str,
    location: str = "",
    **kwargs: Any,
) -> ScraperResult:
    errors: list[str] = []
    jobs: list[dict[str, str]] = []
    # F-08 (user-confirmed): blank location searches the home market, not the US.
    loc = location if location else "India"

    days = max(1, kwargs.get("days") or 7)
    max_pages = kwargs.get("max_pages", 1)
    f_tpr = f"r{days * SECONDS_PER_DAY}"

    logger.info(
        "Searching LinkedIn (guest-api): q=%s location=%s days=%s max_pages=%s",
        query,
        loc,
        days,
        max_pages,
    )
    try:
        for page in range(max_pages):
            start = page * 25
            url = (
                f"https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
                f"?keywords={quote(query)}&location={quote(loc)}&f_TPR={f_tpr}"
                f"&start={start}"
            )

            resp = resilient_get(url, headers=HEADERS, timeout=15)
            if resp.status_code != 200:
                msg = f"LinkedIn page {page + 1} returned status {resp.status_code}"
                logger.warning(msg)
                errors.append(msg)
                break

            soup = BeautifulSoup(resp.text, "html.parser")
            job_cards = soup.find_all("li")

            if not job_cards:
                logger.info("LinkedIn page %d: no jobs found, stopping pagination", page + 1)
                break

            for card in job_cards:
                try:
                    title_el = card.select_one(".base-search-card__title") or card.find("h3")
                    company_el = card.select_one(".base-search-card__subtitle") or card.select_one(
                        ".job-search-card__company-name"
                    )
                    location_el = card.select_one(".job-search-card__location") or card.select_one(
                        ".base-search-card__location"
                    )
                    link_el = card.select_one("a.base-card__full-link") or card.find("a", href=True)

                    title = title_el.get_text(strip=True) if title_el else ""
                    company = company_el.get_text(strip=True) if company_el else ""
                    job_location = location_el.get_text(strip=True) if location_el else ""

                    link = ""
                    if link_el:
                        href = str(link_el.get("href", "") or "")
                        link = (
                            href if href.startswith("http") else f"https://www.linkedin.com{href}"
                        )

                    if title:
                        jobs.append(
                            {
                                "title": title,
                                "company": company,
                                "location": job_location,
                                "description": "",
                                "url": link,
                                "source": "LinkedIn",
                            }
                        )
                except (AttributeError, ValueError, TypeError) as e:
                    logger.warning("Failed to parse LinkedIn card: %s", e)
                    continue

            logger.info(
                "LinkedIn page %d: %d jobs parsed (total %d)", page + 1, len(job_cards), len(jobs)
            )

        return ScraperResult(
            jobs=jobs, errors=errors, source="LinkedIn", backend="guest-api", data_quality="snippet"
        )

    except requests.RequestException as e:
        msg = f"LinkedIn request failed: {e}"
        logger.warning(msg)
        errors.append(msg)
        return ScraperResult(
            jobs=jobs, errors=errors, source="LinkedIn", backend="guest-api", data_quality="snippet"
        )


class LinkedInSource(Source):
    """LinkedIn — OpenCLI (browser, consented) preferred, guest API fallback."""

    name = "linkedin"
    description = "LinkedIn — OpenCLI browser backend, guest API fallback"
    # Honest chain: only backends search actually implements. ddgs was listed
    # in Phase 0 but never wired into the search path — dropped so doctor
    # never claims a backend that cannot deliver jobs (strategy §6.3 table
    # updated to match).
    backends = ["opencli", "guest-api"]
    tier = 1  # login-gated: full results need a logged-in browser (or auth)

    def check(self, config: dict[str, Any] | None = None) -> tuple[str, str]:
        from matcha.sources.backends.opencli import consent_granted, opencli_status, opencli_summary

        opencli_hint = ""
        for backend in self.ordered_backends(config):
            if backend == "opencli":
                if not consent_granted(config, "linkedin"):
                    continue  # not opted in — skip without penalty
                st = opencli_status()
                if st.ready:
                    self.active_backend = "opencli"
                    return "ok", f"OpenCLI browser bridge connected (v{st.version})"
                opencli_hint = opencli_summary(st)
            elif backend == "guest-api":
                status, msg = probe_url(
                    "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
                    "?keywords=engineer&location=India&f_TPR=r604800&start=0"
                )
                if status == "ok":
                    self.active_backend = "guest-api"
                    return "ok", "LinkedIn guest API responding (HTTP 200)"
                if status == "warn":
                    self.active_backend = None
                    return (
                        "warn",
                        "LinkedIn is login / anti-bot gated; guest API results may be thin",
                    )
        self.active_backend = None
        if opencli_hint:
            return "warn", f"OpenCLI not connected ({opencli_hint}); LinkedIn unreachable"
        return "error", "LinkedIn unreachable via any backend"

    def search(self, query: str, location: str = "", **kwargs: Any) -> ScraperResult:
        return search_linkedin_jobs(query, location, **kwargs)
