"""Provider-agnostic AI client (strategy §10, Phase 5).

OpenAI-compatible REST against ``{base_url}/chat/completions`` with:

- **Provider presets** (``PROVIDERS``): Groq, Kilo Gateway (default),
  OpenRouter, OpenAI/any compatible endpoint, and local (Ollama/LM Studio —
  no API key required).
- **Model tiers**: ``model_fast`` for high-volume low-stakes tasks (query
  generation, title suggestion); ``model_best`` for scoring/profile
  extraction. Resolution order per tier:
  env var → config.json → settings.yaml → provider preset default.
- **Budget guard**: ``max_calls`` per run caps spend/latency; once
  exhausted, remaining calls return None and jobs keep heuristic scores.
  Reported via ``budget_used()``/``budget_remaining()``.
- **Disk cache** (``ai_cache.py``): opt-in via ``settings.ai.cache_ttl > 0``
  (default 0 = disabled); keyed by task + sha256(inputs), SQLite, TTL'd.
- **No API key required to run the tool**: missing key ⇒ heuristic-only mode.

Backwards-compatible surface kept intact for existing callers/tests:
``_get_api_key/_get_api_url/_get_model/check_ai_available/configure_ai/
_call_ai/_extract_json`` + the four task functions.
"""

import json
import logging
import os
import re
import threading
import time
from typing import Any

import requests

from matcha import ai_cache
from matcha.config import load_config, save_config
from matcha.settings import load_settings

logger = logging.getLogger(__name__)

AI_API_URL = ""
AI_MODEL = ""
CONFIG_KEY = "ai_key"
ENV_VAR = "MINIMAX"
CONFIG_URL_KEY = "ai_url"
CONFIG_MODEL_KEY = "ai_model"
CONFIG_PROVIDER_KEY = "ai_provider"

#: One retry after ConnectionError/Timeout/non-200, with a short backoff so
#: transient provider hiccups don't hammer the endpoint.
_RETRY_BACKOFF_SECONDS = 0.25

#: Provider presets (strategy §10.2). ``url`` is the OpenAI-compatible BASE
#: URL — ``/chat/completions`` is appended at call time. ``model_best`` /
#: ``model_fast`` are only defaults; every layer above can override them.
#: ``requires_key=False`` providers (local endpoints) skip the API key check.
PROVIDERS: dict[str, dict[str, Any]] = {
    "groq": {
        "label": "Groq (free tier)",
        "url": "https://api.groq.com/openai/v1",
        "model_best": "openai/gpt-oss-120b",
        "model_fast": "openai/gpt-oss-20b",
    },
    "kilo": {
        "label": "Kilo Gateway (default)",
        "url": "https://api.kilo.ai/api/gateway",
        "model_best": "kilo-auto/small",
        "model_fast": "kilo-auto/small",
    },
    "openrouter": {
        "label": "OpenRouter (free models)",
        "url": "https://openrouter.ai/api/v1",
        "model_best": "meta-llama/llama-3.3-70b-instruct:free",
        "model_fast": "meta-llama/llama-3.1-8b-instruct:free",
    },
    "openai": {
        "label": "OpenAI / any compatible endpoint",
        "url": "https://api.openai.com/v1",
        "model_best": "gpt-4o-mini",
        "model_fast": "gpt-4o-mini",
    },
    "local": {
        "label": "Local (Ollama / LM Studio)",
        "url": "http://localhost:11434/v1",
        "model_best": "",  # user must name a model (e.g. llama3)
        "model_fast": "",
        "requires_key": False,
    },
}


# ── budget guard (thread-safe: AI scoring runs in a pool) ──────────────

_budget_lock = threading.Lock()
_budget_used = 0
_budget_max = 0  # 0 = unlimited until run() calls reset_budget()
_budget_warned = False

#: Settings values are re-read on a short TTL so config edits take effect
#: within a run without re-parsing YAML on every call.
_SETTINGS_TTL_SECONDS = 5.0
_settings_ts = 0.0
_settings_value: dict[str, Any] | None = None


def _ai_settings() -> dict[str, Any]:
    global _settings_ts, _settings_value
    now = time.monotonic()
    if now - _settings_ts > _SETTINGS_TTL_SECONDS:
        _settings_value = load_settings()
        _settings_ts = now
    return _settings_value or {}


