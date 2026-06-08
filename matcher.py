import re
from typing import Any, Optional

from ai import ai_score_job, check_ai_available


def compute_relevance_ai(job: dict[str, Any], profile: dict[str, Any]) -> Optional[dict[str, Any]]:
    if not check_ai_available():
        return None
    return ai_score_job(profile, job)


def tokenize(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9+#.]+", text.lower()))


def compute_relevance(job: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    score = 0.0
    reasons = []

    profile_skills = [s.lower() for s in profile.get("skills", [])]
    job_title = (job.get("title") or "").lower()
    job_description = (job.get("description") or "").lower()
    job_text = f"{job_title} {job_description}"

    skill_matches = [s for s in profile_skills if s in job_text]
    if profile_skills:
        skill_ratio = len(skill_matches) / len(profile_skills)
        score += skill_ratio * 70
        if skill_matches:
            msg = f"Skills: {', '.join(skill_matches[:5])}"
            if len(skill_matches) > 5:
                msg += f" +{len(skill_matches) - 5} more"
            reasons.append(msg)

    profile_title_tokens = tokenize(profile.get("title", ""))
    job_title_tokens = tokenize(job_title)
    if profile_title_tokens & job_title_tokens:
        score += 10
        overlap = profile_title_tokens & job_title_tokens
        reasons.append(f"Title overlap: {', '.join(overlap)}")

    exp = profile.get("experience", "")
    try:
        years_exp = int(re.search(r"\d+", str(exp)).group())
    except (ValueError, AttributeError):
        years_exp = None

    if years_exp is not None:
        senior_kw = {"senior", "sr", "lead", "staff", "principal", "architect", "manager", "head"}
        mid_kw = {"mid", "intermediate", "ii", "2"}
        entry_kw = {
            "junior",
            "jr",
            "entry",
            "associate",
            "graduate",
            "trainee",
            "intern",
            "fresher",
        }
        if years_exp >= 5:
            expected = senior_kw
        elif years_exp >= 2:
            expected = mid_kw
        else:
            expected = entry_kw
        found = (set(tokenize(job_title)) | set(tokenize(job_description))) & expected
        if found:
            score += 10
            reasons.append(f"Seniority: {', '.join(found)}")

    location = job.get("location", "").lower()
    profile_location = profile.get("location", "").lower()
    if profile_location and profile_location != "remote":
        location_parts = set(profile_location.replace(",", "").split())
        location_parts = {p for p in location_parts if len(p) > 2}
        if location_parts & set(tokenize(location)):
            score += 10
            reasons.append("Location match")
    elif "remote" in location:
        score += 5

    score = max(0, min(score, 100))

    return {
        "score": round(score, 1),
        "reasons": reasons[:8],
    }
