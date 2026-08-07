import logging
import re
import time
from typing import Any
from urllib.parse import urlparse

try:
    from ddgs import DDGS
except ImportError:
    DDGS = None  # type: ignore[assignment, misc]

from matcha.models import ScraperResult
from matcha.sources.base import Source
from matcha.sources.constants import (
    MONTH_NAMES,
    NON_JOB_TITLE_PATTERNS,
    NON_JOB_URL_PATTERNS,
    SEARCH_PAGE_PATTERNS,
)

from .utils import ddgs_text, limiter

logger = logging.getLogger(__name__)

# Session 23: Career Sites shares the single ``duckduckgo.com`` bucket (30
# rpm) with Web Search/Naukri/Indeed so total DuckDuckGo load stays bounded —
# its old separate 6-rpm ``career_sites.ddgs`` bucket starved it the same way
# it starved Web Search (up to 16 DDGS calls/run at 6 rpm = 160s vs the 75s
# batch budget), and a 30-rpm twin bucket would double total DDG load.

CAREER_SITES: dict[str, str] = {
    "Tech Mahindra": "careers.techmahindra.com",
    "Axis Bank": "www.axisbank.com",
    "ICICI Bank": "www.icicicareers.com",
    "Meta": "www.metacareers.com",
    "Google": "careers.google.com",
    "YouTube": "careers.google.com",
    "X (Twitter)": "about.x.com",
    "LinkedIn": "careers.linkedin.com",
    "WhatsApp": "www.metacareers.com",
    "Snapchat": "www.snap.com",
    "ShareChat": "sharechat.com",
    "Spotify": "www.lifeatspotify.com",
    "Netflix": "jobs.netflix.com",
    "Disney+ Hotstar": "www.disneycareers.com",
    "HBO": "careers.wbd.com",
    "Sony": "www.sony.com",
    "Sony Interactive (PlayStation)": "www.playstation.com",
    "Apple": "www.apple.com",
    "Microsoft": "careers.microsoft.com",
    "OpenAI": "openai.com",
    "Anthropic": "www.anthropic.com",
    "Perplexity": "perplexity.ai",
    "Zoom": "careers.zoom.us",
    "Calendly": "calendly.com",
    "Replit": "replit.com",
    "GitHub": "github.com",
    "Slack": "slack.com",
    "Stack Overflow": "stackoverflow.co",
    "Postman": "www.postman.com",
    "BrowserStack": "www.browserstack.com",
    "Datadog": "www.datadoghq.com",
    "Snowflake": "careers.snowflake.com",
    "Salesforce": "www.salesforce.com",
    "Workday": "www.workday.com",
    "Intuit": "www.intuit.com",
    "Atlassian": "www.atlassian.com",
    "SAP": "www.sap.com",
    "Oracle": "www.oracle.com",
    "IBM": "www.ibm.com",
    "Red Hat": "www.redhat.com",
    "Cisco": "www.cisco.com",
    "Citrix": "www.citrix.com",
    "Autodesk": "www.autodesk.com",
    "Intel": "www.intel.com",
    "AMD": "www.amd.com",
    "Arm": "www.arm.com",
    "Dell": "www.dell.com",
    "Motorola Solutions": "www.motorolasolutions.com",
    "Nokia": "www.nokia.com",
    "Amdocs": "www.amdocs.com",
    "Atos": "atos.net",
    "HCLTech": "www.hcltech.com",
    "HCLSoftware": "www.hcl-software.com",
    "Zensar": "www.zensar.com",
    "Hexaware": "www.hexaware.com",
    "Mphasis": "careers.mphasis.com",
    "Nagarro": "www.nagarro.com",
    "Virtusa": "www.virtusa.com",
    "Xoriant": "www.xoriant.com",
    "DXC Technology": "careers.dxc.com",
    "UST": "www.ust.com",
    "Concentrix": "www.concentrix.com",
    "Genpact": "www.genpact.com",
    "NTT Data": "www.nttdata.com",
    "Tata Technologies": "www.tatatechnologies.com",
    "LTIMindtree": "www.ltimindtree.com",
    "Persistent": "www.persistent.com",
    "Bosch": "www.bosch.com",
    "Ascendion": "ascendion.com",
    "Agio": "www.agio.com",
    "Avaya": "www.avaya.com",
    "Genesys": "www.genesys.com",
    "Nice": "www.nice.com",
    "Sprinklr": "www.sprinklr.com",
    "BMC Software": "www.bmc.com",
    "ValueLabs": "www.valuelabs.com",
    "FIS": "www.fisglobal.com",
    "Visa": "www.visa.com",
    "Mastercard": "www.mastercard.com",
    "PayPal": "www.paypal.com",
    "NPCI (RuPay)": "www.npci.org.in",
    "CRED": "careers.cred.club",
    "PhonePe": "www.phonepe.com",
    "Paytm": "paytm.com",
    "Groww": "groww.in",
    "Zerodha": "zerodha.com",
    "Angel One": "www.angelone.in",
    "Truecaller": "www.truecaller.com",
    "Zoho": "www.zoho.com",
    "Freshworks": "www.freshworks.com",
    "Flipkart": "www.flipkart.com",
    "Myntra": "careers.myntra.com",
    "Meesho": "www.meesho.com",
    "Nykaa": "www.nykaa.com",
    "PharmEasy": "pharmeasy.in",
    "MediBuddy": "www.medibuddy.in",
    "UpGrad": "www.upgrad.com",
    "Ola": "www.olacabs.com",
    "Uber": "www.uber.com",
    "Airbnb": "www.airbnb.com",
    "MakeMyTrip": "careers.makemytrip.com",
    "Shopify": "www.shopify.com",
    "Walmart": "www.walmart.com",
    "Amazon": "www.amazon.jobs",
    "FedEx": "careers.fedex.com",
    "Dominos": "www.dominos.com",
    "EA": "www.ea.com",
    "Air India": "careers.airindia.com",
    "SpiceJet": "www.spicejet.com",
    "Qatar Airways": "www.qatarairways.com",
    "BP": "www.bp.com",
    "Porsche": "www.porsche.com",
    "Bentley Motors": "www.bentleymotors.com",
    "Bentley Systems": "www.bentley.com",
    "Honda": "www.honda.com",
    "Hyundai": "www.hyundai.com",
    "Genesis Global": "genesis.global",
    "Cummins": "www.cummins.com",
    "Michelin": "www.michelin.com",
    "BNY": "www.bny.com",
    "Citi": "www.citi.com",
    "Goldman Sachs": "www.goldmansachs.com",
    "Morgan Stanley": "www.morganstanley.com",
    "JPMorgan Chase": "www.jpmorganchase.com",
    "Barclays": "www.barclays.com",
    "HSBC": "www.hsbc.com",
    "Deutsche Bank": "www.db.com",
    "UBS": "www.ubs.com",
    "BNP Paribas": "group.bnpparibas.com",
    "Lloyds Banking Group": "www.lloydsbankinggroup.com",
    "HDFC Bank": "www.hdfcbank.com",
    "Kotak Mahindra": "www.kotak.com",
    "TIAA": "www.tiaa.org",
    "Allstate": "www.allstate.com",
    "GE": "www.ge.com",
    "Unilever": "www.unilever.com",
    "ITC": "www.itcportal.com",
    "KPMG": "www.kpmg.com",
    "Jio": "www.jio.com",
    "Vodafone": "www.vodafone.com",
    "Airtel": "www.airtel.com",
    "Fiserv": "www.fiserv.com",
    "Broadridge": "www.broadridge.com",
    "State Street": "www.statestreet.com",
    "Northern Trust": "www.northerntrust.com",
    "CME Group": "www.cmegroup.com",
    "Nasdaq": "www.nasdaq.com",
    "FactSet": "www.factset.com",
    "S&P Global": "www.spglobal.com",
    "Moody's": "www.moodys.com",
    "ICE": "www.theice.com",
    "Cboe": "www.cboe.com",
    "Synchrony": "www.synchronycareers.com",
    "Equiniti": "www.equiniti.com",
    "Cencora": "www.cencora.com",
    "IQVIA": "www.iqvia.com",
    "ICON plc": "www.iconplc.com",
    "Roche": "www.roche.com",
    "Siemens Healthineers": "www.siemens-healthineers.com",
    "GE HealthCare": "careers.gehealthcare.com",
    "Philips": "www.philips.com",
    "ResMed": "www.resmed.com",
    "Medtronic": "www.medtronic.com",
    "Smith+Nephew": "www.smith-nephew.com",
    "Caterpillar": "www.caterpillar.com",
    "Rockwell Automation": "www.rockwellautomation.com",
    "Emerson": "www.emerson.com",
    "Schneider Electric": "www.se.com",
    "ABB": "careers.abb",
    "Eaton": "www.eaton.com",
    "Honeywell": "www.honeywell.com",
    "Carrier": "www.carrier.com",
    "Otis": "www.otis.com",
    "John Deere": "careers.deere.com",
    "McDonald's": "www.mcdonalds.com",
    "Lowe's": "www.lowes.com",
    "Target": "www.target.com",
    "Tesco": "www.tesco.com",
    "PepsiCo": "www.pepsico.com",
    "Coca-Cola": "www.coca-colacompany.com",
    "Reckitt": "www.reckitt.com",
    "Colgate-Palmolive": "www.colgatepalmolive.com",
    "Mondelez": "www.mondelez.com",
    "Palo Alto Networks": "www.paloaltonetworks.com",
    "Fortinet": "www.fortinet.com",
    "Akamai": "www.akamai.com",
    "Cloudflare": "www.cloudflare.com",
    "F5": "www.f5.com",
    "Check Point": "www.checkpoint.com",
    "Sophos": "www.sophos.com",
    "Trellix": "www.trellix.com",
    "Progress Software": "www.progress.com",
    "SolarWinds": "www.solarwinds.com",
    "Pegasystems": "www.pega.com",
    "Quest Software": "www.quest.com",
    "Deltek": "www.deltek.com",
    "Epicor": "www.epicor.com",
    "IFS": "www.ifs.com",
    "BlackBerry": "www.blackberry.com",
    "OpenText": "www.opentext.com",
    "Aptiv": "www.aptiv.com",
    "Visteon": "www.visteon.com",
    "Magna": "www.magna.com",
    "ZF Group": "www.zf.com",
    "Valeo": "www.valeo.com",
    "Volvo Group": "www.volvogroup.com",
    "Ciena": "www.ciena.com",
    "Ribbon Communications": "www.ribboncommunications.com",
    "Mavenir": "www.mavenir.com",
    "CommScope": "www.commscope.com",
    "Ericsson": "www.ericsson.com",
    "BT Group": "www.bt.com",
    "Spirent": "www.spirent.com",
    "Viavi Solutions": "www.viavisolutions.com",
    "Synaptics": "www.synaptics.com",
    "Marvell": "www.marvell.com",
    "NXP": "www.nxp.com",
    "Analog Devices": "careers.analog.com",
    "Microchip Technology": "www.microchip.com",
    "Western Digital": "www.westerndigital.com",
    "Seagate": "www.seagate.com",
    "KLA": "www.kla.com",
    "Lam Research": "www.lamresearch.com",
    "Harness": "www.harness.io",
    "New Relic": "www.newrelic.com",
    "Elastic": "www.elastic.co",
    "GitLab": "about.gitlab.com",
}

