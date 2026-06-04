import re
from urllib.parse import parse_qs, quote, unquote, urlparse

import requests
from bs4 import BeautifulSoup

from .utils import resilient_get

HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}


def search_naukri_jobs(query, location=""):
    jobs = []
    seen_urls = set()

    search_query = f"{query} {location}".strip()
    for q in [f"naukri.com {search_query}", f"naukri {search_query}"]:
        url = f"https://html.duckduckgo.com/html/?q={quote(q)}"

        try:
            resp = resilient_get(url, headers=HEADERS, timeout=15)
            if resp.status_code != 200:
                continue

            soup = BeautifulSoup(resp.text, "html.parser")

            for result in soup.select(".result"):
                try:
                    if result.select_one(".badge--ad"):
                        continue

                    title_el = result.select_one(".result__title a")
                    if not title_el:
                        continue

                    raw_href = title_el.get("href", "")
                    actual_url = extract_url(raw_href)
                    title = title_el.get_text(strip=True)

                    if not title or not actual_url or "naukri.com" not in actual_url.lower():
                        continue

                    if actual_url in seen_urls:
                        continue
                    seen_urls.add(actual_url)

                    snippet_el = result.select_one(".result__snippet")
                    snippet = snippet_el.get_text(strip=True) if snippet_el else ""

                    jobs.append(build_job(title, snippet, actual_url, location, query))
                except Exception:
                    continue

            if jobs:
                break
        except requests.RequestException:
            continue

    return jobs


def build_job(title, snippet, url, search_location, query):
    title_clean = clean_title(title)

    company = "Naukri"
    m = re.search(r"(\d+)\s+[Ii]n\s+([A-Z][A-Za-z0-9\s&.]+)", snippet)
    if m:
        company = m.group(2).strip()

    location = search_location or "India"
    m2 = re.search(r"[Ii]n\s+([A-Z][a-zA-Z\s]+(?:,\s*[A-Z]{2})?)", snippet)
    if m2:
        loc = m2.group(1).strip()
        if len(loc) < 30:
            location = loc

    return {
        "title": title_clean or title,
        "company": company,
        "location": location,
        "description": snippet[:1000],
        "url": url,
        "source": "Naukri",
    }


def clean_title(title):
    title = re.sub(r"\s*[-–|]\s*Naukri\.?com.*", "", title, flags=re.IGNORECASE)
    title = re.sub(r"\s*[-–|]\s*(?:Hiring|Job|Opening|Vacancy).*", "", title, flags=re.IGNORECASE)
    title = re.sub(r"\s*[-–]\s*\d+.*", "", title)
    title = re.sub(r"Apply\s+To\s*\d*", "", title, flags=re.IGNORECASE).strip()
    title = re.sub(r"^\d+\s+", "", title)
    title = re.sub(r"\s+-\s+\d+.*", "", title)
    title = re.sub(r"\s*\d+\s*(?:Job|Vacanc)", "", title, flags=re.IGNORECASE)
    return title.strip(" ,-–")


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
