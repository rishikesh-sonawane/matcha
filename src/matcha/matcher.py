import logging
import re
from typing import Any

from matcha.ai import ai_score_job, check_ai_available

logger = logging.getLogger(__name__)


def compute_relevance_ai(
    job: dict[str, Any],
    profile: dict[str, Any],
    ai_timeout: int = 60,
) -> dict[str, Any] | None:
    if not check_ai_available():
        return None
    return ai_score_job(profile, job, timeout=ai_timeout)


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


def compute_relevance(job: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    score = 0.0
    reasons: list[str] = []

    profile_skills = [s.strip().lower() for s in profile.get("skills", []) if s.strip()]
    job_title = (job.get("title") or "").lower()
    job_description = (job.get("description") or "").lower()
    job_text = f"{job_title} {job_description}"

    skill_matches = [s for s in profile_skills if _word_boundary_match(job_text, s)]
    if profile_skills:
        skill_ratio = len(skill_matches) / len(profile_skills)
        score += skill_ratio * 35.0
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
        score += kw_ratio * 10.0

    score = max(5.0, min(score, 100.0))
    if score < 10:
        reasons = ["Low match — few overlapping signals"]

    return {
        "score": round(score, 1),
        "reasons": reasons[:8],
    }
