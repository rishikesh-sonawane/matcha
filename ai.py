import json
import os
import re
from typing import Any, Optional

import requests
from rich.console import Console

from config import load_config, save_config

console = Console()

def _env_or_config(key: str, config_key: str, default: str = "") -> str:
    val = os.environ.get(key, "")
    if val:
        return val
    return load_config().get(config_key, default)


def _get_api_key() -> str:
    return _env_or_config("AI_API_KEY", "ai_key", os.environ.get("MINIMAX", ""))


def _get_api_url() -> str:
    return _env_or_config("AI_API_URL", "ai_url", os.environ.get("OPENAI_BASE_URL", ""))


def _get_model() -> str:
    return _env_or_config("AI_MODEL", "ai_model", "")


def check_ai_available() -> bool:
    if not _get_api_key():
        return False
    if not _get_api_url():
        return False
    if not _get_model():
        return False
    return True


def configure_ai(key: str, url: str = "", model: str = "") -> None:
    config = load_config()
    config["ai_key"] = key
    if url:
        config["ai_url"] = url
    if model:
        config["ai_model"] = model
    save_config(config)


def _call_ai(
    messages: list[dict[str, Any]],
    response_format: Optional[dict[str, Any]] = None,
    max_tokens: int = 8192,
    timeout: int = 120,
) -> Optional[str]:
    key = _get_api_key()
    url = _get_api_url()
    model = _get_model()
    if not key:
        console.print("[red]AI Error:[/red] $AI_API_KEY is not set. Run with --configure or set the env var.")
        return None
    if not url:
        console.print("[red]AI Error:[/red] $AI_API_URL is not set. Run with --configure or set the env var.")
        return None
    if not model:
        console.print("[red]AI Error:[/red] $AI_MODEL is not set. Run with --configure or set the env var.")
        return None

    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0.1,
    }
    if response_format:
        payload["response_format"] = response_format

    for attempt in range(2):
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
            if resp.status_code == 401:
                console.print("[red]AI Error: Unauthorized (HTTP 401).[/red] Check your $AI_API_KEY.")
                return None
            if resp.status_code == 404:
                console.print(f"[red]AI Error: Endpoint not found (HTTP 404).[/red] Check your $AI_API_URL:\n  {url}")
                return None
            if resp.status_code == 429:
                console.print("[red]AI Error: Rate limited (HTTP 429).[/red] Try again later.")
                return None
            if resp.status_code != 200:
                detail = resp.text[:300]
                console.print(f"[red]AI Error: HTTP {resp.status_code}[/red]\n  {detail}")
                return None
            data = resp.json()
            choices = data.get("choices", [])
            if not choices:
                console.print("[red]AI Error:[/red] API returned empty response (no choices).")
                return None
            content = choices[0].get("message", {}).get("content", "")
            if not content:
                finish = choices[0].get("finish_reason", "unknown")
                usage = data.get("usage", {})
                comp = usage.get("completion_tokens", 0)
                reasoning = (
                    usage.get("completion_tokens_details", {})
                    .get("reasoning_tokens", 0)
                )
                console.print(
                    f"[red]AI Error:[/red] Model returned empty content "
                    f"(finish_reason={finish}, completion_tokens={comp}, "
                    f"reasoning_tokens={reasoning}). "
                    f"Increase max_tokens for reasoning models."
                )
                return None
            return content
        except requests.ConnectionError:
            console.print(f"[red]AI Error: Could not connect to[/red] {url}\n  Check the URL and your network connection.")
            return None
        except requests.ReadTimeout:
            if attempt == 0:
                console.print("[yellow]AI request timed out, retrying...[/yellow]")
                continue
            console.print(f"[red]AI Error: Request timed out after {timeout}s.[/red]")
            return None
        except requests.RequestException as e:
            console.print(f"[red]AI Error:[/red] {e}")
            return None
        except Exception as e:
            console.print(f"[red]AI Error: Unexpected error:[/red] {e}")
            return None
    return None


def _extract_json(text: str) -> Optional[dict[str, Any]]:
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


PROFILE_EXTRACTION_PROMPT = """Extract structured information from this resume as JSON.

Resume text:
{text}

Return valid JSON with these exact keys:
- "name": full name of the person
- "title": most recent or current job title (e.g. "Senior DevOps Engineer")
- "headline": one-line professional summary
- "skills": array of ALL technical and professional skills mentioned (languages, frameworks, tools, platforms, methodologies — be comprehensive)
- "experience": total years of professional experience as a number, or null if not mentioned
- "summary": 2-3 sentence professional summary

Rules:
- Extract the title from the resume context, don't guess
- List EVERY skill mentioned — programming languages, cloud platforms, CI/CD tools, monitoring, databases, containers, etc.
- If experience is ambiguous, use null rather than guessing"""


