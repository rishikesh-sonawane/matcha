"""Canonical job normalization (strategy §7, §14).

Pipeline stage 3: turn each raw job dict into a canonical, filter-ready shape:

- ``listed_epoch`` — int epoch seconds of the posting time (age filter's
  authority), parsed from ``listed`` ("5 days ago", ISO-8601, "Jan 5, 2026"),
  ``epoch`` (RemoteOK), or an existing ``listed_epoch`` int.
- ``salary_int`` — upper-bound LPA int ("₹28-35 LPA" → 35, "₹7-12 Lacs" → 12,
  "₹1.2 Cr" → 120, "₹8,00,000 - 12,00,000" → 12). The display string stays
  untouched in ``salary``.
- ``city`` / ``region`` — synonym-canonicalized primary city ("Bengaluru" for
  bangalore/BLR) plus a coarse region ("Delhi NCR", "Maharashtra") used by the
  location filter's exact-city ≥ region fallback.
- ``remote_ok`` — bool; ``workplace`` mirrors the existing ``workplace_type``.

Everything is in place and additive — jobs keep their search data, and a
missing/unparseable value yields ``None``/``""`` rather than an error.
"""

import re
import time
from datetime import datetime, timezone
from typing import Any

# ---------------------------------------------------------------------------
# City / region synonyms
# ---------------------------------------------------------------------------

_CITY_SYNONYMS: dict[str, str] = {
    "pune": "Pune",
    "poonaw": "Pune",
    "bengaluru": "Bengaluru",
    "bangalore": "Bengaluru",
    "blr": "Bengaluru",
    "hyderabad": "Hyderabad",
    "secunderabad": "Hyderabad",
    "hyd": "Hyderabad",
    "mumbai": "Mumbai",
    "bombay": "Mumbai",
    "chennai": "Chennai",
    "madras": "Chennai",
    "kolkata": "Kolkata",
    "calcutta": "Kolkata",
    "delhi": "Delhi",
    "new delhi": "Delhi",
    "delhi ncr": "Delhi",
    "ncr": "Delhi",
    "gurgaon": "Gurugram",
    "gurugram": "Gurugram",
    "noida": "Noida",
    "ghaziabad": "Ghaziabad",
    "faridabad": "Faridabad",
    "kochi": "Kochi",
    "cochin": "Kochi",
    "thiruvananthapuram": "Thiruvananthapuram",
    "trivandrum": "Thiruvananthapuram",
    "mysuru": "Mysuru",
    "mysore": "Mysuru",
    "visakhapatnam": "Visakhapatnam",
    "vizag": "Visakhapatnam",
    "vijayawada": "Vijayawada",
    "jaipur": "Jaipur",
    "udaipur": "Udaipur",
    "jodhpur": "Jodhpur",
    "lucknow": "Lucknow",
    "kanpur": "Kanpur",
    "agra": "Agra",
    "ahmedabad": "Ahmedabad",
    "surat": "Surat",
    "vadodara": "Vadodara",
    "baroda": "Vadodara",
    "indore": "Indore",
    "bhopal": "Bhopal",
    "nagpur": "Nagpur",
    "nashik": "Nashik",
    "chandigarh": "Chandigarh",
    "amritsar": "Amritsar",
    "ludhiana": "Ludhiana",
    "dehradun": "Dehradun",
    "shimla": "Shimla",
    "srinagar": "Srinagar",
    "jammu": "Jammu",
    "goa": "Goa",
    "panaji": "Panaji",
    "patna": "Patna",
    "ranchi": "Ranchi",
    "jamshedpur": "Jamshedpur",
    "bhubaneswar": "Bhubaneswar",
    "guwahati": "Guwahati",
    "siliguri": "Siliguri",
    "raipur": "Raipur",
    "coimbatore": "Coimbatore",
    "madurai": "Madurai",
    "salem": "Salem",
    "trichy": "Trichy",
    "tiruchirappalli": "Trichy",
    "mangaluru": "Mangaluru",
    "mangalore": "Mangaluru",
    "kozhikode": "Kozhikode",
    "calicut": "Kozhikode",
    "remote": "Remote",
    "work from home": "Remote",
    "work-from-home": "Remote",
    "wfh": "Remote",
    "anywhere": "Remote",
    "telecommute": "Remote",
    "virtual": "Remote",
    "india": "India",
    "pan india": "India",
    "pan-india": "India",
    "all india": "India",
    "anywhere in india": "India",
}

