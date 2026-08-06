import logging
import re
from typing import Any
from urllib.parse import parse_qs, urlparse

import cloudscraper
import requests
from bs4 import BeautifulSoup

try:
    from ddgs import DDGS
except ImportError:
    DDGS = None  # type: ignore[assignment, misc]

from matcha.models import ScraperResult
from matcha.sources.backends.opencli import _opencli_should_run, run_opencli
from matcha.sources.base import Source, probe_url

from .utils import limiter, resilient_get

logger = logging.getLogger(__name__)


def resolve_indeed_url(url: str, domain: str = "in.indeed.com") -> str:
    parsed = urlparse(url)
    params = parse_qs(parsed.query)

    if "rc/clk" in url:
        jk = params.get("jk", [None])[0]
        if jk:
            return f"https://{domain}/viewjob?jk={jk}"

    if "pagead/clk" in url:
        jk = params.get("jk", [None])[0]
        if jk:
            return f"https://{domain}/viewjob?jk={jk}"
        try:
            scraper = cloudscraper.create_scraper()
            resp = scraper.head(url, allow_redirects=True, timeout=10)
            if resp.url and "indeed.com" in resp.url and "pagead/clk" not in resp.url:
                return resp.url
        except Exception as e:
            logger.warning("pagead/clk redirect failed: %s", e)

    return url


def search_indeed_jobs(
    query: str,
    location: str = "",
    domain: str = "in.indeed.com",
    **kwargs: Any,
) -> ScraperResult:
    """Acquire Indeed jobs, preferring the consented OpenCLI backend.

    Phase 1 (strategy §6.3): the OpenCLI browser backend bypasses the
    anti-bot gate that breaks ``cloudscraper`` on Python 3.14 and yields
    salary + stable URLs. When consented but failing at call time, degrade
    to the HTML/DDGS path instead of returning empty.
    """
    backend = kwargs.pop("backend", None)
    config = kwargs.pop("config", None)
    # An explicit backend= override is the caller opting in — it intentionally
    # skips the consent+health gate (the opencli search still falls back to
    # html when it cannot run). Implicit routing below always gates.
    if backend is None:
        backend = "opencli" if _opencli_should_run(config, "indeed") else "html"
    if backend == "opencli":
        result = _search_indeed_opencli(query, location, **kwargs)
        if result is not None:
            return result
        logger.info("OpenCLI Indeed unavailable at search time; falling back to HTML")
    return _search_indeed_html(query, location, domain=domain, **kwargs)


def _search_indeed_opencli(
    query: str,
    location: str = "",
    **kwargs: Any,
) -> ScraperResult | None:
    """Run ``opencli indeed search``; None = could not run (caller falls back).

    Note: OpenCLI's Indeed adapter is hardcoded to the US site
    (clis/indeed/utils.js INDEED_ORIGIN = https://www.indeed.com). --location
    still filters results, but the index is US-global, not in.indeed.com.
    """
    days = kwargs.get("days")
    limit = min(int(kwargs.get("limit") or 25), 25)  # Indeed caps at one page

    args = ["indeed", "search", query, "--limit", str(limit)]
    if location:
        args += ["--location", location]
    if days:
        args += ["--fromage", str(_fromage_flag(days))]

    result = run_opencli(args, timeout=int(kwargs.get("timeout") or 60))
    if not result["ok"]:
        logger.warning("OpenCLI Indeed search failed: %s", result["error"])
        return None

    jobs = _parse_indeed_rows(result["rows"], location)
    return ScraperResult(jobs=jobs, source="Indeed", backend="opencli", data_quality="partial")


def _fromage_flag(days: int) -> int:
    """Map matcha's ``days`` filter onto Indeed's --fromage set (1/3/7/14)."""
    days = max(1, int(days))
    for allowed in (14, 7, 3, 1):
        if days >= allowed:
            return allowed
    return 14