def ai_extract_profile(text: str) -> Optional[dict[str, Any]]:
    if not check_ai_available():
        return None
    prompt = PROFILE_EXTRACTION_PROMPT.format(text=text[:4000])
    result = _call_ai(
        [{"role": "user", "content": prompt}],
        max_tokens=16384,
        timeout=300,
    )
    if not result:
        return None
    parsed = _extract_json(result)
    if not parsed or not isinstance(parsed, dict):
        console.print("[red]AI Error:[/red] Could not parse profile extraction response as JSON.")
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


SUGGEST_TITLES_PROMPT = """You are a career advisor. Given a list of technical skills, suggest 3-5 job titles that best match this skill set.

Skills: {skills}

Return valid JSON:
{{
  "titles": ["title1", "title2", "title3", ...]
}}

Rules:
- Suggest titles that match the overall skill profile, not just one skill
- Cover related roles (e.g. "DevOps Engineer", "Platform Engineer", "Cloud Engineer" for infrastructure skills)
- Return exactly 3-5 titles, ordered by best match first"""


def ai_suggest_titles(skills: list[str]) -> Optional[list[str]]:
    if not check_ai_available() or not skills:
        return None
    prompt = SUGGEST_TITLES_PROMPT.format(skills=", ".join(skills))
    result = _call_ai(
        [{"role": "user", "content": prompt}],
        max_tokens=4096,
    )
    if not result:
        return None
    parsed = _extract_json(result)
    if not parsed or not isinstance(parsed, dict):
        console.print("[red]AI Error:[/red] Could not parse title suggestion response as JSON.")
        return None
    titles = parsed.get("titles", [])
    if not isinstance(titles, list) or len(titles) < 1:
        console.print("[red]AI Error:[/red] Title suggestion response missing 'titles' list.")
        return None
    return [t.strip() for t in titles if t.strip()][:5]


QUERY_GENERATION_PROMPT = """You are a job search strategist. Given a candidate's profile, generate 3-5 diverse search queries that will find the best matching jobs.

Each query must combine a role title and a specific skill from the profile.

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
- Each query should be 2-4 words, combining a job title with ONE specific skill (e.g. "AWS DevOps Engineer", "Terraform Cloud Engineer", "Kubernetes SRE")
- Cover different role types AND different skills
- Include location-relevant terms if location is specified
- Return 3-5 queries"""


def ai_generate_queries(profile: dict[str, Any]) -> Optional[list[str]]:
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
        max_tokens=4096,
    )
    if not result:
        return None
    parsed = _extract_json(result)
    if not parsed or not isinstance(parsed, dict):
        console.print("[red]AI Error:[/red] Could not parse query generation response as JSON.")
        return None
    queries = parsed.get("queries", [])
    if not isinstance(queries, list) or len(queries) < 1:
        console.print("[red]AI Error:[/red] Query generation response missing 'queries' list.")
        return None
    return [q.strip() for q in queries if q.strip()][:5]


JOB_SCORING_PROMPT = """You are a critical job matching analyst. Score how well a job fits a candidate's profile.

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
- Skills match (40%): how many of the candidate's core skills are relevant
- Title/role match (25%): does the job leverage the candidate's actual expertise?
- Experience fit (20%): is the seniority level appropriate?
- Location fit (15%): same city = best, same region = OK, remote = neutral

Guidelines:
- Score 80+ for strong skills overlap AND aligned role
- Score 50-79 for adjacent roles with partial relevance
- Score 25-49 for tangential roles
- Score 0-24 for irrelevant roles
- Include specific, honest reasons mentioning what's missing if relevant"""


def ai_score_job(profile: dict[str, Any], job: dict[str, Any]) -> Optional[dict[str, Any]]:
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
        max_tokens=16384,
        timeout=300,
    )
    if not result:
        return None
    parsed = _extract_json(result)
    if not parsed or not isinstance(parsed, dict):
        console.print("[red]AI Error:[/red] Could not parse job scoring response as JSON.")
        return None
    score = parsed.get("score")
    if not isinstance(score, (int, float)):
        console.print("[red]AI Error:[/red] Job scoring response missing valid 'score' field.")
        return None
    return {
        "score": max(0, min(100, round(float(score), 1))),
        "reasons": parsed.get("reasons", [])[:8],
    }
