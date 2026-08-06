"""Relevance scoring (strategy §9) — confidence-weighted, calibrated for Phase 4.

The heuristic keeps its max dimension weights (skills 35 · title 25 · seniority
15 · location 15 · keywords 10) as the *ceiling* available for a perfectly
described job, then:

- **Confidence scaling (§9.1):** the text-derived dimensions (skills,
  keywords) are multiplied by a data-richness confidence factor — `full`
  (enriched) ≈ 1.0, `partial`/short ≈ 0.85, `snippet`/no description ≈ 0.7 —
  so a match on an empty field contributes ~0 and full-data jobs outrank
  snippet-guesses.
- **Recency (§9.2):** a fresh posting (`listed_epoch`) earns up to +5, decaying
  to 0 past two weeks; unknown age earns nothing.
- **Workplace match (§9.2):** jobs whose `remote_ok`/`workplace_type` agrees
  with the profile's `remote_preference` earn +3.
- **Must-have-skill coverage (§9.2):** +2 per matched must-have skill
  (synonym-aware, same map as the filter), capped at +6.
- **Soft-mode cap:** jobs kept by `soft_must_skills` (below the must-skill
  threshold) are capped at 45 so they never outrank a hard match.

Also provides the calibration guard (`detect_flatline`, `normalize_scores`,
§9.4) and `ai_eligible` (AI re-scoring runs only on enriched candidates, §9.3).
"""

import logging
import re
import time
from typing import Any

from matcha.ai import ai_score_job, check_ai_available
from matcha.filters import matches_skill

logger = logging.getLogger(__name__)

#: Soft-mode rank cap (§9.2) — below the ~50+ range of genuine must-skill matches.
SOFT_CAP = 45.0
#: Flatline guard (§9.4): top-decile spread below this = homogeneous scores.
FLATLINE_SPREAD = 5.0
#: Minimum description length to treat as confidently rich without a quality tag.
#: The explicit `data_quality` flag carries the real enriched-vs-snippet signal;
#: the length proxy only separates "has a real description" from "barely any".
_FULL_DESC = 30
_PARTIAL_DESC = 8
#: AI re-scoring (§9.3) needs a substantial description when provenance is absent.
_AI_MIN_DESC = 60


def compute_relevance_ai(
    job: dict[str, Any],
    profile: dict[str, Any],
    ai_timeout: int = 60,
) -> dict[str, Any] | None:
    if not check_ai_available():
        return None
    return ai_score_job(profile, job, timeout=ai_timeout)


def ai_eligible(job: dict[str, Any]) -> bool:
    """§9.3 — AI re-scoring is for enriched candidates only.

    A job qualifies when its provenance says full/partial (OpenCLI detail,
    Jina render, Naukri job-page) or it carries a substantial description —
    never for bare snippet rows where the AI prompt would score noise.
    """
    quality = (job.get("data_quality") or "").lower()
    if quality in ("full", "partial"):
        return True
    return len((job.get("description") or "").strip()) >= _AI_MIN_DESC