_DOMAIN_TO_COMPANIES: dict[str, list[str]] = {}
for _company, _domain in CAREER_SITES.items():
    _DOMAIN_TO_COMPANIES.setdefault(_domain, []).append(_company)


def _dedup_jobs(jobs: list[dict[str, str]]) -> list[dict[str, str]]:
    seen_urls: set[str] = set()
    result: list[dict[str, str]] = []
    for j in jobs:
        if j["url"] not in seen_urls:
            seen_urls.add(j["url"])
            result.append(j)
    return result


def _is_older_than_days(text: str, max_days: int) -> bool:
    now = time.time()
    patterns = [
        (re.compile(r"(\d+)\s+(?:year|yr)s?\s+ago"), 365),
        (re.compile(r"(\d+)\s+month(?:s)?\s+ago"), 30),
        (re.compile(r"(\d+)\s+week(?:s)?\s+ago"), 7),
        (re.compile(r"(\d+)\s+day(?:s)?\s+ago"), 1),
        (re.compile(r"(?:posted|published|updated)\s+(\d+)\s+(?:year|yr)s?\s+ago"), 365),
        (re.compile(r"(?:posted|published|updated)\s+(\d+)\s+month(?:s)?\s+ago"), 30),
        (re.compile(r"(?:posted|published|updated)\s+(\d+)\s+week(?:s)?\s+ago"), 7),
        (re.compile(r"(?:posted|published|updated)\s+(\d+)\s+day(?:s)?\s+ago"), 1),
    ]
    text_lower = text.lower()
    for pat, unit_days in patterns:
        m = pat.search(text_lower)
        if m:
            num = int(m.group(1))
            if num * unit_days > max_days:
                return True
    m = re.search(
        r"(?:posted|published|updated|date)\s*:\s*(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec|"
        r"january|february|march|april|may|june|july|august|september|october|november|december)\s+"
        r"(\d{1,2})(?:,?\s*(\d{4}))?",
        text_lower,
    )
    if m:
        month = MONTH_NAMES.get(m.group(1), 1)
        day = int(m.group(2))
        year = int(m.group(3)) if m.group(3) else time.gmtime().tm_year
        posted = time.mktime((year, month, day, 0, 0, 0, 0, 0, 0))
        age_days = (now - posted) / 86400
        if age_days > max_days:
            return True
    return False


