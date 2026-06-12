import logging
from typing import Any
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

from models import ScraperResult

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


def search_linkedin_jobs(
    query: str,
    location: str = "",
    **kwargs: Any,
) -> ScraperResult:
    errors: list[str] = []
    jobs: list[dict[str, str]] = []
    loc = location if location else "United States"

    days = max(1, kwargs.get("days") or 7)
    max_pages = kwargs.get("max_pages", 1)
    f_tpr = f"r{days * SECONDS_PER_DAY}"

    logger.info(
        "Searching LinkedIn: q=%s location=%s days=%s max_pages=%s", query, loc, days, max_pages
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
                        href = link_el.get("href", "")
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

        return ScraperResult(jobs=jobs, errors=errors, source="LinkedIn")

    except requests.RequestException as e:
        msg = f"LinkedIn request failed: {e}"
        logger.warning(msg)
        errors.append(msg)
        return ScraperResult(jobs=jobs, errors=errors, source="LinkedIn")