def _parse_indeed_rows(rows: list[dict[str, Any]], default_location: str) -> list[dict[str, Any]]:
    """Map OpenCLI Indeed search rows onto matcha job dicts.

    OpenCLI row shape: {rank, id, title, company, location, salary, tags,
    url}. ``id`` is the Indeed jk (job key) used later by ``indeed job`` for
    enrichment; salary is kept for the Phase 1+ data-quality work.
    """
    jobs: list[dict[str, Any]] = []
    for row in rows:
        title = str(row.get("title") or "").strip()
        if not title:
            continue
        job: dict[str, Any] = {
            "title": title,
            "company": str(row.get("company") or "").strip(),
            "location": str(row.get("location") or "").strip() or default_location or "India",
            "description": str(row.get("salary") or "").strip(),
            "url": str(row.get("url") or "").strip(),
            "source": "Indeed",
        }
        if row.get("salary"):
            job["salary"] = str(row["salary"]).strip()
        if row.get("id"):
            job["job_key"] = str(row["id"]).strip()
        if row.get("tags"):
            job["tags"] = row["tags"]
        jobs.append(job)
    return jobs


def _fetch_indeed_page(url: str, params: dict[str, str]) -> requests.Response:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    try:
        resp = resilient_get(url, params=params, headers=headers, timeout=20)
        if resp.status_code == 200:
            return resp
    except Exception as e:
        logger.warning("resilient_get failed for Indeed: %s", e)
    scraper = cloudscraper.create_scraper()
    return scraper.get(url, params=params, timeout=20, allow_redirects=True)


def _parse_indeed_card(card: Any, location: str, domain: str) -> dict[str, str] | None:
    try:
        title_el = card.select_one("h3.jobTitle a span[title]") or card.select_one("h3.jobTitle a")
        company_el = card.select_one("[data-testid=company-name]")
        location_el = card.select_one("[data-testid=text-location]")
        salary_el = card.select_one("[data-testid*=salary]")
        link_el = card.select_one("a.jcs-JobTitle") or card.find("a", href=True)

        title = title_el.get_text(strip=True) if title_el else ""
        company = company_el.get_text(strip=True) if company_el else ""
        location_text = location_el.get_text(strip=True) if location_el else ""
        salary = salary_el.get_text(strip=True) if salary_el else ""

        if not title:
            return None

        link = ""
        if link_el:
            href = link_el.get("href", "")
            if href.startswith("http"):
                link = resolve_indeed_url(href, domain)
            else:
                link = resolve_indeed_url(f"https://{domain}{href}", domain)

        description = salary
        snippet_el = card.select_one(".job-snippet") or card.select_one(
            "[data-testid=attribute_snippet_testid]"
        )
        if snippet_el:
            description = (
                snippet_el.get_text(strip=True)[:500] + " | " + salary
                if salary
                else snippet_el.get_text(strip=True)[:500]
            )

        return {
            "title": title,
            "company": company,
            "location": location_text or location or "India",
            "description": description,
            "url": link,
            "source": "Indeed",
        }
    except (AttributeError, ValueError, TypeError) as e:
        logger.warning("Failed to parse Indeed card: %s", e)
        return None


def _search_indeed_via_ddgs(query: str, location: str) -> list[dict[str, str]]:
    search_q = f"site:in.indeed.com/viewjob {query}"
    if location:
        search_q += f" {location}"

    if DDGS is None:
        return []
    limiter.acquire("duckduckgo.com")
    try:
        with DDGS() as ddgs:
            raw = ddgs.text(search_q, max_results=15)
    except Exception as e:
        logger.warning("DDGS Indeed fallback failed: %s", e)
        return []

    from matcha.sources.constants import STOP_WORDS

    jobs: list[dict[str, str]] = []
    seen: set[str] = set()

    for item in raw:
        url = item.get("href", "")
        title = item.get("title", "")
        body = item.get("body", "")

        if not url or not title:
            continue

        clean_title = re.sub(
            r"\s*[-–|]\s*Indeed(\.com)?\s*$", "", title, flags=re.IGNORECASE
        ).strip()
        parts = re.split(r"\s+[-–|]\s+", clean_title)
        job_title = parts[0].strip() if parts else clean_title

        company = "Unknown"
        pat = r"\b(at|by|via)\s+([A-Z][A-Za-z0-9&. ]+?)(?:\s+[-–]|\s+(?:is|has|in)\s+|\.|$)"
        m = re.search(pat, body, re.IGNORECASE)
        if m:
            candidate = m.group(2).strip()
            first_word = candidate.split()[0].lower()
            if len(candidate) >= 3 and len(candidate) <= 50 and first_word not in STOP_WORDS:
                company = candidate

        if company == "Unknown" and len(parts) >= 3:
            candidate = parts[1].strip()
            first_word = candidate.split()[0].lower()
            if len(candidate) >= 3 and first_word not in STOP_WORDS:
                company = candidate

        if len(parts) >= 3:
            job_location = " - ".join(p.strip() for p in parts[2:])
        elif len(parts) == 2:
            job_location = parts[1].strip()
        else:
            job_location = ""

        jobs.append(
            {
                "title": job_title,
                "company": company,
                "location": job_location or location or "India",
                "description": body[:1000] if body else "",
                "url": url,
                "source": "Indeed",
            }
        )
        seen.add(url)

    return jobs