def _is_search_page(title: str, url: str) -> bool:
    for p in SEARCH_PAGE_PATTERNS:
        if p.search(title):
            return True
    if re.search(r"/search\?", url, re.IGNORECASE):
        return True
    return False


def _clean_title(title: str) -> str:
    title = re.sub(
        r"\s*[-–|]\s*(?:LinkedIn|Indeed|Glassdoor|Monster|ZipRecruiter).*",
        "",
        title,
        flags=re.IGNORECASE,
    )
    title = re.sub(r"\s*[-–|]\s*(?:Hiring|Job|Opening|Vacancy).*", "", title, flags=re.IGNORECASE)
    segments = re.split(r"\s*[-–|]\s*", title)
    return segments[0].strip() if segments[0].strip() else title.strip()


def _match_company(url: str) -> str:
    domain = urlparse(url).netloc.lower().removeprefix("www.")
    for career_domain, companies in _DOMAIN_TO_COMPANIES.items():
        clean = career_domain.lower().removeprefix("www.")
        if domain == clean or domain.endswith("." + clean) or clean.endswith("." + domain):
            return companies[0]
    parts = domain.split(".")
    return parts[0].title() if parts else domain.title()


def _extract_location(snippet: str, title: str) -> str:
    patterns = [
        re.compile(r"in\s+([A-Z][a-zA-Z\s]+(?:,\s*[A-Z]{2})?)", re.IGNORECASE),
        re.compile(r"([A-Z][a-zA-Z\s]+(?:,\s*[A-Z]{2}))(?:\s+[.…]|\s*$)", re.IGNORECASE),
    ]
    for p in patterns:
        m = p.search(snippet or "")
        if m:
            loc = m.group(1).strip()
            if len(loc) < 40:
                return loc
    return "Remote / Unspecified"


