from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field

#
# Runtime models
#


@dataclass
class ScraperResult:
    jobs: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    source: str = ""
    # Provenance (Phase 0, strategy §6.7): which backend produced the jobs
    # and how rich the data is. data_quality: "full" | "partial" | "snippet".
    backend: str = ""
    data_quality: str = "snippet"


#
# Pydantic persisted models
#


class Job(BaseModel):
    title: str = ""
    company: str = ""
    location: str = ""
    description: str = ""
    url: str = ""
    source: str = ""
    # enrichment + normalization (Phase 1/2, strategy §14)
    apply_url: str = ""
    salary: str = ""
    salary_int: int | None = None
    workplace_type: str = ""
    job_type: str = ""
    listed: str = ""
    listed_epoch: int | None = None
    applicants: str = ""
    company_url: str = ""
    # provenance
    backend: str = ""
    data_quality: str = "partial"  # full | partial | snippet
    city: str = ""
    region: str = ""
    remote_ok: bool = False


class Profile(BaseModel):
    name: str = ""
    title: str = ""
    headline: str = ""
    skills: list[str] = Field(default_factory=list)
    experience: str = ""
    summary: str = ""
    location: str = ""
    # Phase 2 filter preferences (strategy §7/§14)
    must_have_skills: list[str] = Field(default_factory=list)
    min_salary: int = 0
    remote_preference: str = ""  # remote | hybrid | onsite
    github_username: str = ""


class RelevanceResult(BaseModel):
    score: float = Field(ge=0.0, le=100.0)
    reasons: list[str] = Field(default_factory=list)


class SavedJob(BaseModel):
    title: str = ""
    company: str = ""
    url: str = ""
    source: str = ""


class ConfigSchema(BaseModel):
    ai_key: str = ""
    serpapi_key: str = ""
    ai_url: str = ""
    ai_model: str = ""
    ai_provider: str = ""  # Phase 5 preset: groq | kilo | openrouter | openai | local
    last_query: str = ""
    last_location: str = ""
    last_days: int = 7
    # OpenCLI consent (strategy §6.3): opt-in to the browser-bridge backend.
    linkedin_consent: bool = False
    indeed_consent: bool = False


class SearchConfig(BaseModel):
    query: str = ""
    location: str = ""
    days: int = 7
    max_pages: int = 2


class AIConfig(BaseModel):
    """AI client settings (strategy §10.2, Phase 5)."""

    enabled: bool = True
    top_n: int = 30
    timeout: int = 60
    model_best: str = ""  # scoring / profile extraction (default per provider)
    model_fast: str = ""  # query gen / title suggestion (default per provider)
    max_calls: int = 60  # budget guard per run
    cache_ttl: int = 0  # disk cache TTL in seconds; 0 = disabled (opt-in)


class ScraperConfig(BaseModel):
    serpapi: bool = False
    indeed_domain: str = "in.indeed.com"


class EnrichmentConfig(BaseModel):
    enabled: bool = True
    top_n: int = 30
    timeout: int = 30
    max_workers: int = 5


class FilterConfig(BaseModel):
    """Central filter pipeline settings (strategy §7.6)."""

    days: int = 7
    strict_age: bool = False
    min_must_matches: int = 1
    soft_must_skills: bool = False
    remote: bool = False
    min_salary: int = 0
    drop_unknown_salary: bool = False


class RankingConfig(BaseModel):
    """Phase 4 ranking recalibration (strategy §9)."""

    normalize_scores: bool = False  # stretch a flat score distribution onto [5,100]


class Settings(BaseModel):
    search: SearchConfig = Field(default_factory=SearchConfig)
    ai: AIConfig = Field(default_factory=AIConfig)
    scrapers: ScraperConfig = Field(default_factory=ScraperConfig)
    enrichment: EnrichmentConfig = Field(default_factory=EnrichmentConfig)
    filters: FilterConfig = Field(default_factory=FilterConfig)
    ranking: RankingConfig = Field(default_factory=RankingConfig)
