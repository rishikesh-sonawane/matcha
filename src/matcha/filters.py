"""Central filter pipeline (strategy §7) — quality → age → must-skills → location → salary.

Filters run as pipeline stages on *normalized* jobs (see ``normalization.py``)
in a fixed order, each enabled by default with sensible values and overridable
via ``settings.yaml`` under ``filters:`` (§7.6):

.. code-block:: yaml

    filters:
      days: 7                  # job age window (final authority over scrapers)
      strict_age: false        # drop unknown-age jobs instead of tagging [age?]
      min_must_matches: 1      # must-have skills required in title+description
      soft_must_skills: false  # keep below-threshold jobs, flagged for rank cap
      remote: false            # remote-only mode
      min_salary: 0            # LPA floor (0 = off)
      drop_unknown_salary: false

Each stage returns ``(kept_jobs, FilterReport)`` so the UI can show exactly
why results were cut ("96 kept (age −142 · must −21 · loc −33 …)"). Unknown-age
jobs are tagged ``age: "unknown"`` and unknown-salary jobs are tagged
``salary_tag: "unknown"`` so the UI can render ``[age?]`` / ``[salary?]``.
"""

import re
import time
from dataclasses import dataclass, field
from typing import Any

from matcha.normalization import normalize_city, normalize_region

# ---------------------------------------------------------------------------
# Report model
# ---------------------------------------------------------------------------


@dataclass
class FilterReport:
    """Per-stage outcome — kept/dropped counts plus provenance annotations."""

    name: str
    kept: int
    dropped: int
    unknown: int = 0
    reason: str = ""
    tags: list[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.dropped or self.unknown)


# ---------------------------------------------------------------------------
# Quality gate (§7.5)
# ---------------------------------------------------------------------------

_PLACEHOLDER = frozenset(
    {"", "unknown", "naukri", "naukri.com", "untitled", "tba", "tbd", "na", "n/a", "none"}
)
_TRACKING_URL = re.compile(r"(rc/clk|pagead/clk)", re.IGNORECASE)

#: Navigation/listing-page titles leaked into results by snippet fallbacks
#: (DDGS discovery for Naukri etc.) — never real postings. Titles ending in
#: "Jobs" ("Developer Tcs Jobs", "It Jobs", "DevOps - Jobs") are listing-page
#: artifacts; real titles end with the role. Conservative: single generic
#: words and boilerplate. NOTE: this must NOT fold in _PLACEHOLDER — F-12
#: keeps placeholder-title jobs whose company is real (never over-drop);
#: placeholders are handled by their own rule below.
_JUNK_TITLE_RE = re.compile(
    r"^(link to\b|it jobs?$|it$|job(s)?$|hiring$|openings?$|vacanc(y|ies)$|"
    r"careers?$|sign in$|log in$|logon$|search$|apply now$|view (job|more)$|"
    r"see (all )?jobs?$|submit$|register$)"
    r"|(^|\s)(jobs? in|jobs? at|jobs? for|apply for)\b"
    r"|^top companies? (hiring|hiring for)\b"
    r"|(^|\s)companies? hiring for\b"
    r"|([\w-]+)\s+jobs?$"
    r"|([\w-]+)\s+careers?$"
    r"|^walk[ -]?in\s+(drive|drives|interview)s?\b"
    r"|^job listings?\b"
    r"|^join our (team|company|talent)\b",
    re.IGNORECASE,
)


def _is_junk_title(title: str) -> bool:
    return bool(_JUNK_TITLE_RE.search(title.strip().lower()))


def _filter_quality(
    jobs: list[dict[str, Any]],
    profile: dict[str, Any],
    cfg: dict[str, Any],
) -> tuple[list[dict[str, Any]], FilterReport]:
    del profile, cfg  # uniform stage signature
    kept: list[dict[str, Any]] = []
    for job in jobs:
        title = str(job.get("title") or "").strip().lower()
        company = str(job.get("company") or "").strip().lower()
        url = str(job.get("url") or "").strip()

        if not title:
            continue  # empty title
        if _is_junk_title(job.get("title", "")):
            continue  # listing-page/nav noise leaked by snippet fallbacks
        if (title in _PLACEHOLDER or title.startswith("naukri")) and company in _PLACEHOLDER:
            continue  # title AND company both placeholder (F-12: never over-drop)
        if not url:
            continue  # truncated snippet with no URL
        if _TRACKING_URL.search(url) and not job.get("job_key"):
            continue  # unresolved tracking URL with no job key
        if company in _PLACEHOLDER:
            job.setdefault("data_quality", "partial")  # placeholder company alone → tagged
        kept.append(job)
    return kept, FilterReport("quality", len(kept), len(jobs) - len(kept))


# ---------------------------------------------------------------------------
# Age filter (§7.1)
# ---------------------------------------------------------------------------