_REGION_CITIES: dict[str, set[str]] = {
    "Maharashtra": {
        "pune",
        "mumbai",
        "nashik",
        "nagpur",
        "aurangabad",
        "kolhapur",
        "solapur",
        "navi mumbai",
        "thane",
    },
    "Karnataka": {
        "bengaluru",
        "bangalore",
        "mysuru",
        "mysore",
        "hubli",
        "dharwad",
        "mangaluru",
        "mangalore",
        "belgaum",
        "hubballi",
    },
    "Telangana": {"hyderabad", "secunderabad"},
    "Tamil Nadu": {
        "chennai",
        "coimbatore",
        "madurai",
        "salem",
        "trichy",
        "vellore",
        "erode",
        "tirupur",
    },
    "Kerala": {"kochi", "cochin", "thiruvananthapuram", "trivandrum", "kozhikode", "calicut"},
    "West Bengal": {"kolkata", "siliguri"},
    "Delhi NCR": {"delhi", "new delhi", "gurgaon", "gurugram", "noida", "ghaziabad", "faridabad"},
    "Gujarat": {"ahmedabad", "surat", "vadodara", "baroda", "rajkot"},
    "Rajasthan": {"jaipur", "udaipur", "jodhpur"},
    "Uttar Pradesh": {"noida", "lucknow", "kanpur", "agra", "varanasi"},
    "Madhya Pradesh": {"indore", "bhopal", "jabalpur", "gwalior"},
    "Punjab": {"amritsar", "ludhiana", "jalandhar"},
    "Chandigarh": {"chandigarh", "mohali", "panchkula"},
    "Bihar": {"patna"},
    "Odisha": {"bhubaneswar", "cuttack"},
    "Jharkhand": {"ranchi", "jamshedpur"},
    "Assam": {"guwahati"},
    "Uttarakhand": {"dehradun"},
    "Himachal Pradesh": {"shimla"},
    "Jammu & Kashmir": {"srinagar", "jammu"},
    "Andhra Pradesh": {"visakhapatnam", "vijayawada", "guntur", "nellore", "kakinada"},
    "Goa": {"goa", "panaji"},
    "Chhattisgarh": {"raipur"},
    "Remote": {"remote", "anywhere", "wfh", "work from home", "telecommute"},
}

_REMOTE_PAT = re.compile(
    r"\b(remote|work from home|work-from-home|wfh|telecommute|anywhere|virtual|hybrid|home based)\b",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# listed_epoch
# ---------------------------------------------------------------------------

_RELATIVE_AGO = re.compile(
    r"(\d+)\s*(seconds?|minutes?|hours?|days?|weeks?|months?|years?)\s+ago", re.IGNORECASE
)
_UNIT_DAYS = {
    "second": 0,
    "minute": 0,
    "hour": 0,
    "day": 1,
    "week": 7,
    "month": 30,
    "year": 365,
}
_JUST_NOW = re.compile(r"\bjust now\b", re.IGNORECASE)
_TODAY = re.compile(r"\b(today)\b", re.IGNORECASE)
_YESTERDAY = re.compile(r"\b(yesterday)\b", re.IGNORECASE)

_ISO_FORMATS = (
    "%Y-%m-%dT%H:%M:%S%z",
    "%Y-%m-%dT%H:%M:%S.%f%z",
    "%Y-%m-%d",
    "%d %b %Y",
    "%b %d, %Y",
    "%B %d, %Y",
    "%d %B %Y",
    "%d-%m-%Y",
    "%d/%m/%Y",
)


def _parse_relative_epoch(text: str) -> int | None:
    m = _RELATIVE_AGO.search(text)
    if m:
        num = int(m.group(1))
        unit = m.group(2).lower().rstrip("s")
        days = _UNIT_DAYS.get(unit, 0)
        return int(time.time() - num * days * 86400)
    if _JUST_NOW.search(text):
        return int(time.time())
    if _TODAY.search(text):
        return int(time.time() - 3600)
    if _YESTERDAY.search(text):
        return int(time.time() - 86400)
    return None


def _parse_iso_epoch(text: str) -> int | None:
    cleaned = re.sub(
        r"^(?:posted|published|updated|date)\s*:?\s*", "", text.strip(), flags=re.IGNORECASE
    ).replace("Z", "+00:00")
    for fmt in _ISO_FORMATS:
        try:
            dt = datetime.strptime(cleaned, fmt)
        except ValueError:
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp())
    return None


def normalize_listed_epoch(job: dict[str, Any]) -> int | None:
    """Epoch seconds of the posting time, or None when unknown/unparseable."""
    existing = job.get("listed_epoch")
    if existing is not None:
        try:
            return int(existing)
        except (TypeError, ValueError):
            return None
    raw = job.get("listed") or job.get("epoch") or job.get("listedDate") or ""
    if isinstance(raw, (int, float)):
        return int(raw)
    text = str(raw).strip()
    if not text:
        return None
    relative = _parse_relative_epoch(text)
    if relative is not None:
        return relative
    return _parse_iso_epoch(text)


# ---------------------------------------------------------------------------
# salary_int (LPA)
# ---------------------------------------------------------------------------