def tokenize(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9+#.]+", text.lower()))


def _word_boundary_match(text: str, word: str) -> bool:
    return bool(re.search(rf"\b{re.escape(word)}\b", text.lower()))


_SENIORITY_KEYWORDS: dict[str, set[str]] = {
    "entry": {"junior", "jr", "intern", "trainee", "entry", "graduate", "fresher", "apprentice"},
    "mid": {"mid", "midlevel", "intermediate", "ii"},
    "senior": {"senior", "sr", "lead", "principal", "staff", "architect", "iii", "iv", "v"},
}


def _infer_level_from_experience(years: float) -> str:
    if years <= 1:
        return "entry"
    elif years <= 4:
        return "mid"
    elif years <= 8:
        return "senior"
    else:
        return "staff"


def _infer_level_from_title(title: str) -> str | None:
    title_lower = title.lower()
    title_tokens = set(re.findall(r"[a-z0-9+#.]+", title_lower))
    for level, keywords in _SENIORITY_KEYWORDS.items():
        if title_tokens & keywords:
            return level
    return None


def _seniority_score(profile_exp_str: str, job_title: str) -> tuple[float, list[str]]:
    reasons: list[str] = []
    try:
        profile_years = float(profile_exp_str)
    except (ValueError, TypeError):
        return 0.0, reasons

    profile_level = _infer_level_from_experience(profile_years)
    job_level = _infer_level_from_title(job_title)

    if job_level is None:
        return 7.5, ["Seniority not specified in title"]

    level_rank = {"entry": 0, "mid": 1, "senior": 2, "staff": 3}
    diff = level_rank.get(job_level, 1) - level_rank.get(profile_level, 1)

    if diff == 0:
        reasons.append(f"Seniority match: {profile_level}")
        return 15.0, reasons
    elif abs(diff) == 1:
        reasons.append(f"Seniority close: profile={profile_level}, job={job_level}")
        return 7.5, reasons
    elif diff > 0:
        reasons.append(f"Job may be overqualified: profile={profile_level}, job={job_level}")
        return 3.0, reasons
    else:
        reasons.append(f"Job may be underqualified: profile={profile_level}, job={job_level}")
        return 3.0, reasons


def _location_score(job_location: str, profile_location: str) -> tuple[float, list[str]]:
    reasons: list[str] = []
    job_loc = (job_location or "").lower().strip()
    profile_loc = (profile_location or "").lower().strip()

    if not profile_loc or profile_loc == "remote":
        if "remote" in job_loc or not job_loc:
            reasons.append("Remote work")
            return 12.0, reasons
        return 10.0, ["No location preference set"]

    job_tokens = set(tokenize(job_loc))
    profile_tokens = set(tokenize(profile_loc))

    overlap = job_tokens & profile_tokens
    significant_overlap = {t for t in overlap if len(t) > 2}

    if significant_overlap:
        reasons.append("Location match")
        return 15.0, reasons
    if "remote" in job_loc:
        reasons.append("Remote position (location flexible)")
        return 12.0, reasons
    return 3.0, reasons


# ---------------------------------------------------------------------------
# Phase 4 signals (strategy §9.1–9.2)
# ---------------------------------------------------------------------------


def _data_confidence(job: dict[str, Any]) -> float:
    """Confidence that text-derived scores reflect the real posting (§9.1).

    Explicit per-row provenance wins. The description-length proxy is a
    best-effort fallback only for rows that never got stamped (legacy/edge
    data) — the real pipeline stamps every row from its ``ScraperResult``
    in ``main.search_jobs``, so production rows always carry ``data_quality``.
    A match on an empty field contributes ~0.
    """
    quality = (job.get("data_quality") or "").lower()
    if quality == "full":
        return 1.0
    if quality == "partial":
        return 0.85
    if quality == "snippet":
        return 0.7
    desc_len = len((job.get("description") or "").strip())
    if desc_len >= _FULL_DESC:
        return 1.0
    if desc_len >= _PARTIAL_DESC:
        return 0.85
    return 0.7


def _recency_bonus(job: dict[str, Any]) -> tuple[float, list[str]]:
    """Favor fresh postings within the filter window (§9.2)."""
    if job.get("age") == "unknown":
        return 0.0, []
    epoch = job.get("listed_epoch")
    if epoch is None:
        return 0.0, []
    try:
        days_old = (time.time() - int(epoch)) / 86400
    except (TypeError, ValueError):
        return 0.0, []
    if days_old < 3:
        return 5.0, ["Fresh posting"]
    if days_old < 7:
        return 3.0, ["Recent posting"]
    if days_old < 14:
        return 1.0, ["Listed within 2 weeks"]
    return 0.0, []


def _workplace_bonus(job: dict[str, Any], profile: dict[str, Any]) -> tuple[float, list[str]]:
    """Reward workplace agreement with the profile's remote preference (§9.2)."""
    pref = (profile.get("remote_preference") or "").strip().lower()
    if pref not in ("remote", "hybrid", "onsite"):
        return 0.0, []
    remote = bool(job.get("remote_ok"))
    workplace = " ".join(str(job.get(k) or "") for k in ("workplace_type", "workplace")).lower()
    # remote_ok is the normalization-layer authority (is_remote() folds
    # workplace_type in); a contradictory workplace_type string doesn't
    # override it.
    wants_remote = pref in ("remote", "hybrid")
    if wants_remote and (remote or "remote" in workplace or "hybrid" in workplace):
        return 3.0, ["Remote-friendly workplace"]
    if pref == "onsite" and not remote and "remote" not in workplace:
        return 3.0, ["On-site position"]
    return 0.0, []


def _must_skills_bonus(job: dict[str, Any], profile: dict[str, Any]) -> tuple[float, list[str]]:
    """Bonus for must-have-skill coverage, synonym-aware like the filter (§9.2)."""
    must = [s.strip() for s in profile.get("must_have_skills", []) if s.strip()]
    if not must:
        return 0.0, []
    text = f"{job.get('title', '')} {job.get('description', '')}".lower()
    hits = [s for s in must if matches_skill(text, s)]
    if not hits:
        return 0.0, []
    bonus = min(6.0, 2.0 * len(hits))
    return bonus, [f"Must-have skill: {', '.join(hits[:3])}"]


# ---------------------------------------------------------------------------
# Calibration guard (strategy §9.4)
# ---------------------------------------------------------------------------


def detect_flatline(scores: list[float], threshold: float = FLATLINE_SPREAD) -> bool:
    """True when the top-decile spread is near zero (homogeneous scores).

    Small batches (< 15) are skipped — with too few scores the "top decile"
    is a meaningless one- or two-element slice whose spread is always ~0.
    """
    if len(scores) < 15:
        return False
    ordered = sorted(scores, reverse=True)
    decile = ordered[: max(3, len(ordered) // 10)]
    return (decile[0] - decile[-1]) < threshold


def normalize_scores(scores: list[float]) -> list[float]:
    """Linear stretch of a flat distribution onto [5, 100] (§9.4, when configured)."""
    if len(scores) < 2:
        return list(scores)
    lo, hi = min(scores), max(scores)
    if hi - lo < 1e-9:
        return list(scores)
    return [round(5.0 + (s - lo) / (hi - lo) * 95.0, 1) for s in scores]


# ---------------------------------------------------------------------------
# Main scorer
# ---------------------------------------------------------------------------


def compute_relevance(job: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    score = 0.0
    reasons: list[str] = []
    confidence = _data_confidence(job)

    profile_skills = [s.strip().lower() for s in profile.get("skills", []) if s.strip()]
    job_title = (job.get("title") or "").lower()
    job_description = (job.get("description") or "").lower()
    job_text = f"{job_title} {job_description}"

    skill_matches = [s for s in profile_skills if _word_boundary_match(job_text, s)]
    if profile_skills:
        skill_ratio = len(skill_matches) / len(profile_skills)
        # §9.1: text-derived dimensions are confidence-scaled.
        score += skill_ratio * 35.0 * confidence
        if skill_matches:
            msg = f"Skills: {', '.join(skill_matches[:5])}"
            if len(skill_matches) > 5:
                msg += f" +{len(skill_matches) - 5} more"
            reasons.append(msg)

    profile_title_text = f"{profile.get('title', '')} {profile.get('headline', '')}"
    profile_title_tokens = tokenize(profile_title_text)
    job_title_tokens = tokenize(job_title)
    if profile_title_tokens and job_title_tokens:
        overlap = profile_title_tokens & job_title_tokens
        title_ratio = len(overlap) / max(len(profile_title_tokens), len(job_title_tokens))
        title_points = title_ratio * 25.0
        score += title_points
        if overlap:
            reasons.append(f"Title overlap: {', '.join(sorted(overlap)[:5])}")

    sen_score, sen_reasons = _seniority_score(profile.get("experience", ""), job.get("title", ""))
    score += sen_score
    reasons.extend(sen_reasons)

    loc_score, loc_reasons = _location_score(job.get("location", ""), profile.get("location", ""))
    score += loc_score
    reasons.extend(loc_reasons)

    keywords = {s for s in profile_skills if len(s.split()) > 1}
    keyword_hits = sum(1 for kw in keywords if _word_boundary_match(job_text, kw))
    if keywords:
        kw_ratio = keyword_hits / len(keywords)
        score += kw_ratio * 10.0 * confidence

    # §9.2 signals: recency, workplace agreement, must-have-skill coverage.
    rec_bonus, rec_reasons = _recency_bonus(job)
    score += rec_bonus
    reasons.extend(rec_reasons)

    work_bonus, work_reasons = _workplace_bonus(job, profile)
    score += work_bonus
    reasons.extend(work_reasons)

    must_bonus, must_reasons = _must_skills_bonus(job, profile)
    score += must_bonus
    reasons.extend(must_reasons)

    # §9.2 soft-mode cap: below-threshold must-skill jobs never outrank hard matches.
    if job.get("must_skills_soft"):
        score = min(score, SOFT_CAP)
        reasons.append("Below must-skill threshold (soft mode)")

    score = max(5.0, min(score, 100.0))
    if score < 10:
        reasons = ["Low match — few overlapping signals"]

    return {
        "score": round(score, 1),
        "reasons": reasons[:8],
    }