def _filter_age(
    jobs: list[dict[str, Any]],
    profile: dict[str, Any],
    cfg: dict[str, Any],
) -> tuple[list[dict[str, Any]], FilterReport]:
    del profile  # uniform stage signature
    raw_days = cfg.get("days")
    days = int(raw_days) if raw_days is not None else 7
    strict = bool(cfg.get("strict_age", False))
    # days=0 = "today only" (§7.1). Use a one-day window rather than cutoff=now:
    # date-based listings ("today", ISO "2026-08-06" → UTC midnight) parse a bit
    # before now and would otherwise be wrongly dropped.
    window = max(0, days) * 86400 or 86399
    cutoff = time.time() - window
    kept: list[dict[str, Any]] = []
    unknown = 0
    for job in jobs:
        epoch = job.get("listed_epoch")
        if epoch is None:
            unknown += 1
            job["age"] = "unknown"
            if strict:
                continue
            kept.append(job)
        elif epoch >= cutoff:
            kept.append(job)
    return kept, FilterReport("age", len(kept), len(jobs) - len(kept), unknown=unknown)


# ---------------------------------------------------------------------------
# Must-have-skills gate (§7.2)
# ---------------------------------------------------------------------------

#: Skill → matching variants (word-boundary). Strategy §7.2 examples: k8s↔kubernetes,
#: aws↔amazon web services, ci/cd↔gitops. Additions are conservative to avoid
#: false positives ("go" is deliberately NOT folded into golang).
_SKILL_VARIANTS: dict[str, list[str]] = {
    "kubernetes": ["kubernetes", "k8s", "k8"],
    "k8s": ["kubernetes", "k8s", "k8"],
    "amazon web services": ["aws", "amazon web services"],
    "aws": ["aws", "amazon web services"],
    "gitops": ["gitops", "ci/cd"],
    "ci/cd": ["ci/cd", "continuous integration", "continuous delivery", "gitops"],
    "c++": ["c++", "cpp"],
    "cpp": ["c++", "cpp"],
    "js": ["javascript", "js"],
    "javascript": ["javascript", "js"],
    "react.js": ["react", "reactjs"],
    "reactjs": ["react", "reactjs"],
}


def _skill_variants(skill: str) -> list[str]:
    key = skill.strip().lower()
    return _SKILL_VARIANTS.get(key, [key])


def matches_skill(job_text: str, skill: str) -> bool:
    """Word-boundary match of a skill (with synonym variants) in lowercased text.

    Public so the ranker can reuse the same synonym map (strategy §9.2
    must-have-skill coverage bonus) instead of duplicating it.
    """
    for variant in _skill_variants(skill):
        if re.search(rf"(?<![a-z0-9]){re.escape(variant)}(?![a-z0-9])", job_text):
            return True
    return False


def _filter_must_skills(
    jobs: list[dict[str, Any]],
    profile: dict[str, Any],
    cfg: dict[str, Any],
) -> tuple[list[dict[str, Any]], FilterReport]:
    must = [s.strip() for s in profile.get("must_have_skills", []) if s.strip()]
    if not must:
        return jobs, FilterReport("must-skills", len(jobs), 0, reason="no must-have skills set")
    min_matches = max(1, int(cfg.get("min_must_matches") or 1))
    soft = bool(cfg.get("soft_must_skills", False))
    kept: list[dict[str, Any]] = []
    dropped = 0
    for job in jobs:
        text = f"{job.get('title', '')} {job.get('description', '')}".lower()
        hits = sum(1 for s in must if matches_skill(text, s))
        if hits >= min_matches:
            kept.append(job)
        elif soft:
            job["must_skills_soft"] = True  # kept but capped below hard matches (Phase 4)
            kept.append(job)
        else:
            dropped += 1
    return kept, FilterReport("must-skills", len(kept), dropped)


# ---------------------------------------------------------------------------
# Location / remote filter (§7.3)
# ---------------------------------------------------------------------------


