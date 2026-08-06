"""Naukri — jobs via DDGS discovery, enriched from the real job pages.

Phase 1 (strategy §6.2): Naukri's preferred backend is ``job-page`` — parse
the real ``job-listings-*`` posting pages for genuine descriptions, salary,
experience, key skills and apply URLs instead of snippet guesses. DDGS
remains the link-discovery mechanism and the ``ddgs`` fallback backend.

Verified 2026-08-06 against a live ``www.naukri.com/job-listings-*`` page:

- Naukri serves a **client-rendered Next.js shell** (empty ``jobDetails``,
  no JSON-LD, no server-side description) to plain requests — the internal
  ``jobapi`` endpoints reject unauthenticated calls. So the page is fetched
  via the **Jina Reader render** (``https://r.jina.ai/<url>``) — the same
  zero-config pattern as ``enrichment.py`` — and parsed from its markdown.
- A direct HTML fetch is still attempted first (cheap, cached): if Naukri
  ever server-renders again, the embedded ``application/ld+json``
  JobPosting / ``__NEXT_DATA__`` data wins.
- Expired postings redirect to search pages ("Jobs In ... - N Job
  Vacancies") — detected and skipped so stale links never masquerade as
  jobs.

Rate limits: the anonymous Jina tier is aggressive, so at most
``_JOB_PAGE_MAX`` postings are fetched per batch (same cap philosophy as
``enrichment._JINA_MAX_JOBS``), each with a short timeout, fetched in
parallel (≤4 workers), and isolated per job — a failed fetch keeps the
snippet data and records ``enrich_error``.
"""

import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from bs4 import BeautifulSoup

try:
    from ddgs import DDGS
except ImportError:
    DDGS = None  # type: ignore[assignment, misc]

from matcha.models import ScraperResult
from matcha.sources.base import Source
from matcha.sources.constants import NAUKRI_NON_JOB_PATHS, NON_JOB_TITLE_PATTERNS, STOP_WORDS

from .utils import limiter, resilient_get

logger = logging.getLogger(__name__)

HEADERS: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

_JINA_BASE = "https://r.jina.ai/"
#: Cap on postings fetched per batch — the anonymous Jina tier is aggressively
#: rate-limited (same philosophy as enrichment._JINA_MAX_JOBS).
_JOB_PAGE_MAX = 8
_JOB_PAGE_TIMEOUT = 12
_JOB_PAGE_WORKERS = 4
#: The direct GET is a speculative (future-proof) probe — never let a slow
#: Naukri shell response starve the Jina render fallback inside one job's
#: time budget, so it gets a fraction of the per-fetch timeout.
_DIRECT_FETCH_TIMEOUT = 6
_MAX_DESCRIPTION = 3000
#: A real server-rendered posting page is much larger than the ~15–35 KB
#: client-side shell; below this size the direct fetch is a shell and the
#: parser must not waste time on it.
_DIRECT_FETCH_MIN_BYTES = 50_000

#: Common Indian cities (slug form) — used to split title/company/location out
#: of Naukri's ``job-listings-<title>-<company>-<city>-...-<exp>-<jobid>`` URLs.
_INDIAN_CITY_SLUGS: frozenset[str] = frozenset(
    {
        "bengaluru",
        "bangalore",
        "hyderabad",
        "secunderabad",
        "pune",
        "mumbai",
        "navi-mumbai",
        "thane",
        "kolkata",
        "chennai",
        "delhi",
        "new-delhi",
        "gurgaon",
        "gurugram",
        "noida",
        "ghaziabad",
        "faridabad",
        "ahmedabad",
        "surat",
        "vadodara",
        "jaipur",
        "udaipur",
        "jodhpur",
        "lucknow",
        "kanpur",
        "agra",
        "varanasi",
        "prayagraj",
        "allahabad",
        "indore",
        "bhopal",
        "jabalpur",
        "gwalior",
        "nagpur",
        "nashik",
        "aurangabad",
        "kolhapur",
        "solapur",
        "sangli",
        "rajkot",
        "bhavnagar",
        "jamnagar",
        "kochi",
        "cochin",
        "trivandrum",
        "thiruvananthapuram",
        "kozhikode",
        "calicut",
        "mangalore",
        "mangaluru",
        "mysore",
        "mysuru",
        "hubli",
        "dharwad",
        "belgaum",
        "coimbatore",
        "madurai",
        "salem",
        "trichy",
        "tiruchirappalli",
        "vellore",
        "tirupur",
        "erode",
        "vijayawada",
        "visakhapatnam",
        "vizag",
        "nellore",
        "kakinada",
        "guntur",
        "raipur",
        "ranchi",
        "jamshedpur",
        "patna",
        "bhubaneswar",
        "cuttack",
        "guwahati",
        "siliguri",
        "dehradun",
        "haridwar",
        "roorkee",
        "amritsar",
        "ludhiana",
        "jalandhar",
        "patala",
        "chandigarh",
        "panchkula",
        "mohali",
        "panipat",
        "karnal",
        "ambala",
        "meerut",
        "aligarh",
        "bareilly",
        "gorakhpur",
        "shimla",
        "srinagar",
        "jammu",
        "gangtok",
        "itanagar",
        "shillong",
        "agartala",
        "imphal",
        "aizawl",
        "kohima",
        "panaji",
        "margao",
        "ponda",
        "remote",
        "work-from-home",
        "wfh",
    }
)

