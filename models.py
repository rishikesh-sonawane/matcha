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


class Profile(BaseModel):
    name: str = ""
    title: str = ""
    headline: str = ""
    skills: list[str] = Field(default_factory=list)
    experience: str = ""
    summary: str = ""
    location: str = ""


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
    last_query: str = ""
    last_location: str = ""
    last_days: int = 7


class SearchConfig(BaseModel):
    query: str = ""
    location: str = ""
    days: int = 7
    max_pages: int = 2


class AIConfig(BaseModel):
    enabled: bool = True
    top_n: int = 30
    timeout: int = 60


class ScraperConfig(BaseModel):
    serpapi: bool = False
    indeed_domain: str = "in.indeed.com"


class Settings(BaseModel):
    search: SearchConfig = Field(default_factory=SearchConfig)
    ai: AIConfig = Field(default_factory=AIConfig)
    scrapers: ScraperConfig = Field(default_factory=ScraperConfig)
