import re
from typing import Any, Optional

from ai import ai_score_job, check_ai_available


def compute_relevance_ai(job: dict[str, Any], profile: dict[str, Any]) -> Optional[dict[str, Any]]:
    if not check_ai_available():
        return None
    return ai_score_job(profile, job)


def tokenize(text: str) -> set[str]:
    text = text.lower()
    return set(re.findall(r"[a-z0-9+#.]+", text))


STOP_WORDS = {
    "a",
    "an",
    "the",
    "and",
    "or",
    "of",
    "in",
    "with",
    "for",
    "at",
    "to",
    "is",
    "are",
    "was",
    "were",
    "i",
    "my",
    "me",
    "we",
    "our",
    "you",
    "your",
    "it",
    "its",
    "on",
    "by",
    "as",
    "be",
    "but",
    "from",
    "not",
    "so",
    "up",
    "all",
    "have",
    "has",
    "had",
    "been",
    "being",
    "do",
    "does",
    "did",
    "will",
    "would",
    "could",
    "should",
    "may",
    "might",
    "can",
}


def compute_relevance(job: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    score = 0.0
    reasons = []

    profile_skills = [s.lower() for s in profile.get("skills", [])]
    profile_title = (profile.get("title") or "").lower()
    profile_summary = (profile.get("summary") or "").lower()
    profile_headline = (profile.get("headline") or "").lower()

    job_title = (job.get("title") or "").lower()
    job_description = (job.get("description") or "").lower()
    job_text = f"{job_title} {job_description}"

    title_words = tokenize(profile_title) | tokenize(profile_headline)
    title_words -= STOP_WORDS

    matched_title = title_words & tokenize(job_title)
    if matched_title:
        score += 20
        reasons.append(f"Job title matches profile: {', '.join(matched_title)}")

    skill_matches = 0
    matched_skills = []
    for skill in profile_skills:
        skill_lower = skill.lower()
        skill_words = tokenize(skill_lower)
        if skill_lower in job_text or (len(skill_words) > 1 and skill_words <= tokenize(job_text)):
            skill_matches += 1
            matched_skills.append(skill)

    if profile_skills:
        skill_ratio = skill_matches / len(profile_skills)
        score += skill_ratio * 35
    else:
        score += 15

    if matched_skills:
        reasons.append(f"Skill match: {', '.join(matched_skills[:5])}")
        if len(matched_skills) > 5:
            reasons[-1] += f" +{len(matched_skills) - 5} more"

    all_profile_text = " ".join(
        [
            profile_summary,
            profile_headline,
            " ".join(profile_skills),
            profile_title,
        ]
    )
    profile_keywords = tokenize(all_profile_text) - STOP_WORDS - title_words
    desc_matches = profile_keywords & tokenize(job_text)
    if desc_matches:
        kw_score = min(len(desc_matches) * 1.5, 15)
        score += kw_score
        matching = list(desc_matches - set(matched_skills))
        if matching:
            reasons.append(f"Keyword match: {', '.join(matching[:5])}")

    exp = profile.get("experience", "")
    try:
        years_exp = int(re.search(r"\d+", str(exp)).group())
    except (ValueError, AttributeError):
        years_exp = None

    if years_exp is not None:
        seniority_keywords = {
            "entry": [
                "junior",
                "entry",
                "associate",
                "graduate",
                "trainee",
                "new grad",
                "intern",
                "internship",
            ],
            "mid": ["mid", "mid-level", "intermediate", "ii", "2", "level 2"],
            "senior": [
                "senior",
                "sr",
                "lead",
                "staff",
                "principal",
                "architect",
                "manager",
                "head",
                "supervisor",
            ],
        }

        if years_exp <= 2:
            expected = "entry"
            bonus_levels = ["entry", "mid"]
        elif years_exp <= 5:
            expected = "mid"
            bonus_levels = ["mid", "entry"]
        else:
            expected = "senior"
            bonus_levels = ["senior", "mid"]

        found_level = None
        for level, kws in seniority_keywords.items():
            for kw in kws:
                if kw in job_title or kw in job_description:
                    found_level = level
                    break
            if found_level:
                break

        if found_level == expected:
            score += 10
            reasons.append(f"Seniority match: {found_level}")
        elif found_level and found_level in bonus_levels:
            score += 5
        elif found_level:
            score -= 3

    location = job.get("location", "").lower()
    profile_location = profile.get("location", "").lower()
    if profile_location and profile_location != "remote":
        location_parts = profile_location.replace(",", "").split()
        if any(part in location for part in location_parts if len(part) > 2):
            score += 8
            reasons.append("Location match")
    elif "remote" in location.lower():
        score += 5

    score = max(0, min(score, 100))

    return {
        "score": round(score, 1),
        "reasons": reasons[:8],
    }
