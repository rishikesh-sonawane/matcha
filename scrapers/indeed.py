import re
from typing import Any
from urllib.parse import parse_qs, urlparse

import cloudscraper
import requests
from bs4 import BeautifulSoup
from ddgs import DDGS

from .utils import resilient_get


def resolve_indeed_url(url: str) -> str:
    """Resolve Indeed tracking URLs to actual job page URLs."""
    parsed = urlparse(url)
    params = parse_qs(parsed.query)

    if "rc/clk" in url:
        jk = params.get("jk", [None])[0]
        if jk:
            return f"https://in.indeed.com/viewjob?jk={jk}"

    if "pagead/clk" in url:
        jk = params.get("jk", [None])[0]
        if jk:
            return f"https://in.indeed.com/viewjob?jk={jk}"
        try:
            scraper = cloudscraper.create_scraper()
            resp = scraper.head(url, allow_redirects=True, timeout=10)
            if resp.url and "indeed.com" in resp.url and "pagead/clk" not in resp.url:
                return resp.url
        except Exception:
            pass

    return url


INDIA_JOB_DOMAINS: dict[str, str] = {
    "in.indeed.com": "India",
    "in.indeed.com/m/careers": "India",
}


def _fetch_indeed_page(url: str, params: dict[str, str]) -> requests.Response:
    """Try resilient_get first, fall back to cloudscraper."""
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
    except Exception:
        pass
    scraper = cloudscraper.create_scraper()
    return scraper.get(url, params=params, timeout=20, allow_redirects=True)


def _parse_indeed_card(card: Any, location: str) -> dict[str, str] | None:
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
                link = resolve_indeed_url(href)
            else:
                link = resolve_indeed_url(f"https://in.indeed.com{href}")

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
    except Exception:
        return None


def _search_indeed_via_ddgs(query: str, location: str) -> list[dict[str, str]]:
    """Fallback: search Indeed job listings via DuckDuckGo API."""
    search_q = f"site:in.indeed.com/viewjob {query}"
    if location:
        search_q += f" {location}"

    try:
        with DDGS() as ddgs:
            raw = ddgs.text(search_q, max_results=15)
    except Exception:
        return []

    jobs: list[dict[str, str]] = []
    seen: set[str] = set()

    for item in raw:
        url = item.get("href", "")
        title = item.get("title", "")
        body = item.get("body", "")

        if not url or not title:
            continue

        # Title format: "Job Title - Location - Indeed.com"
        clean_title = re.sub(
            r"\s*[-–|]\s*Indeed(\.com)?\s*$", "", title, flags=re.IGNORECASE
        ).strip()
        parts = re.split(r"\s*[-–|]\s*", clean_title)
        job_title = parts[0].strip() if parts else clean_title
        job_location = parts[1].strip() if len(parts) > 1 else ""

        stop_words = {
            "the",
            "a",
            "an",
            "is",
            "are",
            "was",
            "were",
            "be",
            "been",
            "being",
            "have",
            "has",
            "had",
            "do",
            "does",
            "did",
            "will",
            "would",
            "could",
            "should",
            "may",
            "might",
            "must",
            "shall",
            "can",
            "this",
            "that",
            "these",
            "those",
            "it",
            "its",
            "our",
            "their",
            "your",
            "my",
            "his",
            "her",
            "they",
            "we",
            "you",
            "he",
            "she",
            "and",
            "or",
            "but",
            "nor",
            "for",
            "with",
            "about",
            "between",
            "through",
            "during",
            "before",
            "after",
            "above",
            "below",
            "from",
            "up",
            "down",
            "of",
            "in",
            "on",
            "at",
            "by",
            "to",
            "into",
            "over",
            "under",
            "again",
            "further",
            "then",
            "once",
            "here",
            "there",
            "all",
            "each",
            "every",
            "both",
            "few",
            "more",
            "most",
            "some",
            "any",
            "no",
            "not",
            "only",
            "own",
            "same",
            "so",
            "than",
            "too",
            "very",
            "overview",
            "summary",
            "about",
            "description",
            "role",
            "position",
            "job",
            "apply",
            "learn",
            "join",
            "team",
            "via",
        }
        company = "Unknown"
        for pat in [
            (r"\b(at|by|via)\s+([A-Z][A-Za-z0-9\s&.]+?)(?:\s+[-–]|\s+(?:is|has|in)\s+|\.|$)", 2),
            (r"([A-Z][A-Za-z0-9\s&]+)\s+(?:is\s+)?(?:hiring|seeking|looking)", 1),
        ]:
            m = re.search(pat[0], body, re.IGNORECASE)
            if m:
                candidate = m.group(pat[1]).strip()
                first_word = candidate.split()[0].lower()
                if len(candidate) >= 3 and len(candidate) <= 50 and first_word not in stop_words:
                    company = candidate
                    break

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


def search_indeed_jobs(
    query: str,
    location: str = "",
    **kwargs: Any,
) -> list[dict[str, str]]:
    jobs: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    base_url = "https://in.indeed.com/jobs"
    params: dict[str, str] = {
        "q": query,
        "l": location or "",
    }

    resp = _fetch_indeed_page(base_url, params)
    if resp.status_code == 200:
        try:
            soup = BeautifulSoup(resp.text, "html.parser")
            cards = soup.select(".job_seen_beacon") or soup.select("[data-jk]")

            for card in cards:
                job = _parse_indeed_card(card, location)
                if job is None:
                    continue
                dedup_key = (job["title"].lower(), job["company"].lower())
                if dedup_key in seen:
                    continue
                seen.add(dedup_key)
                jobs.append(job)
        except Exception:
            pass

    if not jobs:
        jobs = _search_indeed_via_ddgs(query, location)

    return jobs