_DESC_HEADING = re.compile(
    r"^(about (the )?job|job description|job details|role[:\-]?\s*responsibilities|"
    r"responsibilities|what you[\u2019']?ll do|key responsibilities)$",
    re.IGNORECASE,
)
_STOP_HEADING = re.compile(
    r"^(key skills?|skills required|skills|about company|about (the )?company|salary|"
    r"education|perks|benefits|how to apply|job opening details|requirements?|"
    r"qualifications|additional information|contact)$",
    re.IGNORECASE,
)
_SALARY_WITH_UNIT = re.compile(
    r"(?:₹|rs\.?|inr)?\s*([\d,]+(?:\.\d+)?)\s*(?:-|–|to)\s*([\d,]+(?:\.\d+)?)\s*"
    r"(lpa|lakhs?|lacs?|thousand|k|pa|per annum)\b",
    re.IGNORECASE,
)
_SALARY_RS = re.compile(
    r"(?:₹|rs\.?|inr)\s*([\d,]+(?:\.\d+)?)\s*(?:-|–|to)?\s*([\d,]+(?:\.\d+)?)?\s*"
    r"(lpa|lakhs?|lacs?)?\b",
    re.IGNORECASE,
)
_EXP_RANGE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(?:-|–|to)\s*(\d+(?:\.\d+)?)\s*(?:years|yrs|year|yr)\b",
    re.IGNORECASE,
)
_EXP_SINGLE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:years|yrs|year|yr)\b", re.IGNORECASE)
_LISTED_RELATIVE = re.compile(
    r"(?:posted|updated|published)\s*:?\s*([a-z0-9 ,:\-]{1,40}?"
    r"(?:ago|today|yesterday|just now))",
    re.IGNORECASE,
)
_LISTED_DATE = re.compile(
    r"(?:posted|updated|published)\s*:?\s*"
    r"((?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d{1,2}"
    r"(?:,?\s+\d{4})?)",
    re.IGNORECASE,
)
_APPLY_LINK = re.compile(r"\[(?:apply|apply now|easy apply)\]\((https?://[^)\s]+)\)", re.IGNORECASE)
_APPLY_URL_LINK = re.compile(
    r"\[[^\]]*\]\((https?://[^)\s]*(?:apply|jobs/apply)[^)\s]*)\)", re.IGNORECASE
)

#: Rendered-page lines that look like content/meta, never like a job title.
_TITLE_ARTIFACTS = re.compile(
    r"^(employment type|job description|job details|responsibilities|about the job|"
    r"key skills?|skills required|##|###|\d+[.)]\s|full[- ]?time|part[- ]?time)",
    re.IGNORECASE,
)

#: Generic company words used to recover multi-word company slugs.
_GENERIC_COMPANY_WORDS: frozenset[str] = frozenset(
    {
        "services",
        "solutions",
        "technologies",
        "technology",
        "systems",
        "labs",
        "consultancy",
        "consulting",
        "group",
        "global",
        "digital",
        "india",
        "infotech",
        "ventures",
    }
)


def _plain(line: str) -> str:
    """Strip Jina markdown emphasis/ATX markers so heading regexes can match."""
    return line.lstrip("#").strip("* ").strip()