def reset_budget(max_calls: int | None = None) -> None:
    """Start a fresh AI budget for a run.

    ``max_calls=None`` uses ``settings.ai.max_calls`` (default 60). Calling
    this also un-warns the exhaustion message so a later run can warn again.
    """
    global _budget_used, _budget_max, _budget_warned
    if max_calls is None:
        max_calls = int(_ai_settings().get("ai", {}).get("max_calls", 60))
    with _budget_lock:
        _budget_used = 0
        _budget_max = max(0, int(max_calls))
        _budget_warned = False


def budget_used() -> int:
    with _budget_lock:
        return _budget_used


def budget_remaining() -> int:
    """Calls left this run; -1 when unlimited (no cap configured)."""
    with _budget_lock:
        if _budget_max <= 0:
            return -1
        return max(0, _budget_max - _budget_used)


def _consume_budget() -> bool:
    global _budget_used, _budget_warned
    with _budget_lock:
        if _budget_max > 0 and _budget_used >= _budget_max:
            if not _budget_warned:
                _budget_warned = True
                logger.warning(
                    "AI budget exhausted (%d calls) — remaining jobs keep heuristic scores",
                    _budget_max,
                )
            return False
        _budget_used += 1
        return True


# ── provider + credential resolution ───────────────────────────────────


def _env_or_config(env_var: str, config_key: str, default: str = "") -> str:
    val = os.environ.get(env_var, "")
    if val:
        return val
    config = load_config()
    return config.get(config_key, default)


def _get_api_key() -> str:
    return _env_or_config(ENV_VAR, CONFIG_KEY)


def _get_provider() -> str:
    val = os.environ.get("AI_PROVIDER", "")
    if val:
        return val.strip().lower()
    config = load_config()
    return str(config.get(CONFIG_PROVIDER_KEY, "")).strip().lower()


def _normalize_chat_url(url: str) -> str:
    """Ensure a base URL points at the chat completions endpoint."""
    url = (url or "").strip().rstrip("/")
    if not url:
        return ""
    if url.endswith("/chat/completions"):
        return url
    return f"{url}/chat/completions"


def _get_api_url() -> str:
    val = os.environ.get("AI_API_URL", "")
    if val:
        return val
    config = load_config()
    val = config.get(CONFIG_URL_KEY, "")
    if val:
        return val
    return str(PROVIDERS.get(_get_provider(), {}).get("url", ""))


def _get_model(tier: str = "best") -> str:
    """Resolve the model for a tier: best (scoring/profile) or fast (queries).

    Order per tier: env → config.json → settings.yaml → provider preset.
    ``fast`` falls back to the ``best`` resolution before its own preset.
    """
    provider = _get_provider()
    preset = PROVIDERS.get(provider, {})

    if tier == "fast":
        val = os.environ.get("AI_MODEL_FAST", "")
        if val:
            return val
        val = _ai_settings().get("ai", {}).get("model_fast", "")
        if val:
            return val
        preset_fast = str(preset.get("model_fast", ""))
        if preset_fast:
            return preset_fast
        # Providers without a distinct fast default (e.g. local) reuse best.
        return _get_model("best")

    val = os.environ.get("AI_MODEL", "")
    if val:
        return val
    config = load_config()
    val = config.get(CONFIG_MODEL_KEY, "")
    if val:
        return val
    val = _ai_settings().get("ai", {}).get("model_best", "")
    if val:
        return val
    return str(preset.get("model_best", ""))


def check_ai_available() -> bool:
    provider = _get_provider()
    if not PROVIDERS.get(provider, {}).get("requires_key", True):
        # Local endpoints (Ollama/LM Studio) need no API key.
        return bool(_get_api_url() and _get_model())
    return bool(_get_api_key() and _get_api_url() and _get_model())


def ai_status() -> dict[str, Any]:
    """Machine-readable AI configuration snapshot (used by ``matcha doctor``).

    Returns the RESOLVED values a run would actually use (env var →
    config.json → settings.yaml → provider preset default). The API key
    itself is NEVER returned — only a ``key_set`` boolean — so doctor
    output can never leak credentials.
    """
    provider = _get_provider()
    preset = PROVIDERS.get(provider, {})
    requires_key = bool(preset.get("requires_key", True))
    key_set = bool(_get_api_key())
    url = _get_api_url()
    model_best = _get_model("best")
    model_fast = _get_model("fast")
    # Availability verdict computed from the exact resolved values shown
    # above (mirrors check_ai_available): needs URL + model, plus a key
    # unless the provider is keyless (local endpoints).
    available = bool(url and model_best) and (key_set or not requires_key)
    return {
        "provider": provider,  # "" = no provider configured
        "provider_label": preset.get("label", "") or "Not configured",
        "known_provider": provider in PROVIDERS,
        "requires_key": requires_key,
        "key_set": key_set,
        "url": url,
        "model_best": model_best,
        "model_fast": model_fast,
        "available": available,
    }


