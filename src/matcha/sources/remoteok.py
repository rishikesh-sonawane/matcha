import logging
import re
import time
from typing import Any

import requests

from matcha.models import ScraperResult
from matcha.sources.base import Source, probe_url
from matcha.sources.constants import STOP_WORDS

from .utils import resilient_get

logger = logging.getLogger(__name__)

HEADERS: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}


def search_remoteok_jobs(
    query: str,
    location: str = "",
    **kwargs: Any,
) -> ScraperResult:
    errors: list[str] = []
    jobs: list[dict[str, Any]] = []
    days = kwargs.get("days")
    cutoff = time.time() - (days * 86400) if days else 0
    query_lower = query.lower()
    query_terms = set(query_lower.split())

    significant_terms = {t for t in query_terms if t not in STOP_WORDS and len(t) > 1}
    if not significant_terms:
        significant_terms = query_terms

    logger.info("Searching RemoteOK: q=%s", query)
    try:
        resp = resilient_get(
            "https://remoteok.com/api",
            headers=HEADERS,
            timeout=15,
        )
        if resp.status_code != 200:
            msg = f"RemoteOK returned status {resp.status_code}"
            logger.warning(msg)
            errors.append(msg)
            return ScraperResult(
                jobs=jobs, errors=errors, source="RemoteOK", backend="api", data_quality="full"
            )

        data = resp.json()
        if not isinstance(data, list) or len(data) < 2:
            return ScraperResult(
                jobs=jobs, errors=errors, source="RemoteOK", backend="api", data_quality="full"
            )

        raw_jobs = data[1:]

        for item in raw_jobs:
            try:
                title = (item.get("position") or "").strip()
                company = (item.get("company") or "").strip()
                location_text = (item.get("location") or "Remote").strip()
                description = item.get("description") or ""
                url = item.get("url") or ""
                tags = [t.lower() for t in (item.get("tags") or [])]
                epoch = item.get("epoch") or item.get("date") or 0
                if cutoff and isinstance(epoch, (int, float)) and epoch < cutoff:
                    continue

                if not title:
                    continue

                title_lower = title.lower()
                title_words = set(re.findall(r"[a-z0-9+#.]+", title_lower))

                title_match = significant_terms & title_words
                tag_match = significant_terms & set(tags)

                if not title_match and not tag_match:
                    continue

                jobs.append(
                    {
                        "title": title,
                        "company": company,
                        "location": location_text,
                        "description": description[:1000],
                        "url": url,
                        "source": "RemoteOK",
                    }
                )
            except Exception as e:
                logger.warning("Failed to parse RemoteOK job: %s", e)
                continue

        return ScraperResult(
            jobs=jobs, errors=errors, source="RemoteOK", backend="api", data_quality="full"
        )

    except requests.RequestException as e:
        msg = f"RemoteOK request failed: {e}"
        logger.warning(msg)
        errors.append(msg)
        return ScraperResult(
            jobs=jobs, errors=errors, source="RemoteOK", backend="api", data_quality="full"
        )


class RemoteOKSource(Source):
    """RemoteOK — global remote-jobs API."""

    name = "remoteok"
    description = "RemoteOK — global remote-jobs API"
    backends = ["api"]
    tier = 0

    def check(self, config: dict[str, Any] | None = None) -> tuple[str, str]:
        status, msg = probe_url("https://remoteok.com/api")
        if status == "ok":
            self.active_backend = "api"
            return "ok", "RemoteOK API responding (HTTP 200)"
        self.active_backend = None
        return "error", f"RemoteOK unreachable: {msg}"

    def search(self, query: str, location: str = "", **kwargs: Any) -> ScraperResult:
        return search_remoteok_jobs(query, location, **kwargs)
