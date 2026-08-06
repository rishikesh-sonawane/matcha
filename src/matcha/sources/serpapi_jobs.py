import logging
from typing import Any

import requests

from matcha.models import ScraperResult
from matcha.sources.base import Source

from .utils import resilient_get

logger = logging.getLogger(__name__)

SERPAPI_BASE: str = "https://serpapi.com/search.json"


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
                    related_links = item.get("related_links", []) or []

                    url = ""
                    for link in related_links:
                        if link.get("link"):
                            url = link["link"]
                            break

                    if not url:
                        for link in related_links:
                            if link.get("type") == "application" and link.get("link"):
                                url = link["link"]
                                break

                    jobs.append(
                        {
                            "title": title,
                            "company": company,
                            "location": location_text,
                            "description": description[:2000],
                            "url": url,
                            "source": "Google Jobs",
                        }
                    )
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