def configure_ai(key: str, url: str = "", model: str = "") -> None:
    config = load_config()
    config[CONFIG_KEY] = key
    if url:
        config[CONFIG_URL_KEY] = url
    if model:
        config[CONFIG_MODEL_KEY] = model
    save_config(config)


def configure_provider(provider: str, key: str = "", url: str = "", model: str = "") -> None:
    """Persist a provider preset choice (+ optional overrides).

    ``provider`` must be a ``PROVIDERS`` key (or "" to clear). When an
    override is empty, any previously stored url/model is cleared so the
    preset (or env/settings) owns that slot — switching providers must not
    keep another provider's endpoint.
    """
    if provider and provider not in PROVIDERS:
        raise ValueError(f"Unknown AI provider: {provider!r}")
    config = load_config()
    config[CONFIG_PROVIDER_KEY] = provider
    if key:
        config[CONFIG_KEY] = key
    if url:
        config[CONFIG_URL_KEY] = url
    else:
        config.pop(CONFIG_URL_KEY, None)
    if model:
        config[CONFIG_MODEL_KEY] = model
    else:
        config.pop(CONFIG_MODEL_KEY, None)
    save_config(config)


# ── transport ──────────────────────────────────────────────────────────


def _call_ai(
    messages: list[dict[str, Any]],
    response_format: dict[str, Any] | None = None,
    max_tokens: int = 8192,
    timeout: int = 60,
    tier: str = "best",
) -> str | None:
    key = _get_api_key()
    url = _get_api_url()
    model = _get_model(tier)
    if not url or not model:
        return None
    provider = _get_provider()
    if PROVIDERS.get(provider, {}).get("requires_key", True) and not key:
        return None
    if not _consume_budget():
        return None

    headers: dict[str, str] = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0.1,
    }
    if response_format:
        payload["response_format"] = response_format

    endpoint = _normalize_chat_url(url)
    for attempt in range(2):
        try:
            resp = requests.post(endpoint, headers=headers, json=payload, timeout=timeout)
            if resp.status_code != 200:
                if attempt < 1:
                    logger.warning(
                        "AI API returned %d, retrying (attempt %d/2)",
                        resp.status_code,
                        attempt + 1,
                    )
                    time.sleep(_RETRY_BACKOFF_SECONDS)
                    continue
                return None
            data = resp.json()
            choices = data.get("choices", [])
            if not choices:
                return None
            content = choices[0].get("message", {}).get("content", "")
            if not content:
                usage = data.get("usage", {})
                finish = choices[0].get("finish_reason", "unknown")
                comp_tokens = usage.get("completion_tokens", 0)
                reason_tokens = usage.get("reasoning_tokens", 0)
                logger.warning(
                    "AI returned empty content. "
                    "finish_reason=%s, completion_tokens=%s, reasoning_tokens=%s. "
                    "Increase max_tokens for reasoning models.",
                    finish,
                    comp_tokens,
                    reason_tokens,
                )
                return None
            return content
        except (requests.ConnectionError, requests.Timeout) as e:
            if attempt < 1:
                logger.warning(
                    "AI request failed: %s, retrying (attempt %d/2)",
                    e,
                    attempt + 1,
                )
                time.sleep(_RETRY_BACKOFF_SECONDS)
                continue
            logger.warning("AI request failed after 2 attempts: %s", e)
            return None
        except requests.RequestException as e:
            logger.warning("AI request failed: %s", e)
            return None
    return None


def _run_with_cache(
    task: str,
    messages: list[dict[str, Any]],
    max_tokens: int,
    timeout: int,
    tier: str,
) -> str | None:
    """Call ``_call_ai`` with an optional disk-cache round-trip.

    Cache engages only when ``settings.ai.cache_ttl > 0`` (opt-in; default
    0). The cache key is ``task + resolved model + the exact messages sent``
    — so switching providers/models or editing a prompt self-invalidates
    entries, and prompt-side truncation is hashed exactly. Cache hits don't
    consume AI budget. The raw completion text is cached; parsing happens on
    every hit (cheap, and keeps the cache generic).
    """
    ttl = int(_ai_settings().get("ai", {}).get("cache_ttl", 0) or 0)
    if ttl > 0:
        key = ai_cache.cache_key(task, _get_model(tier), messages)
        hit = ai_cache.get(task, key, ttl)
        if hit is not None:
            return hit
    result = _call_ai(messages, max_tokens=max_tokens, timeout=timeout, tier=tier)
    if result is not None and ttl > 0:
        ai_cache.put(task, ai_cache.cache_key(task, _get_model(tier), messages), result)
    return result