def _is_job_url(url: str) -> bool:
    return bool(re.search(r"/job-listings-", url))


def search_naukri_jobs(
    query: str,
    location: str = "",
    **kwargs: Any,
) -> ScraperResult:
    """Acquire Naukri jobs, preferring the job-page backend.

    Phase 1 (strategy §6.2): DDGS discovers candidate links; the ``job-page``
    backend then fetches each real ``job-listings-*`` posting and parses the
    genuine fields (description/salary/experience/skills/apply URL). The
    ``ddgs`` backend returns the raw snippets only. Any page failure keeps the
    snippet job — a bad posting never takes the batch down.
    """
    backend = kwargs.pop("backend", None)
    if backend is None:
        backend = "job-page"

    result = _search_naukri_ddgs(query, location, **kwargs)
    if backend == "job-page" and result.jobs:
        _enrich_with_job_pages(result, **kwargs)
    return result


def _search_naukri_ddgs(
    query: str,
    location: str = "",
    **kwargs: Any,
) -> ScraperResult:
    """DDGS ``site:naukri.com`` discovery → snippet-level jobs."""
    errors: list[str] = []
    if DDGS is None:
        return ScraperResult(errors=["ddgs library not available"], source="Naukri", backend="ddgs")

    days = kwargs.get("days")
    timelimit = ""
    if days:
        if days <= 1:
            timelimit = "d"
        elif days <= 7:
            timelimit = "w"
        else:
            timelimit = "m"

    search_query = f"{query} {location}".strip()
    site_query = f"site:naukri.com {search_query}"
    seen_urls: set[str] = set()
    jobs: list[dict[str, str]] = []

    logger.info("Searching Naukri: q=%s location=%s", query, location)
    limiter.acquire("duckduckgo.com")
    try:
        with DDGS() as ddgs:
            raw = list(
                ddgs.text(site_query, max_results=20, timelimit=timelimit)
                if timelimit
                else ddgs.text(site_query, max_results=20)
            )
    except Exception as e:
        msg = f"Naukri DDGS search failed: {e}"
        logger.warning(msg)
        errors.append(msg)
        return ScraperResult(errors=errors, source="Naukri", backend="ddgs")

    for item in raw:
        try:
            url = item.get("href", "")
            title = item.get("title", "")
            body = item.get("body", "")

            if not title or not url or "naukri.com" not in url.lower():
                continue
            if any(p in url for p in NAUKRI_NON_JOB_PATHS):
                continue
            if any(re.search(p, title) for p in NON_JOB_TITLE_PATTERNS):
                continue
            if url in seen_urls:
                continue
            seen_urls.add(url)

            job = _build_job(title, body, url, location, query)
            if job and job["title"]:
                jobs.append(job)
        except Exception as e:
            logger.warning("Failed to parse Naukri result: %s", e)
            continue

    return ScraperResult(
        jobs=jobs, errors=errors, source="Naukri", backend="ddgs", data_quality="snippet"
    )


def _enrich_with_job_pages(result: ScraperResult, **kwargs: Any) -> None:
    """Fetch the real posting pages for discovered jobs, in place.

    Only ``job-listings-*`` URLs are real postings; at most ``_JOB_PAGE_MAX``
    are fetched per batch (Jina rate-limit cap), in parallel, each isolated —
    a failing page keeps the snippet job and sets ``enrich_error``.
    """
    targets = [j for j in result.jobs if _is_job_url(str(j.get("url") or ""))][:_JOB_PAGE_MAX]
    if not targets:
        return

    timeout = int(kwargs.get("timeout") or _JOB_PAGE_TIMEOUT)
    with ThreadPoolExecutor(max_workers=min(_JOB_PAGE_WORKERS, len(targets))) as pool:
        futures = {pool.submit(_fetch_and_extract, j, timeout): j for j in targets}
        for future in as_completed(futures):
            job = futures[future]
            try:
                fields = future.result()
            except Exception as e:  # noqa: BLE001 — per-job isolation is the contract
                logger.warning("Naukri job-page worker raised: %s", e)
                fields = None
            if fields:
                _merge_job_fields(job, fields)
            else:
                job["enrich_error"] = "job page fetch/parse failed"
                job["data_quality"] = "snippet"  # provenance: snippet data kept

    enriched = sum(1 for j in result.jobs if j.get("enrich_source") == "job-page")
    if not enriched:
        # Every fetch failed (expired postings, network) — provenance stays
        # honest: discovery was ddgs, no page data was served.
        return
    qualities = {j.get("data_quality", "snippet") for j in result.jobs}
    if "full" in qualities:
        result.data_quality = "full"
    elif "partial" in qualities:
        result.data_quality = "partial"
    # The page fetches are the richest data source — report the backend that
    # actually served them (snippet discovery is subsumed under it).
    result.backend = "job-page"


