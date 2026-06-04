import re
import cloudscraper
from bs4 import BeautifulSoup
from urllib.parse import quote

INDIA_JOB_DOMAINS = {
    "in.indeed.com": "India",
    "in.indeed.com/m/careers": "India",
}


def search_indeed_jobs(query, location=""):
    scraper = cloudscraper.create_scraper()
    jobs = []
    seen = set()

    base_url = "https://in.indeed.com/jobs"
    params = {
        "q": query,
        "l": location or "",
    }

    try:
        resp = scraper.get(
            base_url, params=params, timeout=20, allow_redirects=True
        )
        if resp.status_code != 200:
            return jobs

        soup = BeautifulSoup(resp.text, "html.parser")
        cards = soup.select(".job_seen_beacon") or soup.select("[data-jk]")

        for card in cards:
            try:
                title_el = (
                    card.select_one("h3.jobTitle a span[title]")
                    or card.select_one("h3.jobTitle a")
                )
                company_el = card.select_one("[data-testid=company-name]")
                location_el = card.select_one("[data-testid=text-location]")
                salary_el = card.select_one("[data-testid*=salary]")
                link_el = (
                    card.select_one("a.jcs-JobTitle")
                    or card.find("a", href=True)
                )

                title = title_el.get_text(strip=True) if title_el else ""
                company = company_el.get_text(strip=True) if company_el else ""
                location_text = (
                    location_el.get_text(strip=True) if location_el else ""
                )
                salary = salary_el.get_text(strip=True) if salary_el else ""

                link = ""
                if link_el:
                    href = link_el.get("href", "")
                    if href.startswith("http"):
                        link = href
                    else:
                        link = f"https://in.indeed.com{href}"

                if not title:
                    continue

                dedup_key = (title.lower(), company.lower())
                if dedup_key in seen:
                    continue
                seen.add(dedup_key)

                description = salary
                snippet_el = card.select_one(
                    ".job-snippet"
                ) or card.select_one("[data-testid=attribute_snippet_testid]")
                if snippet_el:
                    description = (
                        snippet_el.get_text(strip=True)[:500] + " | " + salary
                        if salary
                        else snippet_el.get_text(strip=True)[:500]
                    )

                jobs.append({
                    "title": title,
                    "company": company,
                    "location": location_text or location or "India",
                    "description": description,
                    "url": link,
                    "source": "Indeed",
                })
            except Exception:
                continue

    except Exception:
        return jobs

    return jobs
