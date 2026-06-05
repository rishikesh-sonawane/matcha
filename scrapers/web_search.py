import re
from typing import Any
from urllib.parse import urlparse

from ddgs import DDGS

INDIVIDUAL_JOB_PATTERNS: list[str] = [
    r"/jobs/view/",
    r"/job/view/",
    r"/viewjob",
    r"/job/\d+",
    r"/employment/",
    r"/careers/",
    r"/job-opening/",
    r"/position/",
    r"/o/[a-zA-Z]",
    r"/jobs/\d+",
    r"-job-",
    r"/listings/",
]

SEARCH_PAGE_PATTERNS: list[str] = [
    r"jobs\sin\s",
    r"jobs\savailable",
    r"Top\s+\d+",
    r"\d+\+?\s+.*jobs",
    r"Job\s+Vacancies",
]

AGGREGATE_URL_PATTERNS: list[str] = [
    r"/jobs(\?|$)",
    r"/jobs/.*-jobs-",
    r"\?f_",
    r"\?location",
]

NON_JOB_URL_PATTERNS: list[str] = [
    r"/auth/",
    r"/login",
    r"/signup",
    r"/register",
    r"/password/",
    r"/session/",
]


def _dedup_jobs(jobs: list[dict[str, str]]) -> list[dict[str, str]]:
    seen_urls: set[str] = set()
    result: list[dict[str, str]] = []
    for j in jobs:
        if j["url"] not in seen_urls:
            seen_urls.add(j["url"])
            result.append(j)
    return result


def search_web_for_jobs(
    query: str,
    location: str = "",
    **kwargs: Any,
) -> list[dict[str, str]]:
    jobs: list[dict[str, str]] = []

    # Search targeted job-board sites for high-quality individual job listings
    site_queries: list[str] = [
        f"site:linkedin.com/jobs/view {query} {location}",
        f"site:greenhouse.io {query} {location}",
        f"site:lever.co {query} {location}",
        f"site:jobs.ashbyhq.com {query} {location}",
        f"site:boards.greenhouse.io {query} {location}",
    ]
    # Fallback: general search for career pages
    site_queries.append(f"{query} {location} career")

    for q in site_queries:
        try:
            with DDGS() as ddgs:
                raw = ddgs.text(q, max_results=5)
        except Exception:
            continue

        for item in raw:
            try:
                title = item.get("title", "")
                url = item.get("href", "")
                snippet = item.get("body", "")

                if not title or not url:
                    continue
                if is_search_page(title, url):
                    continue
                if any(re.search(p, url, re.IGNORECASE) for p in NON_JOB_URL_PATTERNS):
                    continue

                job = {
                    "title": clean_title(title),
                    "company": extract_company(url, snippet, title),
                    "location": extract_location(snippet, url, title),
                    "description": snippet[:1000],
                    "url": url,
                    "source": identify_source(url),
                }
                if job["title"] and not is_search_page(job["title"], url):
                    jobs.append(job)
            except Exception:
                continue

        if len(jobs) >= 10:
            break

    return _dedup_jobs(jobs)


def is_search_page(title: str, url: str) -> bool:
    for p in SEARCH_PAGE_PATTERNS:
        if re.search(p, title, re.IGNORECASE):
            return True
    if re.search(r"/search\?", url, re.IGNORECASE):
        return True
    return False


def clean_title(title: str) -> str:
    title = re.sub(
        r"\s*[-–|]\s*(?:LinkedIn|Indeed|Glassdoor|Monster|ZipRecruiter).*",
        "",
        title,
        flags=re.IGNORECASE,
    )
    title = re.sub(r"\s*[-–|]\s*(?:Hiring|Job|Opening|Vacancy).*", "", title, flags=re.IGNORECASE)
    segments = re.split(r"\s*[-–|]\s*", title)
    return segments[0].strip() if segments[0].strip() else title.strip()


_SKIP_DOMAIN_PARTS: set[str] = {
    "www",
    "ww1",
    "ww2",
    "in",
    "uk",
    "de",
    "fr",
    "au",
    "ca",
    "br",
    "jp",
    "app",
    "careers",
    "jobs",
    "boards",
    "career",
    "join",
    "employment",
    "recruitment",
    "apply",
    "search",
    "job",
}


_STOP_WORDS: set[str] = {
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


def extract_company(url: str, snippet: str, title: str) -> str:
    patterns = [
        r"(?:at|by)\s+([A-Z][A-Za-z0-9\s&.]+?)(?:\s+[-–]|\s+(?:is|has|in)\s+|$)",
        r"([A-Z][A-Za-z0-9\s&]+)\s+(?:is\s+)?(?:hiring|seeking|looking)",
    ]
    for p in patterns:
        m = re.search(p, snippet or "", re.IGNORECASE)
        if m:
            candidate = m.group(1).strip()
            first_word = candidate.split()[0].lower()
            if len(candidate) >= 3 and first_word not in _STOP_WORDS:
                return candidate

    # Try title-based extraction: "X hiring Y" → X is the company
    m = re.search(r"^([A-Z][A-Za-z0-9\s&.]+?)\s+(?:is\s+)?hiring\s+", title or "", re.IGNORECASE)
    if m:
        return m.group(1).strip()

    domain = urlparse(url).netloc.lower()
    domain = re.sub(r"^www\d*\.", "", domain)
    parts = [p for p in domain.split(".") if p not in _SKIP_DOMAIN_PARTS]
    return parts[0].title() if parts else domain.split(".")[0].title()


def extract_location(snippet: str, url: str, title: str) -> str:
    patterns = [
        r"in\s+([A-Z][a-zA-Z\s]+(?:,\s*[A-Z]{2})?)",
        r"([A-Z][a-zA-Z\s]+(?:,\s*[A-Z]{2}))(?:\s+[.…]|\s*$)",
    ]
    for p in patterns:
        m = re.search(p, snippet, re.IGNORECASE)
        if m:
            loc = m.group(1).strip()
            if len(loc) < 40:
                return loc
    return "Remote / Unspecified"


def identify_source(url: str) -> str:
    domain = urlparse(url).netloc.lower()
    sources = {
        "linkedin.com": "LinkedIn",
        "indeed.com": "Indeed",
        "glassdoor.com": "Glassdoor",
        "monster.com": "Monster",
        "ziprecruiter.com": "ZipRecruiter",
        "dice.com": "Dice",
        "simplyhired.com": "SimplyHired",
        "wellfound.com": "Wellfound",
        "greenhouse.io": "Greenhouse",
        "lever.co": "Lever",
    }
    for pattern, name in sources.items():
        if pattern in domain:
            return name
    clean = re.sub(r"^www\d*\.", "", domain)
    parts = clean.split(".")
    return parts[0].title() if parts else clean.title()