def _fetch_and_extract(job: dict[str, Any], timeout: int) -> dict[str, Any] | None:
    url = str(job.get("url") or "")
    text = _fetch_job_page(url, timeout)
    if not text:
        return None
    return _extract_job_fields(text, url)


def _fetch_job_page(url: str, timeout: int) -> str | None:
    """Fetch one posting page: direct HTML first, Jina render as fallback."""
    try:
        resp = resilient_get(url, timeout=min(timeout, _DIRECT_FETCH_TIMEOUT), headers=HEADERS)
        if resp.status_code == 200 and _looks_server_rendered(resp.text):
            return resp.text
    except Exception as e:  # noqa: BLE001 — degraded to the render fallback
        logger.warning("Direct Naukri fetch failed for %s: %s", url, e)
    try:
        resp = resilient_get(_JINA_BASE + url, timeout=timeout)
        if resp.status_code == 200 and resp.text.strip():
            return resp.text
    except Exception as e:  # noqa: BLE001 — degraded to snippet job
        logger.warning("Jina render failed for %s: %s", url, e)
    return None


def _looks_server_rendered(html: str) -> bool:
    """True when a direct fetch carried real content, not the empty SPA shell."""
    if len(html) >= _DIRECT_FETCH_MIN_BYTES:
        return True
    return "application/ld+json" in html or "__NEXT_DATA__" in html


def _extract_job_fields(text: str, url: str) -> dict[str, Any] | None:
    """Extract job fields from a fetched page (embedded JSON or rendered text)."""
    if "application/ld+json" in text or "__NEXT_DATA__" in text:
        fields = _parse_embedded(text, url)
        if fields:
            return fields
    return _parse_rendered_text(text, url)


def _merge_job_fields(job: dict[str, Any], fields: dict[str, Any]) -> None:
    """Merge parsed page fields into a job dict (page data wins)."""
    for key in (
        "title",
        "company",
        "location",
        "salary",
        "experience",
        "keyskills",
        "listed",
        "apply_url",
    ):
        value = fields.get(key)
        if not value:
            continue
        if key == "title" and not _is_usable_title(str(value)):
            continue  # keep the snippet title over a section-label artifact
        job[key] = value
    desc = fields.get("description")
    if desc:
        job["description"] = desc[:_MAX_DESCRIPTION]
        job["data_quality"] = "full"
    else:
        job["data_quality"] = "partial"
    job["enrich_source"] = "job-page"


#
# Embedded-JSON parsing (direct server-rendered pages — future-proof path)
#


def _parse_embedded(text: str, url: str) -> dict[str, Any] | None:
    soup = BeautifulSoup(text, "html.parser")

    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or script.get_text() or "")
        except (json.JSONDecodeError, TypeError):
            continue
        blocks = data if isinstance(data, list) else [data]
        for block in blocks:
            if isinstance(block, dict) and str(block.get("@type") or "").lower() == "jobposting":
                fields = _extract_from_jobposting(block, url)
                if fields:
                    return fields

    next_data_script = soup.find("script", id="__NEXT_DATA__")
    if next_data_script:
        try:
            data = json.loads(next_data_script.string or next_data_script.get_text() or "")
        except (json.JSONDecodeError, TypeError):
            data = None
        if isinstance(data, dict):
            fields = _extract_from_next_data(data, url)
            if fields:
                return fields
    return None