def _extract_json(text: str) -> dict[str, Any] | None:
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


def ai_extract_profile(text: str) -> dict[str, Any] | None:
    if not check_ai_available():
        return None
    prompt = PROFILE_EXTRACTION_PROMPT.format(text=text[:4000])
    result = _run_with_cache(
        "extract_profile",
        [{"role": "user", "content": prompt}],
        max_tokens=16384,
        timeout=300,
        tier="best",
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


def ai_suggest_titles(skills: list[str]) -> list[str] | None:
    if not check_ai_available() or not skills:
        return None
    prompt = SUGGEST_TITLES_PROMPT.format(skills=", ".join(skills))
    result = _run_with_cache(
        "suggest_titles",
        [{"role": "user", "content": prompt}],
        max_tokens=4096,
        timeout=60,
        tier="fast",
    )
    if not result:
        return None
    parsed = _extract_json(result)
    if not parsed or not isinstance(parsed, dict):
        return None
    titles = parsed.get("titles", [])
    if not isinstance(titles, list) or len(titles) < 1:
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


def ai_generate_queries(profile: dict[str, Any]) -> list[str] | None:
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
    result = _run_with_cache(
        "generate_queries",
        [{"role": "user", "content": prompt}],
        max_tokens=8192,
        timeout=60,
        tier="fast",
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
- Experience fit (20%): is the seniority level appropriate for someone with {experience} years? penalize roles requiring significantly more experience (principal, architect, staff, distinguished) or less (intern, junior)
- Location fit (15%): same city = best, same region = OK, remote = neutral

Guidelines:
- Score 80+ for strong skills overlap AND aligned role
- Score 50-79 for adjacent roles with partial relevance
- Score 25-49 for tangential roles
- Score 0-24 for irrelevant roles
- Include specific, honest reasons mentioning what's missing if relevant
- A candidate with ~4 years experience is NOT a fit for principal, architect, staff, or distinguished engineer roles — heavily penalize these regardless of skills"""


def ai_score_job(
    profile: dict[str, Any], job: dict[str, Any], timeout: int = 60
) -> dict[str, Any] | None:
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
    result = _run_with_cache(
        "score_job",
        [{"role": "user", "content": prompt}],
        max_tokens=16384,
        timeout=timeout,
        tier="best",
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


JOB_VERDICT_PROMPT = """You are a senior recruiter advising one candidate. Give a crisp go/no-go verdict on ONE job.

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
- Salary: {job_salary}
- Description: {job_description}

Return valid JSON:
{{
  "recommend": true or false,
  "line": "one short sentence (<20 words) explaining the recommendation"
}}

Rules:
- recommend=true only if you would genuinely tell THIS candidate to apply
- The line must be specific to this candidate + this job (skills overlap, seniority fit, location or salary concerns) — never generic filler"""


def ai_verdict(
    profile: dict[str, Any], job: dict[str, Any], timeout: int = 60
) -> dict[str, Any] | None:
    """Optional final verdict (§9.5): "would you actually recommend applying?"

    Returns ``{"recommend": bool, "line": str}`` (rendered in the TUI detail
    panel + surfaced in ``search --json``) or None when unavailable / unparsable.
    Gated on AI availability, cached + budget-limited like every other task.
    Callers gate on ``matcher.ai_eligible`` so bare snippet rows are never
    judged.
    """
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
    job_salary = job.get("salary", "") or ""
    job_description = (job.get("description", "") or "")[:1000]

    prompt = JOB_VERDICT_PROMPT.format(
        title=title,
        headline=headline,
        skills=skills,
        experience=experience,
        summary=summary,
        location=location,
        job_title=job_title,
        job_company=job_company,
        job_location=job_location,
        job_salary=job_salary,
        job_description=job_description,
    )
    result = _run_with_cache(
        "verdict",
        [{"role": "user", "content": prompt}],
        max_tokens=4096,
        timeout=timeout,
        tier="best",
    )
    if not result:
        return None
    parsed = _extract_json(result)
    if not parsed or not isinstance(parsed, dict):
        return None
    recommend = parsed.get("recommend")
    line = parsed.get("line")
    if not isinstance(recommend, bool) or not isinstance(line, str) or not line.strip():
        return None
    return {"recommend": recommend, "line": line.strip()}
