import requests
import re

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}


def search_remoteok_jobs(query, location=""):
    jobs = []
    query_lower = query.lower()
    query_terms = set(query_lower.split())

    stop_words = {
        "a", "an", "the", "and", "or", "of", "in", "with", "for",
        "at", "to", "is", "are", "was", "were", "i", "my", "me",
        "we", "our", "you", "your", "it", "its", "on", "by",
        "as", "be", "but", "from", "not", "so", "up", "all",
    }
    significant_terms = {
        t for t in query_terms
        if t not in stop_words and len(t) > 1
    }

    if not significant_terms:
        significant_terms = query_terms

    try:
        resp = requests.get(
            "https://remoteok.com/api",
            headers=HEADERS,
            timeout=15,
        )
        if resp.status_code != 200:
            return jobs

        data = resp.json()
        if not isinstance(data, list) or len(data) < 2:
            return jobs

        raw_jobs = data[1:]

        for item in raw_jobs:
            try:
                title = (item.get("position") or "").strip()
                company = (item.get("company") or "").strip()
                location_text = (item.get("location") or "Remote").strip()
                description = item.get("description") or ""
                url = item.get("url") or ""
                tags = [t.lower() for t in (item.get("tags") or [])]
                date = item.get("date") or ""

                if not title:
                    continue

                title_lower = title.lower()
                title_words = set(re.findall(r"[a-z0-9+#.]+", title_lower))

                combined_tags = " ".join(tags)

                title_match = significant_terms & title_words
                tag_match = significant_terms & set(tags)
                desc_match = significant_terms & set(
                    re.findall(r"[a-z0-9+#.]+", (description + " " + combined_tags).lower())
                )

                if not title_match and not tag_match:
                    continue

                jobs.append({
                    "title": title,
                    "company": company,
                    "location": location_text,
                    "description": description[:1000],
                    "url": url,
                    "source": "RemoteOK",
                })
            except Exception:
                continue

        return jobs

    except requests.RequestException:
        return jobs