def _search_indeed_html(
    query: str,
    location: str = "",
    domain: str = "in.indeed.com",
    **kwargs: Any,
) -> ScraperResult:
    errors: list[str] = []
    jobs: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    backend = "html"  # may flip to "ddgs" after the fallback below

    base_url = f"https://{domain}/jobs"
    days = kwargs.get("days")
    max_pages = kwargs.get("max_pages", 1)
    params: dict[str, str] = {
        "q": query,
        "l": location or "",
    }
    if days:
        params["fromage"] = str(days)

    logger.info(
        "Searching Indeed (%s): q=%s location=%s days=%s max_pages=%s",
        domain,
        query,
        location,
        days,
        max_pages,
    )
    for page in range(max_pages):
        page_params = dict(params)
        if page > 0:
            page_params["start"] = str(page * 10)
        resp = _fetch_indeed_page(base_url, page_params)
        if resp.status_code != 200:
            logger.warning("Indeed page %d returned status %d", page + 1, resp.status_code)
            errors.append(f"Page {page + 1}: HTTP {resp.status_code}")
            break
        try:
            soup = BeautifulSoup(resp.text, "html.parser")
            cards = soup.select(".job_seen_beacon") or soup.select("[data-jk]")

            if not cards:
                logger.info("Indeed page %d: no job cards found, stopping pagination", page + 1)
                break

            for card in cards:
                job = _parse_indeed_card(card, location, domain)
                if job is None:
                    continue
                dedup_key = (job["title"].lower(), job["company"].lower())
                if dedup_key in seen:
                    continue
                seen.add(dedup_key)
                jobs.append(job)

            logger.info(
                "Indeed page %d: %d jobs parsed (total %d)", page + 1, len(cards), len(jobs)
            )
        except Exception as e:
            msg = f"Failed to parse Indeed HTML page {page + 1}: {e}"
            logger.warning(msg)
            errors.append(msg)
            break

    if not jobs:
        logger.info("Indeed HTML returned 0 jobs, falling back to DDGS")
        backend = "ddgs"
        jobs = _search_indeed_via_ddgs(query, location)

    data_quality = "snippet" if backend == "ddgs" else "partial"
    return ScraperResult(
        jobs=jobs, errors=errors, source="Indeed", backend=backend, data_quality=data_quality
    )


class IndeedSource(Source):
    """Indeed — OpenCLI (browser, consented) preferred, HTML/DDGS fallback."""

    name = "indeed"
    description = "Indeed — OpenCLI browser backend, HTML + DDGS fallback"
    backends = ["opencli", "html", "ddgs"]
    tier = 0

    def check(self, config: dict[str, Any] | None = None) -> tuple[str, str]:
        from matcha.sources.backends.opencli import consent_granted, opencli_status, opencli_summary

        opencli_hint = ""
        for backend in self.ordered_backends(config):
            if backend == "opencli":
                if not consent_granted(config, "indeed"):
                    continue  # not opted in — skip without penalty
                st = opencli_status()
                if st.ready:
                    self.active_backend = "opencli"
                    return "ok", f"OpenCLI browser bridge connected (v{st.version})"
                opencli_hint = opencli_summary(st)
            elif backend == "html":
                status, msg = probe_url("https://in.indeed.com/jobs?q=engineer&l=India")
                if status == "ok":
                    self.active_backend = "html"
                    return "ok", "Indeed India responding (HTTP 200)"
                if status == "warn":
                    self.active_backend = None
                    return "warn", "Indeed is anti-bot gated; DDGS fallback available"
            elif backend == "ddgs":
                status, msg = self._ddgs_status(DDGS is not None)
                if status == "ok":
                    self.active_backend = "ddgs"
                    return "ok", msg
        self.active_backend = None
        if opencli_hint:
            return "warn", f"OpenCLI not connected ({opencli_hint}); using fallbacks"
        return "error", "Indeed unreachable via any backend"

    def search(self, query: str, location: str = "", **kwargs: Any) -> ScraperResult:
        return search_indeed_jobs(query, location, **kwargs)
