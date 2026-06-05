import re
from typing import Any

try:
    from ddgs import DDGS
except ImportError:
    DDGS = None

HEADERS: dict[str, str] = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
}

NON_JOB_PATHS: list[str] = [
    "/code360/",
    "/campus/",
    "/blog/",
    "/interview-",
    "/cloudgateway",
    "companies.naukri.com",
]


def _is_job_url(url: str) -> bool:
    return bool(re.search(r"/job-listings-", url))


def search_naukri_jobs(
    query: str,
    location: str = "",
    **kwargs: Any,
) -> list[dict[str, str]]:
    if DDGS is None:
        return []

    search_query = f"{query} {location}".strip()
    site_query = f"site:naukri.com {search_query}"
    seen_urls: set[str] = set()
    jobs: list[dict[str, str]] = []

    try:
        with DDGS() as ddgs:
            raw = list(ddgs.text(site_query, max_results=20))
    except Exception:
        return []

    for item in raw:
        try:
            url = item.get("href", "")
            title = item.get("title", "")
            body = item.get("body", "")

            if not title or not url or "naukri.com" not in url.lower():
                continue
            if any(p in url for p in NON_JOB_PATHS):
                continue
            if url in seen_urls:
                continue
            seen_urls.add(url)

            job = build_job(title, body, url, location, query)
            if job and job["title"]:
                jobs.append(job)
        except Exception:
            continue

    return jobs


def build_job(
    title: str,
    snippet: str,
    url: str,
    search_location: str,
    query: str,
) -> dict[str, str]:
    title_clean = clean_title(title)
    if not title_clean or title_clean.startswith("naukri"):
        title_clean = _title_from_url(url) or title_clean or title

    company = extract_company(url, snippet, title, title_clean)
    location = extract_location(snippet, search_location)

    return {
        "title": title_clean or title,
        "company": company,
        "location": location,
        "description": snippet[:1000],
        "url": url,
        "source": "Naukri",
    }


def clean_title(title: str) -> str:
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
        # Strip location suffix like "in Pune" → keep just the role
        raw = re.sub(r"\s+In\s+\w.*", "", raw).strip()
        return raw
    return ""


def _is_search_page(url: str) -> bool:
    return bool(re.search(r"-jobs-in-\w", url)) or "naukri.com/jobs?" in url


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
    "any",
    "no",
    "not",
    "only",
    "same",
    "so",
    "than",
    "too",
    "very",
    "overview",
    "summary",
    "description",
    "role",
    "position",
    "job",
    "apply",
    "learn",
    "join",
    "team",
    "via",
    "naukri",
}


def extract_company(url: str, snippet: str, title: str, title_clean: str = "") -> str:
    patterns = [
        r"(?:at|by)\s+([A-Z][A-Za-z0-9&.]+?)(?:\s+[-–]|\s+(?:is|has|in)\s+|$|\.)",
        r"([A-Z][A-Za-z0-9&]+)\s+(?:is\s+)?(?:hiring|seeking|looking)",
    ]
    for p in patterns:
        m = re.search(p, snippet or "", re.IGNORECASE)
        if m:
            candidate = m.group(1).strip()
            first_word = candidate.split()[0].lower()
            if len(candidate) >= 3 and first_word not in _STOP_WORDS:
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


def extract_location(snippet: str, search_location: str) -> str:
    patterns = [
        r"in\s+([A-Z][a-zA-Z\s]+(?:,\s*[A-Z]{2})?)",
        r"([A-Z][a-zA-Z\s]+(?:,\s*[A-Z]{2}))(?:\s+[.…]|\s*$)",
    ]
    for p in patterns:
        m = re.search(p, snippet or "", re.IGNORECASE)
        if m:
            loc = m.group(1).strip()
            if len(loc) < 30:
                return loc
    return search_location or "India"
