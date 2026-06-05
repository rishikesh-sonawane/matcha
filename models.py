from pydantic import BaseModel, Field


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


class SearchConfig(BaseModel):
    query: str = ""
    location: str = ""
    days: int = 7


class AIConfig(BaseModel):
    enabled: bool = True


class ScraperConfig(BaseModel):
    serpapi: bool = False


class Settings(BaseModel):
    search: SearchConfig = Field(default_factory=SearchConfig)
    ai: AIConfig = Field(default_factory=AIConfig)
    scrapers: ScraperConfig = Field(default_factory=ScraperConfig)
