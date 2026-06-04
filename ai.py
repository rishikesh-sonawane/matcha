import json
import os
import re

import requests

from config import load_config, save_config

AI_API_URL = "https://api.kilo.ai/api/gateway/chat/completions"
AI_MODEL = "kilo-auto/small"
CONFIG_KEY = "ai_key"
ENV_VAR = "MINIMAX"


def _get_api_key():
    key = os.environ.get(ENV_VAR, "")
    if key:
        return key
    config = load_config()
    return config.get(CONFIG_KEY, "")


def check_ai_available():
    return bool(_get_api_key())


def configure_ai(key):
    config = load_config()
    config[CONFIG_KEY] = key
    save_config(config)


def _call_ai(messages, response_format=None, max_tokens=500):
    key = _get_api_key()
    if not key:
        return None

    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": AI_MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0.1,
    }
    if response_format:
        payload["response_format"] = response_format

    try:
        resp = requests.post(AI_API_URL, headers=headers, json=payload, timeout=30)
        if resp.status_code != 200:
            return None
        data = resp.json()
        choices = data.get("choices", [])
        if not choices:
            return None
        content = choices[0].get("message", {}).get("content", "")
        return content
    except Exception:
        return None


def _extract_json(text):
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
    return None


PROFILE_EXTRACTION_PROMPT = """You are parsing a resume or professional profile. Extract structured information as JSON.

Raw text:
{text}

Return valid JSON with these fields:
- "name": full name
- "title": most recent or current job title (e.g. "Senior Software Engineer")
- "headline": one-line professional summary
- "skills": array of technical and professional skills (be thorough, infer from context)
- "experience": total years of professional experience as a number, or null if unclear
- "summary": 2-3 sentence professional summary

Rules:
- Infer the title from context if not explicit
- Extract ALL skills mentioned even implicitly (languages, frameworks, tools, platforms, methodologies)
- If experience is ambiguous, set to null rather than guessing"""


def ai_extract_profile(text):
    if not check_ai_available():
        return None
    prompt = PROFILE_EXTRACTION_PROMPT.format(text=text[:4000])
    result = _call_ai(
        [{"role": "user", "content": prompt}],
        max_tokens=800,
    )
    if not result:
        return None
    parsed = _extract_json(result)
    if not parsed or not isinstance(parsed, dict):
        return None
    parsed.setdefault("name", "")
    parsed.setdefault("title", "")
    parsed.setdefault("headline", "")
    parsed.setdefault("skills", [])
    parsed.setdefault("experience", "")
    parsed.setdefault("summary", "")
    if isinstance(parsed.get("experience"), (int, float)):
        parsed["experience"] = str(parsed["experience"])
    elif not parsed.get("experience"):
        parsed["experience"] = ""
    return parsed


QUERY_GENERATION_PROMPT = """You are a job search strategist. Given a candidate's profile, generate 3-5 diverse search queries that will find the best matching jobs.

The queries should cover DIFFERENT job titles and angles — not just the candidate's current title. Think about adjacent roles, related specializations, and skill-based searches.

CANDIDATE PROFILE:
- Current Title: {title}
- Headline: {headline}
- Skills: {skills}
- Summary: {summary}
- Preferred Location: {location}

Return valid JSON:
{{
  "queries": ["query1", "query2", "query3", ...]
}}

Rules:
- Each query should be 2-4 words max
- Cover different role types (e.g., if the candidate is a DevOps engineer, include queries for "platform engineer", "site reliability engineer", "cloud engineer" as well)
- Focus on roles where their skills are applicable, not just exact title matches
- Include location-relevant terms if location is specified
- Return 3-5 queries"""


JOB_SCORING_PROMPT = """You are a critical job matching analyst. Score how well a job fits a candidate's profile. Be honest and discriminating — not every related job is a great fit.

CANDIDATE PROFILE:
- Current Title: {title}
- Headline: {headline}
- Skills: {skills}
- Experience: {experience} years
- Summary: {summary}
- Preferred Location: {location}

JOB:
- Title: {job_title}
- Company: {job_company}
- Location: {job_location}
- Description: {job_description}

Return valid JSON:
{{
  "score": <0-100 integer>,
  "reasons": ["reason1", "reason2", ...]
}}

Scoring criteria:
- Skills match (40%): how many of the candidate's core skills are relevant. Deduct for missing key skills the job requires. Skill synonym understanding OK.
- Title/role match (25%): does the job leverage the candidate's actual expertise? A role adjacent to their specialization scores higher than a generic role.
- Experience fit (20%): is the seniority level appropriate? Overqualified = penalty, underqualified = penalty.
- Location fit (15%): same city = best, same region = OK, remote = neutral, different city with no remote = penalty.

Guidelines:
- Score 80+ only if there is strong skills overlap AND the role aligns with their career trajectory
- Score 50-79 for adjacent roles where their skills are partially relevant but it's a stretch
- Score 25-49 for tangential roles that barely use their skills
- Score 0-24 for completely irrelevant roles
- Include specific, honest reasons. Mention what's MISSING if relevant.
- Never give 100 — nobody is a perfect match."""


def ai_generate_queries(profile):
    if not check_ai_available():
        return None
    title = profile.get("title", "") or profile.get("headline", "")
    headline = profile.get("headline", "") or title
    skills = ", ".join(profile.get("skills", [])) or ""
    summary = (profile.get("summary", "") or "")[:300]
    location = profile.get("location", "") or ""

    prompt = QUERY_GENERATION_PROMPT.format(
        title=title,
        headline=headline,
        skills=skills,
        summary=summary,
        location=location,
    )
    result = _call_ai(
        [{"role": "user", "content": prompt}],
        max_tokens=200,
    )
    if not result:
        return None
    parsed = _extract_json(result)
    if not parsed or not isinstance(parsed, dict):
        return None
    queries = parsed.get("queries", [])
    if not isinstance(queries, list) or len(queries) < 1:
        return None
    return [q.strip() for q in queries if q.strip()][:5]


def ai_score_job(profile, job):
    if not check_ai_available():
        return None
    title = profile.get("title", "") or profile.get("headline", "")
    headline = profile.get("headline", "") or title
    skills = ", ".join(profile.get("skills", [])) or "None specified"
    experience = profile.get("experience", "") or "Not specified"
    summary = (profile.get("summary", "") or "")[:500]
    location = profile.get("location", "") or ""

    job_title = job.get("title", "")
    job_company = job.get("company", "")
    job_location = job.get("location", "")
    job_description = (job.get("description", "") or "")[:1000]

    prompt = JOB_SCORING_PROMPT.format(
        title=title,
        headline=headline,
        skills=skills,
        experience=experience,
        summary=summary,
        location=location,
        job_title=job_title,
        job_company=job_company,
        job_location=job_location,
        job_description=job_description,
    )
    result = _call_ai(
        [{"role": "user", "content": prompt}],
        max_tokens=300,
    )
    if not result:
        return None
    parsed = _extract_json(result)
    if not parsed or not isinstance(parsed, dict):
        return None
    score = parsed.get("score")
    if not isinstance(score, (int, float)):
        return None
    return {
        "score": max(0, min(100, round(float(score), 1))),
        "reasons": parsed.get("reasons", [])[:8],
    }