def _extract_from_jobposting(ld: dict[str, Any], url: str) -> dict[str, Any] | None:
    """Map a schema.org JobPosting JSON-LD block onto job fields."""
    title = str(ld.get("title") or ld.get("name") or "").strip()
    if not title:
        return None
    fields: dict[str, Any] = {"title": title}
    desc = str(ld.get("description") or "").strip()
    if desc:
        fields["description"] = desc

    org = ld.get("hiringOrganization") or {}
    if isinstance(org, dict) and str(org.get("name") or "").strip():
        fields["company"] = str(org["name"]).strip()

    loc = ld.get("jobLocation") or {}
    if isinstance(loc, dict):
        address = loc.get("address") or {}
        if isinstance(address, dict):
            parts = [
                str(address.get(k) or "").strip()
                for k in ("addressLocality", "addressRegion", "addressCountry")
            ]
            loc_str = ", ".join(p for p in parts if p)
            if loc_str:
                fields["location"] = loc_str

    if ld.get("datePosted"):
        fields["listed"] = str(ld["datePosted"])[:10]

    salary = ld.get("baseSalary") or {}
    if isinstance(salary, dict):
        # currency lives on the MonetaryAmount, the amount on its value block
        value = salary.get("value") or {}
        if isinstance(value, dict) and value.get("value") is not None:
            fields["salary"] = f"{salary.get('currency', '')} {value['value']}".strip()

    skills = ld.get("skills")
    if isinstance(skills, list) and skills:
        fields["keyskills"] = ", ".join(str(s) for s in skills)

    apply_url = ld.get("directApply") or ld.get("url")
    if isinstance(apply_url, str) and apply_url.startswith("http"):
        fields["apply_url"] = apply_url

    if url and not fields.get("company"):
        slug_company = _company_from_slug(url)
        if slug_company:
            fields["company"] = slug_company
    return fields


def _extract_from_next_data(data: dict[str, Any], url: str) -> dict[str, Any] | None:
    """Walk a Next.js ``__NEXT_DATA__`` tree for the job-details blob."""
    blob = _find_job_blob(data)
    if not blob:
        return None
    title = str(blob.get("title") or blob.get("jobTitle") or blob.get("job_title") or "").strip()
    if not title:
        return None
    fields: dict[str, Any] = {"title": title}

    desc = blob.get("jobDescription") or blob.get("description")
    if isinstance(desc, str) and desc.strip():
        fields["description"] = desc.strip()
    company = blob.get("companyName") or blob.get("company")
    if isinstance(company, str) and company.strip():
        fields["company"] = company.strip()
    location = blob.get("jobLocation") or blob.get("location")
    if isinstance(location, str) and location.strip():
        fields["location"] = location.strip()
    elif isinstance(location, dict):
        address = location.get("address") or {}
        if isinstance(address, dict):
            parts = [
                str(address.get(k) or "").strip()
                for k in ("addressLocality", "addressRegion", "addressCountry")
            ]
            loc_str = ", ".join(p for p in parts if p)
            if loc_str:
                fields["location"] = loc_str

    for src, dst in (("salary", "salary"), ("keySkills", "keyskills")):
        value = blob.get(src)
        if isinstance(value, str) and value.strip():
            fields[dst] = value.strip()
        elif isinstance(value, list) and value:
            fields[dst] = ", ".join(str(v) for v in value)
    exp_parts = [str(blob.get(k) or "").strip() for k in ("minExperience", "maxExperience")]
    exp_parts = [p for p in exp_parts if p]
    if exp_parts:
        fields["experience"] = "-".join(exp_parts)

    listed = (
        blob.get("createdDate")
        or blob.get("createdOn")
        or blob.get("listedDate")
        or blob.get("postedDate")
    )
    if isinstance(listed, str) and listed.strip():
        fields["listed"] = listed.strip()[:10]

    apply_url = blob.get("applyUrl") or blob.get("applyURL") or blob.get("apply_url")
    if isinstance(apply_url, str) and apply_url.startswith("http"):
        fields["apply_url"] = apply_url

    if url and not fields.get("company"):
        slug_company = _company_from_slug(url)
        if slug_company:
            fields["company"] = slug_company
    return fields


def _find_job_blob(obj: Any) -> dict[str, Any] | None:
    """Recursively find the job-details dict inside an arbitrary JSON tree."""
    if isinstance(obj, dict):
        if ("jobDescription" in obj or "description" in obj) and any(
            k in obj for k in ("title", "jobTitle", "job_title")
        ):
            return obj
        for value in obj.values():
            found = _find_job_blob(value)
            if found:
                return found
    elif isinstance(obj, list):
        for value in obj:
            found = _find_job_blob(value)
            if found:
                return found
    return None


