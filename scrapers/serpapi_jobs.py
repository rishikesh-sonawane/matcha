import requests

SERPAPI_BASE = "https://serpapi.com/search.json"


def search_serpapi_jobs(query, location=""):
    config = get_serpapi_config()
    api_key = config.get("serpapi_key")
    if not api_key:
        return []

    search_query = f"{query} job"
    if location:
        search_query += f" {location}"

    params = {
        "engine": "google_jobs",
        "q": search_query,
        "api_key": api_key,
        "hl": "en",
    }

    try:
        resp = requests.get(SERPAPI_BASE, params=params, timeout=15)
        if resp.status_code != 200:
            return []

        data = resp.json()
        error = data.get("error")
        if error:
            return []

        jobs_results = data.get("jobs_results", [])
        jobs = []

        for item in jobs_results:
            try:
                title = item.get("title") or ""
                company = item.get("company_name") or ""
                location_text = item.get("location") or "Remote"
                description = item.get("description") or ""
                via = item.get("via") or "Google Jobs"
                related_links = item.get("related_links", []) or []
                extensions = item.get("extensions", []) or []

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

                jobs.append({
                    "title": title,
                    "company": company,
                    "location": location_text,
                    "description": description[:2000],
                    "url": url,
                    "source": "Google Jobs",
                })
            except Exception:
                continue

        return jobs

    except requests.RequestException:
        return []


def check_serpapi_available():
    config = get_serpapi_config()
    return bool(config.get("serpapi_key"))


def get_serpapi_config():
    try:
        from config import load_config
        return load_config()
    except ImportError:
        return {}
