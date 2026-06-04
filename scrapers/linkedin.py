from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

from .utils import resilient_get

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def search_linkedin_jobs(query, location=""):
    jobs = []
    loc = location if location else "United States"

    url = (
        f"https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
        f"?keywords={quote(query)}&location={quote(loc)}&f_TPR=r86400"
        f"&position=1&pageNum=0"
    )

    try:
        resp = resilient_get(url, headers=HEADERS, timeout=15)
        if resp.status_code != 200:
            return jobs

        soup = BeautifulSoup(resp.text, "html.parser")
        job_cards = soup.find_all("li")

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
                location = location_el.get_text(strip=True) if location_el else ""

                link = ""
                if link_el:
                    href = link_el.get("href", "")
                    link = href if href.startswith("http") else f"https://www.linkedin.com{href}"

                if title:
                    jobs.append(
                        {
                            "title": title,
                            "company": company,
                            "location": location,
                            "description": "",
                            "url": link,
                            "source": "LinkedIn",
                        }
                    )
            except Exception:
                continue

        return jobs

    except requests.RequestException:
        return jobs