def _build_queries(query: str, location: str) -> list[str]:
    queries: list[str] = []
    queries.append(f"site:myworkdayjobs.com {query} {location}")
    queries.append(f"site:greenhouse.io {query} {location}")
    queries.append(f"site:lever.co {query} {location}")
    queries.append(f"site:icims.com {query} {location}")
    queries.append(f"site:smartrecruiters.com {query} {location}")

    unique_domains = sorted(set(CAREER_SITES.values()))
    batch_size = 8
    for i in range(0, len(unique_domains), batch_size):
        batch = unique_domains[i : i + batch_size]
        for domain in batch:
            queries.append(f"site:{domain} {query} {location}")

    return queries


def search_career_sites_jobs(
    query: str,
    location: str = "",
    **kwargs: Any,
) -> ScraperResult:
    errors: list[str] = []
    if DDGS is None:
        return ScraperResult(
            errors=["ddgs library not available"], source="Career Sites", backend="ddgs"
        )

    days = kwargs.get("days")
    timelimit = ""
    if days:
        if days <= 1:
            timelimit = "d"
        elif days <= 7:
            timelimit = "w"
        else:
            timelimit = "m"

    queries = _build_queries(query, location)
    jobs: list[dict[str, str]] = []
    max_queries = kwargs.get("max_queries", 8)
    queries = queries[:max_queries]

    logger.info(
        "Searching Career Sites: q=%s location=%s queries=%d",
        query,
        location,
        len(queries),
    )

    for q in queries:
        limiter.acquire("duckduckgo.com")
        try:
            # Session 23: shared helper — generous timeout + bounded retry.
            raw = ddgs_text(q, max_results=5, timelimit=timelimit, ddgs=DDGS)
        except Exception as e:
            logger.warning("Career sites DDGS query failed (%s): %s", q, e)
            errors.append(f"DDGS query failed: {q[:50]}")
            continue

        for item in raw:
            try:
                title = item.get("title", "")
                url = item.get("href", "")
                snippet = item.get("body", "")

                if not title or not url:
                    continue
                if _is_search_page(title, url):
                    continue
                if any(re.search(p, url) for p in NON_JOB_URL_PATTERNS):
                    continue
                if any(re.search(p, title) for p in NON_JOB_TITLE_PATTERNS):
                    continue
                if days and _is_older_than_days(snippet, days):
                    continue

                job = {
                    "title": _clean_title(title),
                    "company": _match_company(url),
                    "location": _extract_location(snippet, title),
                    "description": snippet[:1000],
                    "url": url,
                    "source": "Career Sites",
                }
                if job["title"] and not _is_search_page(job["title"], url):
                    jobs.append(job)
            except Exception as e:
                logger.warning("Failed to parse career site result: %s", e)
                continue

        if len(jobs) >= 20:
            break

    return ScraperResult(
        jobs=_dedup_jobs(jobs),
        errors=errors,
        source="Career Sites",
        backend="ddgs",
        data_quality="snippet",
    )


class CareerSitesSource(Source):
    """Career Sites — 200+ employer boards via DDGS.

    Registered but OFF by default (F-11): dispatch stays untouched until
    Phase 1 enables it via ``scrapers.career_sites: true``.
    """

    name = "career_sites"
    description = "Career Sites — 200+ employer boards via DDGS"
    backends = ["ddgs"]
    tier = 0
    enabled_by_default = False

    def check(self, config: dict[str, Any] | None = None) -> tuple[str, str]:
        if not self._scrapers_config(config).get("career_sites", False):
            self.active_backend = None
            return (
                "off",
                "Disabled by default — enable via `scrapers.career_sites: true` (Phase 1)",
            )
        status, msg = self._ddgs_status(DDGS is not None)
        self.active_backend = "ddgs" if status == "ok" else None
        return status, msg

    def search(self, query: str, location: str = "", **kwargs: Any) -> ScraperResult:
        return search_career_sites_jobs(query, location, **kwargs)