def _filter_location(
    jobs: list[dict[str, Any]],
    profile: dict[str, Any],
    cfg: dict[str, Any],
) -> tuple[list[dict[str, Any]], FilterReport]:
    force_remote = bool(cfg.get("remote", False))
    profile_loc = str(profile.get("location") or "").strip()
    preference = str(profile.get("remote_preference") or "").strip().lower()
    remote_acceptable = preference in {"remote", "hybrid"} or not profile_loc
    profile_city = normalize_city(profile_loc)
    profile_region = normalize_region(profile_loc)

    kept: list[dict[str, Any]] = []
    remote_dropped = 0
    for job in jobs:
        remote = bool(job.get("remote_ok"))
        if force_remote:
            if remote:
                kept.append(job)
            continue
        if remote:
            if remote_acceptable:
                kept.append(job)
            else:
                remote_dropped += 1
            continue  # remote job, but the user wants on-site only
        city = normalize_city(str(job.get("location") or ""))
        region = normalize_region(str(job.get("location") or ""))
        if not profile_city:
            kept.append(job)  # no location preference
        elif city == profile_city:
            kept.append(job)  # exact city match
        elif city and region and region == profile_region:
            kept.append(job)  # region fallback
        elif not city:
            kept.append(job)  # unknown location — kept (ranked lower later)
    report = FilterReport("location", len(kept), len(jobs) - len(kept))
    # Silent mass-remote drops confuse users (a DevOps search often IS remote).
    if remote_dropped and not force_remote:
        report.reason = (
            f"{remote_dropped} remote job(s) excluded — set filters.remote: true "
            "or profile remote_preference: remote/hybrid to include them"
        )
    return kept, report


# ---------------------------------------------------------------------------
# Salary floor (§7.4)
# ---------------------------------------------------------------------------


def _filter_salary(
    jobs: list[dict[str, Any]],
    profile: dict[str, Any],
    cfg: dict[str, Any],
) -> tuple[list[dict[str, Any]], FilterReport]:
    min_salary = int(profile.get("min_salary") or cfg.get("min_salary") or 0)
    if min_salary <= 0:
        return jobs, FilterReport("salary", len(jobs), 0, reason="no floor configured")
    drop_unknown = bool(cfg.get("drop_unknown_salary", False))
    kept: list[dict[str, Any]] = []
    unknown = 0
    for job in jobs:
        salary_int = job.get("salary_int")
        if salary_int is None:
            unknown += 1
            job["salary_tag"] = "unknown"  # display string untouched
            if drop_unknown:
                continue
            kept.append(job)
        elif int(salary_int) < min_salary:
            continue  # below the floor
        else:
            kept.append(job)
    return kept, FilterReport("salary", len(kept), len(jobs) - len(kept), unknown=unknown)


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

_FILTER_ORDER: tuple[str, ...] = ("quality", "age", "must-skills", "location", "salary")
_STAGES = {
    "quality": _filter_quality,
    "age": _filter_age,
    "must-skills": _filter_must_skills,
    "location": _filter_location,
    "salary": _filter_salary,
}

_KNOWN_STAGES = set(_STAGES)


def apply_filters(
    jobs: list[dict[str, Any]],
    profile: dict[str, Any] | None = None,
    filters_cfg: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], list[FilterReport]]:
    """Run the fixed filter order over normalized jobs.

    Returns ``(kept_jobs, reports)``. ``profile`` may omit the Phase-2 fields
    (``must_have_skills`` / ``min_salary`` / ``remote_preference``) — defaults
    keep everything. Each stage is isolated: a stage failure keeps the jobs it
    has already accepted and records a report rather than crashing the run.
    """
    profile = profile or {}
    cfg = dict(filters_cfg or {})
    kept = list(jobs)
    reports: list[FilterReport] = []
    for name in _FILTER_ORDER:
        try:
            kept, report = _STAGES[name](kept, profile, cfg)
        except Exception as e:  # noqa: BLE001 — failproof pipeline
            report = FilterReport(name, len(kept), 0, reason=f"stage failed: {e}")
        reports.append(report)
    return kept, reports


def build_filter_summary(reports: list[FilterReport]) -> str:
    """Human line of the filter report, e.g. ``age −142 · must −21 · loc −33``."""
    parts: list[str] = []
    for report in reports:
        if not report:
            continue
        if report.dropped:
            parts.append(f"{report.name} −{report.dropped}")
        if report.unknown:
            parts.append(f"{report.name} ?{report.unknown}")
    return " · ".join(parts)


def filter_notes(reports: list[FilterReport]) -> list[str]:
    """Actionable notes beyond the drop counts (currently the remote hint).

    Stage-failure messages are deliberately excluded — those are diagnostics,
    not user guidance.
    """
    for report in reports:
        if (
            report.name == "location"
            and report.reason
            and not report.reason.startswith("stage failed")
        ):
            return [report.reason]
    return []


def provenance_tags(job: dict[str, Any]) -> list[str]:
    """Provenance tags for the results table (strategy §9.6).

    Quality (``full``/``partial``/``snippet``) followed by the Phase-2
    uncertainty tags ``age?`` / ``salary?`` — rendered next to the score so
    low-confidence matches are obvious.
    """
    tags: list[str] = []
    quality = (job.get("data_quality") or "").lower()
    if quality == "full":
        tags.append("full")
    elif quality == "partial":
        tags.append("partial")
    elif quality == "snippet":
        tags.append("snippet")
    if job.get("age") == "unknown":
        tags.append("age?")
    if job.get("salary_tag") == "unknown":
        tags.append("salary?")
    return tags