#
# Rendered-markdown parsing (Jina Reader — the live zero-config path)
#


def _parse_rendered_text(text: str, url: str) -> dict[str, Any] | None:
    """Parse Jina-reader markdown of a live Naukri job page into job fields."""
    if _is_search_page_render(text):
        logger.info("Naukri page for %s redirected to a search page; skipping", url)
        return None
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if lines and lines[0].lower().startswith("title:"):
        # Jina preamble: Title / URL Source / Markdown Content
        lines = lines[3:]
    if not lines:
        return None
    top = "\n".join(lines[:60])

    fields: dict[str, Any] = {}
    title = _extract_render_title(lines, url)
    if title:
        fields["title"] = title
    company = _extract_render_company(lines, url)
    if company:
        fields["company"] = company
    location = _extract_render_location(lines, url)
    if location:
        fields["location"] = location
    description = _extract_render_description(lines)
    if description:
        fields["description"] = description
    salary = _extract_salary(top)
    if salary:
        fields["salary"] = salary
    experience = _extract_experience(top)
    if experience:
        fields["experience"] = experience
    skills = _extract_keyskills(lines)
    if skills:
        fields["keyskills"] = skills
    listed = _extract_listed(top)
    if listed:
        fields["listed"] = listed
    apply_url = _extract_apply_url(text)
    if apply_url:
        fields["apply_url"] = apply_url

    return fields or None


def _is_search_page_render(text: str) -> bool:
    """Detect Naukri's expired-posting redirect to a search listing page."""
    head = text[:1200].lower()
    if "job vacancies in" in head:
        return True
    if re.search(r"jobs in [a-z ,\-]+ - \d[\d,]*\s*(job )?vacanc", head):
        return True
    m = re.search(r"^title:\s*(.+)$", text[:600], re.IGNORECASE | re.MULTILINE)
    if m:
        title = m.group(1).lower()
        if "vacanc" in title and re.search(r"\d", title):
            return True
        if re.search(r"jobs in .+ - \d+", title):
            return True
    return False


def _extract_render_title(lines: list[str], url: str) -> str:
    for ln in lines[:12]:
        if not ln or ln.startswith("!") or ln.startswith("*") or ln.startswith("- "):
            continue
        if ln.startswith("#"):  # ATX markdown heading (e.g. "## Job description")
            continue
        if "naukri.com" in ln and "]" not in ln:
            continue
        candidate = ln
        m = re.match(r"^\[([^\]]+)\]\([^)]+\)$", ln)
        if m:
            candidate = m.group(1)
        candidate = _plain(candidate)
        if not candidate or len(candidate) > 120:
            continue
        if _DESC_HEADING.match(candidate) or _STOP_HEADING.match(candidate):
            continue  # a section label, not the job title
        candidate = _clean_title(candidate)
        if candidate:
            return candidate
    return _clean_title(_title_from_url(url)) or ""


def _extract_render_company(lines: list[str], url: str) -> str:
    for ln in lines[:20]:
        m = re.match(r"^\[([^\]]+)\]\((https?://[^)\s]+)\)$", ln)
        if not m:
            continue
        name = m.group(1).strip("*").strip()
        href = m.group(2)
        if not name or "naukri.com" not in href:
            continue
        if re.search(r"naukri\.com/(jobs|job-listings)", href):
            continue  # job link, not a company page
        return name[:80]
    return _company_from_slug(url)


def _extract_render_location(lines: list[str], url: str) -> str:
    for ln in lines[:25]:
        tokens = [t.strip() for t in ln.split(",")]
        tokens = [t for t in tokens if t]
        if not 1 <= len(tokens) <= 8:
            continue
        if not all(re.fullmatch(r"[A-Za-z][A-Za-z &.\-]{0,30}", t) for t in tokens):
            continue
        known = sum(1 for t in tokens if t.lower().replace("-", " ") in _INDIAN_CITY_SLUGS)
        if known and known >= len(tokens):
            return ", ".join(t.replace("-", " ").title() for t in tokens)
        if known and len(tokens) <= 3:
            return ", ".join(t.replace("-", " ").title() for t in tokens)
    return _locations_from_slug(url)


