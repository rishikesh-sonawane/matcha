import re
import requests
from bs4 import BeautifulSoup
from urllib.parse import quote, urlparse, parse_qs, unquote


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


INDIVIDUAL_JOB_PATTERNS = [
    r"/jobs/view/", r"/job/view/", r"/viewjob", r"/job/\d+",
    r"/employment/", r"/careers/", r"/job-opening/", r"/position/",
    r"/o/[a-zA-Z]", r"/jobs/\d+", r"-job-", r"/listings/",
]

SEARCH_PAGE_PATTERNS = [
    r"jobs\sin\s", r"jobs\savailable", r"Top\s+\d+", r"\d+\+?\s+.*jobs",
]


def search_web_for_jobs(query, location=""):
    jobs = []
    search_query = f"{query} {location}" if location else query

    urls = [
        f"https://html.duckduckgo.com/html/?q={quote(search_query)}",
        f"https://html.duckduckgo.com/html/?q={quote(query + ' hiring')}",
    ]

    for url in urls:
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            if resp.status_code != 200:
                continue

            soup = BeautifulSoup(resp.text, "html.parser")
            results = soup.select(".result")

            for result in results:
                try:
                    is_ad = bool(result.select_one(".badge--ad"))
                    if is_ad:
                        continue

                    title_el = result.select_one(".result__title a") or result.find("a")
                    snippet_el = result.select_one(".result__snippet")

                    if not title_el:
                        continue

                    raw_href = title_el.get("href", "")
                    actual_url = extract_url(raw_href)
                    title = title_el.get_text(strip=True)

                    if not title or not actual_url:
                        continue

                    if is_search_page(title, actual_url):
                        continue

                    is_individual = any(
                        re.search(p, actual_url, re.IGNORECASE)
                        for p in INDIVIDUAL_JOB_PATTERNS
                    )

                    if not is_individual:
                        domain = urlparse(actual_url).netloc.lower()
                        job_board_domains = [
                            "linkedin.com", "indeed.com", "glassdoor.com",
                            "monster.com", "ziprecruiter.com", "dice.com",
                            "simplyhired.com", "wellfound.com", "startup.jobs",
                            "greenhouse.io", "lever.co", "breezy.hr",
                            "workable.com", "bamboohr.com",
                        ]
                        if not any(d in domain for d in job_board_domains):
                            continue

                    snippet = snippet_el.get_text(strip=True) if snippet_el else ""

                    job = {
                        "title": clean_title(title),
                        "company": extract_company(actual_url, snippet, title),
                        "location": extract_location(snippet, actual_url, title),
                        "description": snippet[:1000],
                        "url": actual_url,
                        "source": identify_source(actual_url),
                    }
                    if job["title"] and not is_search_page(job["title"], actual_url):
                        jobs.append(job)
                except Exception:
                    continue

        except requests.RequestException:
            continue

        if jobs:
            break

    return jobs


def is_search_page(title, url):
    for p in SEARCH_PAGE_PATTERNS:
        if re.search(p, title, re.IGNORECASE):
            return True
    if re.search(r"/search\?", url, re.IGNORECASE):
        return True
    return False


def extract_url(raw_href):
    if not raw_href:
        return ""
    if raw_href.startswith("//"):
        raw_href = "https:" + raw_href
    parsed = urlparse(raw_href)
    if "duckduckgo.com" in parsed.netloc:
        qs = parse_qs(parsed.query)
        uddg = qs.get("uddg", [None])[0]
        if uddg:
            return unquote(uddg)
    return raw_href


def clean_title(title):
    title = re.sub(
        r"\s*[-–|]\s*(?:LinkedIn|Indeed|Glassdoor|Monster|ZipRecruiter).*",
        "", title, flags=re.IGNORECASE
    )
    title = re.sub(r"\s*[-–|]\s*(?:Hiring|Job|Opening|Vacancy).*", "", title, flags=re.IGNORECASE)
    return title.strip()


def extract_company(url, snippet, title):
    domain = urlparse(url).netloc.lower()
    domain = re.sub(r"^www\.", "", domain)

    patterns = [
        rf"(?:at|by)\s+([A-Z][A-Za-z0-9\s&.]+?)(?:\s+[-–]|\s+(?:is|has|in)\s+|$)",
        rf"([A-Z][A-Za-z0-9\s&]+)\s+(?:is\s+)?(?:hiring|seeking|looking)",
    ]
    for p in patterns:
        m = re.search(p, snippet, re.IGNORECASE)
        if m:
            return m.group(1).strip()

    return domain.split(".")[0].title()


def extract_location(snippet, url, title):
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


def identify_source(url):
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
    return domain.split(".")[0].title()
