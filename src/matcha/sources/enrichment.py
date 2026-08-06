"""Top-N job enrichment via OpenCLI job-detail (strategy §8).

After ``rank_jobs``, enrich the top N candidates with real posting details so
the TUI shows full descriptions + apply URLs instead of snippets:

- LinkedIn: ``opencli linkedin job-detail <job-url>`` → description, apply_url,
  workplace_type, job_type, applicants, listed, company_url. **No salary**
  (F-06): OpenCLI job-detail never exposes it — LinkedIn salary stays
  best-effort from search cards only.
- Indeed: ``opencli indeed job <jk>`` → description, job_type, salary, url
  (Indeed detail *does* include salary).

Contracts:

- **Parallel ≤5 workers** (``min(max_workers, 5)``), one future per job.
- **Per-job isolation:** a failing detail call leaves the job with its search
  data untouched (``enrich_error`` records the reason) — one bad job never
  takes down the batch.
- **Consent-gated OpenCLI path (strategy §6.3):** the browser-driven
  job-detail calls run only when the user consented to OpenCLI for that
  source. The Jina Reader fallback is **zero-config** (no browser, no login —
  strategy §8) and therefore does NOT require OpenCLI consent; it is capped
  (``_JINA_MAX_JOBS``) to respect the anonymous tier's rate limits.

Enrichment never re-ranks — step 8 (re-rank on enriched signals) is a
separate pipeline stage.
"""

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import requests

from matcha.sources.backends.opencli import (
    consent_granted,
    indeed_job_detail,
    linkedin_job_detail,
    opencli_status,
)

logger = logging.getLogger(__name__)

#: job.source label -> consent config key (backends.opencli._CONSENT_KEYS)
_SOURCE_KEYS = {
    "LinkedIn": "linkedin",
    "Indeed": "indeed",
}

#: Keys merged from OpenCLI LinkedIn job-detail. Salary is deliberately
#: absent (F-06) — enrichment must never claim what the adapter cannot give.
_LINKEDIN_MERGE_KEYS = (
    "description",
    "apply_url",
    "workplace_type",
    "job_type",
    "applicants",
    "listed",
    "company_url",
)

#: Keys merged from OpenCLI Indeed job detail (includes salary).
_INDEED_MERGE_KEYS = ("description", "job_type", "salary", "url")

_JINA_BASE = "https://r.jina.ai/"
_JINA_MAX_DESCRIPTION = 3000
#: Jina's anonymous free tier is aggressively rate-limited — never fire more
#: than this many fallback fetches per batch (strategy §8 zero-config path).
_JINA_MAX_JOBS = 10


def enrich_job(
    job: dict[str, Any],
    timeout: int = 30,
    config: dict[str, Any] | None = None,
    opencli_ready: bool | None = None,
) -> bool:
    """Enrich one job dict in place (strategy §8 ``enrich_job``).

    Returns True when the job gained detail data. The OpenCLI (browser) path
    requires OpenCLI consent for the job's source; the Jina fallback is
    zero-config and runs without it. Failures are isolated — the job keeps
    its search data and ``enrich_error`` records the reason.
    """
    key = _SOURCE_KEYS.get(str(job.get("source", "")))
    if not key:
        return False
    if opencli_ready is None:
        opencli_ready = opencli_status().ready
    try:
        if key == "linkedin":
            return _enrich_linkedin(job, timeout, opencli_ready, config)
        return _enrich_indeed(job, timeout, opencli_ready, config)
    except Exception as e:  # noqa: BLE001 — per-job isolation is the contract
        logger.warning("Enrichment failed for %s job %r: %s", key, job.get("title"), e)
        job["enrich_error"] = str(e)
        return False


def enrich_top_n(
    ranked: list[tuple[float, dict[str, Any], list[str]]],
    top_n: int = 30,
    max_workers: int = 5,
    timeout: int = 30,
    config: dict[str, Any] | None = None,
) -> tuple[int, list[tuple[float, dict[str, Any], list[str]]]]:
    """Enrich the top ``top_n`` ranked jobs in parallel.

    Returns ``(enriched_count, ranked)``; job dicts are mutated in place so
    ranking order and the score/reasons tuples are preserved. When the
    browser bridge is down, only the Jina fallback applies (LinkedIn only)
    and is capped at ``_JINA_MAX_JOBS`` jobs.
    """
    if not ranked:
        return 0, ranked

    st = opencli_status()
    if st.ready:
        top = ranked[:top_n]
    else:
        top = ranked[: min(top_n, _JINA_MAX_JOBS)]

    enriched = 0
    with ThreadPoolExecutor(max_workers=min(max_workers, 5)) as pool:
        futures = [
            pool.submit(enrich_job, job, timeout=timeout, config=config, opencli_ready=st.ready)
            for _, job, _ in top
        ]
        for future in as_completed(futures):
            try:
                if future.result():
                    enriched += 1
            except Exception:  # noqa: BLE001 — isolation means never aborting the batch
                logger.warning("Enrichment worker raised unexpectedly; continuing")
    return enriched, ranked


def _enrich_linkedin(
    job: dict[str, Any],
    timeout: int,
    opencli_ready: bool,
    config: dict[str, Any] | None,
) -> bool:
    url = str(job.get("url") or "")
    if "linkedin.com/jobs" not in url:
        return False
    if opencli_ready:
        if not consent_granted(config, "linkedin"):
            return False
        detail = linkedin_job_detail(url, timeout=timeout)
        if not detail:
            job["enrich_error"] = "job-detail failed"
            return False
        for key in _LINKEDIN_MERGE_KEYS:
            if detail.get(key):
                job[key] = detail[key]
        job["data_quality"] = "full"
        job["enrich_source"] = "opencli"
        return True
    # Zero-config fallback (strategy §8): Jina Reader needs no browser/login,
    # so no OpenCLI consent is required here.
    return _jina_enrich(job, url, timeout)


def _enrich_indeed(
    job: dict[str, Any],
    timeout: int,
    opencli_ready: bool,
    config: dict[str, Any] | None,
) -> bool:
    job_key = str(job.get("job_key") or "")
    if not job_key or not opencli_ready:
        return False  # no zero-config fallback for Indeed yet
    if not consent_granted(config, "indeed"):
        return False
    detail = indeed_job_detail(job_key, timeout=timeout)
    if not detail:
        job["enrich_error"] = "job detail failed"
        return False
    for key in _INDEED_MERGE_KEYS:
        if detail.get(key):
            job[key] = detail[key]
    job["data_quality"] = "full"
    job["enrich_source"] = "opencli"
    return True


def _jina_enrich(job: dict[str, Any], url: str, timeout: int) -> bool:
    """Best-effort Jina Reader fallback (strategy §8)."""
    try:
        resp = requests.get(_JINA_BASE + url, timeout=timeout)
        if resp.status_code != 200:
            return False
        text = resp.text.strip()
        if not text:
            return False
        job["description"] = text[:_JINA_MAX_DESCRIPTION]
        job["data_quality"] = "partial"
        job["enrich_source"] = "jina"
        return True
    except requests.RequestException as e:
        logger.warning("Jina Reader fetch failed for %s: %s", url, e)
        return False