def _extract_render_description(lines: list[str]) -> str:
    start = None
    for i, ln in enumerate(lines[:400]):
        if _DESC_HEADING.match(_plain(ln)):
            start = i
            break
    if start is None:
        return ""
    chunks: list[str] = []
    total = 0
    for ln in lines[start + 1 :]:
        plain = _plain(ln)
        if _STOP_HEADING.match(plain):
            break
        if re.match(r"^!\[", ln):
            continue
        if total + len(ln) > _MAX_DESCRIPTION:
            chunks.append(ln[: _MAX_DESCRIPTION - total])
            total = _MAX_DESCRIPTION
            break
        chunks.append(ln)
        total += len(ln) + 1
    desc = " ".join(chunks).strip()
    return re.sub(r"\s+", " ", desc)[:_MAX_DESCRIPTION]


def _extract_salary(top: str) -> str:
    if re.search(r"not\s+disclosed", top, re.IGNORECASE):
        return "Not Disclosed"
    m = _SALARY_WITH_UNIT.search(top)
    if m:
        a = m.group(1).replace(",", "")
        b = m.group(2).replace(",", "")
        unit = m.group(3).upper() if m.group(3).lower() == "lpa" else m.group(3)
        return f"₹{a}-{b} {unit}".strip() if unit else f"₹{a}-{b}"
    m = _SALARY_RS.search(top)
    if m:
        a = m.group(1).replace(",", "")
        unit = (
            m.group(3).upper() if m.group(3) and m.group(3).lower() == "lpa" else (m.group(3) or "")
        )
        return f"₹{a} {unit}".strip() if unit else f"₹{a}"
    return ""


def _extract_experience(top: str) -> str:
    if re.search(r"\bfresher\b", top, re.IGNORECASE):
        return "Fresher"
    m = _EXP_RANGE.search(top)
    if m:
        return f"{m.group(1)}-{m.group(2)} Years"
    m = _EXP_SINGLE.search(top)
    if m:
        return f"{m.group(1)} Years"
    return ""


def _extract_keyskills(lines: list[str]) -> str:
    start = None
    for i, ln in enumerate(lines[:300]):
        if re.match(r"^(key skills?|skills required|skills)$", _plain(ln), re.IGNORECASE):
            start = i
            break
    if start is None:
        return ""
    skills: list[str] = []
    for ln in lines[start + 1 :]:
        if re.match(
            r"^(about company|salary|education|experience|employment type)$",
            _plain(ln),
            re.IGNORECASE,
        ):
            break
        if not ln or ln.startswith("*") or ln.startswith("-") or re.match(r"^!\[", ln):
            continue
        if re.match(r"^\[", ln):
            break
        cleaned = _plain(ln)
        if cleaned:
            skills.append(cleaned)
        if len(skills) > 30:
            break
    return ", ".join(skills)[:500]


def _extract_listed(top: str) -> str:
    m = _LISTED_RELATIVE.search(top)
    if m:
        return m.group(1).strip().strip(":").strip()
    m = _LISTED_DATE.search(top)
    if m:
        return m.group(1).strip().strip(":").strip()
    return ""


def _extract_apply_url(text: str) -> str:
    m = _APPLY_LINK.search(text)
    if m:
        return m.group(1)
    m = _APPLY_URL_LINK.search(text)
    if m:
        return m.group(1)
    return ""


def _is_usable_title(title: str) -> bool:
    """Reject section labels/artifacts so they never replace the snippet title."""
    t = title.lower()
    if len(t) < 2 or t.startswith("#"):
        return False
    if "job description" in t or "job details" in t:
        return False
    if _TITLE_ARTIFACTS.match(t):
        return False
    return not (_DESC_HEADING.match(t) or _STOP_HEADING.match(t))


#
# URL-slug helpers (fallbacks when the page text hides a field)
#


def _slug_tail_parts(url: str) -> list[str]:
    """``job-listings-<title>-<company>-<city>-...-<exp>-<jobid>`` → chunks."""
    m = re.search(r"/job-listings-(.+?)-(\d+)$", url)
    if not m:
        return []
    parts = m.group(1).split("-")
    return [
        p
        for p in parts
        if not re.fullmatch(r"\d+(?:\.\d+)?", p)
        and p.lower() not in {"to", "years", "year", "yrs", "yr", "fresher", "exp"}
    ]