_SALARY_UNIT = re.compile(
    r"(?:₹|rs\.?|inr)?\s*([\d.]+)\s*(?:-|–|to)\s*([\d.]+)\s*(lpa|lakhs?|lacs?)\b",
    re.IGNORECASE,
)
_SALARY_UNIT_SINGLE = re.compile(
    r"(?:₹|rs\.?|inr)?\s*([\d.]+)\s*(lpa|lakh|lacs?|l)\b", re.IGNORECASE
)
_SALARY_CRORE = re.compile(
    r"(?:₹|rs\.?|inr)?\s*([\d.]+)\s*(?:-|–|to)?\s*([\d.]+)?\s*(cr|crores?)\b", re.IGNORECASE
)
_SALARY_AMOUNT = re.compile(
    r"(?:₹|rs\.?|inr)\s*([\d.]+)\s*(?:-|–|to)\s*(?:₹|rs\.?|inr)?\s*([\d.]+)", re.IGNORECASE
)
_SALARY_THOUSANDS = re.compile(
    r"(?:₹|rs\.?|inr)?\s*([\d.]+)\s*(?:-|–|to)?\s*([\d.]+)?\s*(k|thousand)\b", re.IGNORECASE
)
_MONTHLY_PAT = re.compile(r"per\s*month|monthly|/month|/mo\b|\bmonths?\b|\bpm\b", re.IGNORECASE)


def normalize_salary_int(salary: str) -> int | None:
    """Upper-bound LPA of a salary string, or None when unparseable.

    Handles "₹28-35 LPA", "8-13 LPA", "7-12 Lacs", "₹1.2 Cr", Indian annual
    amounts ("₹8,00,000 - ₹12,00,000"), per-month amounts (×12), and "₹30-40K
    per month". Bare numbers only count when currency-prefixed so "3-6 Years"
    experience never parses as salary.
    """
    if not salary:
        return None
    text = str(salary).replace(",", "")
    if re.search(r"not\s+disclosed|confidential|negotiable", text, re.IGNORECASE):
        return None

    m = _SALARY_UNIT.search(text)
    if m:
        return max(1, int(round(float(m.group(2)))))
    m = _SALARY_UNIT_SINGLE.search(text)
    if m:
        return max(1, int(round(float(m.group(1)))))
    m = _SALARY_CRORE.search(text)
    if m:
        value = float(m.group(2) or m.group(1))
        return max(1, int(round(value * 100)))
    # thousands before plain amounts so "₹30-40K per month" wins the K-unit
    # path (value in K × 12 months × 1000 ₹ / 100_000 ₹-per-LPA)
    m = _SALARY_THOUSANDS.search(text)
    if m and _MONTHLY_PAT.search(text):
        value = float(m.group(2) or m.group(1))
        return max(1, int(round(value * 12 / 100)))
    m = _SALARY_AMOUNT.search(text)
    if m:
        value = float(m.group(2))
        if _MONTHLY_PAT.search(text):
            value *= 12
        return max(1, int(round(value / 100_000)))
    return None


# ---------------------------------------------------------------------------
# City / region / remote
# ---------------------------------------------------------------------------


def normalize_city(location: str) -> str:
    """Primary city of a location string, synonym-canonicalized ("" if none)."""
    if not location:
        return ""
    loc = str(location).lower().strip()
    for key in sorted(_CITY_SYNONYMS, key=len, reverse=True):
        if re.search(rf"(?<![a-z0-9]){re.escape(key)}(?![a-z0-9])", loc):
            return _CITY_SYNONYMS[key]
    m = re.search(r"\b([A-Z][a-zA-Z]{2,}(?: [A-Z][a-zA-Z]+)?)\b", str(location).strip())
    if m and m.group(1).lower() not in {"india", "remote"}:
        candidate = m.group(1)
        if len(candidate) <= 25:
            return candidate
    return ""


def normalize_region(location: str) -> str:
    """Coarse region (state / NCR) of a location, or \"\" when unknown."""
    city = normalize_city(location).lower()
    if not city:
        return ""
    for region, cities in _REGION_CITIES.items():
        if city in cities:
            return region
    return ""


def is_remote(location: str, workplace: str = "", description: str = "") -> bool:
    """True when the job is remote/hybrid per its location, workplace, or blurb."""
    text = f"{location or ''} {workplace or ''}"
    if _REMOTE_PAT.search(text):
        return True
    return "remote" in (description or "")[:400].lower()


def normalize_job(job: dict[str, Any]) -> dict[str, Any]:
    """Add canonical fields to a job dict, in place (additive only)."""
    location = str(job.get("location") or "")
    workplace = str(job.get("workplace_type") or "")
    job["listed_epoch"] = normalize_listed_epoch(job)
    job["salary_int"] = normalize_salary_int(str(job.get("salary") or ""))
    job["city"] = normalize_city(location)
    job["region"] = normalize_region(location)
    job["remote_ok"] = is_remote(location, workplace, str(job.get("description") or ""))
    job["workplace"] = workplace
    return job


def normalize_jobs(jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize a list of jobs in place; returns the same list."""
    for job in jobs:
        try:
            normalize_job(job)
        except (TypeError, ValueError, AttributeError):  # noqa: BLE001 — one bad job
            continue
    return jobs