def _company_from_slug(url: str) -> str:
    """Best-effort company name from the posting URL slug (last non-city chunk).

    Multi-word companies often end in generic words — fold in the preceding
    chunk(s) ("tata-consultancy-services" → "Tata Consultancy Services"); a
    role word like "developer" never folds (title/company boundary).
    """
    parts = _slug_tail_parts(url)
    while parts and parts[-1] in _INDIAN_CITY_SLUGS:
        parts.pop()
    if not parts:
        return ""
    take = 1
    if parts[-1] in _GENERIC_COMPANY_WORDS and len(parts) >= 2:
        take = 2
        if parts[-2] in _GENERIC_COMPANY_WORDS and len(parts) >= 3:
            take = 3
    company = "-".join(parts[-take:])
    return company.replace("-", " ").title().strip()


def _locations_from_slug(url: str) -> str:
    cities = [p for p in _slug_tail_parts(url) if p in _INDIAN_CITY_SLUGS]
    if not cities:
        return ""
    return ", ".join(p.replace("-", " ").title() for p in cities)


class NaukriSource(Source):
    """Naukri — real job-page parse via DDGS discovery; snippet fallback."""

    name = "naukri"
    description = "Naukri — job-page parse via DDGS discovery"
    backends = ["job-page", "ddgs"]
    tier = 0

    def check(self, config: dict[str, Any] | None = None) -> tuple[str, str]:
        """Hermetic availability check (network is verified at search time).

        ``job-page`` needs only requests + bs4 (always present); DDGS needs the
        ddgs library. This mirrors the other zero-config sources' library-based
        probes so ``matcha doctor`` stays fast and offline-safe.
        """
        for backend in self.ordered_backends(config):
            if backend == "job-page":
                self.active_backend = "job-page"
                return "ok", "Naukri job-page backend available (network checked at search time)"
            if backend == "ddgs":
                status, msg = self._ddgs_status(DDGS is not None)
                self.active_backend = "ddgs" if status == "ok" else None
                return status, msg
        self.active_backend = None
        return "error", "Naukri unavailable via any backend"

    def search(self, query: str, location: str = "", **kwargs: Any) -> ScraperResult:
        kwargs["backend"] = self.active_backend or "job-page"
        return search_naukri_jobs(query, location, **kwargs)


def _build_job(
    title: str,
    snippet: str,
    url: str,
    search_location: str,
    query: str,
) -> dict[str, str]:
    title_clean = _clean_title(title)
    if not title_clean or title_clean.startswith("naukri"):
        title_clean = _title_from_url(url) or title_clean or title

    company = _extract_company(url, snippet, title, title_clean)
    location = _extract_location(snippet, search_location)

    return {
        "title": title_clean or title,
        "company": company,
        "location": location,
        "description": snippet[:1000],
        "url": url,
        "source": "Naukri",
    }


def _clean_title(title: str) -> str:
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
    m = re.search(r"/job-listings-([^/]+?)-(\d)", url)
    if m:
        return m.group(1).replace("-", " ").title().strip()
    m = re.search(r"naukri\.com/([^/]+?)(?:-jobs|$)", url)
    if m:
        raw = m.group(1).replace("-", " ").title().strip()
        raw = re.sub(r"\s+In\s+\w.*", "", raw).strip()
        return raw
    return ""


def _extract_company(url: str, snippet: str, title: str, title_clean: str = "") -> str:
    from matcha.sources.constants import COMPANY_EXTRACTION_PATTERNS

    for p in COMPANY_EXTRACTION_PATTERNS:
        m = re.search(p, snippet or "")
        if m:
            candidate = m.group(1).strip()
            first_word = candidate.split()[0].lower()
            if len(candidate) >= 3 and first_word not in STOP_WORDS:
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


def _extract_location(snippet: str, search_location: str) -> str:
    patterns = [
        re.compile(r"in\s+([A-Z][a-zA-Z\s]+(?:,\s*[A-Z]{2})?)", re.IGNORECASE),
        re.compile(r"([A-Z][a-zA-Z\s]+(?:,\s*[A-Z]{2}))(?:\s+[.…]|\s*$)", re.IGNORECASE),
    ]
    for p in patterns:
        m = re.search(p, snippet or "")
        if m:
            loc = m.group(1).strip()
            if len(loc) < 30:
                return loc
    return search_location or "India"
