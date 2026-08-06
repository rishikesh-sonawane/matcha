"""Job-source registry for Matcha 2.0 (strategy §16).

Every source lives in one module under ``matcha.sources`` and subclasses
:class:`~matcha.sources.base.Source`. ``ALL_SOURCES`` is the single registry
consumed by doctor today and by the multi-backend search dispatcher in
Phase 1+.
"""

from matcha.sources.base import Source
from matcha.sources.career_sites import CareerSitesSource
from matcha.sources.indeed import IndeedSource
from matcha.sources.linkedin import LinkedInSource
from matcha.sources.naukri import NaukriSource
from matcha.sources.remoteok import RemoteOKSource
from matcha.sources.serpapi_jobs import SerpapiSource
from matcha.sources.web_search import WebSearchSource

ALL_SOURCES: list[Source] = [
    LinkedInSource(),
    IndeedSource(),
    NaukriSource(),
    RemoteOKSource(),
    WebSearchSource(),
    SerpapiSource(),
    CareerSitesSource(),
]

_SOURCES_BY_NAME: dict[str, Source] = {s.name: s for s in ALL_SOURCES}


def get_all_sources() -> list[Source]:
    """Return the source registry (a fresh list of the singletons)."""
    return list(ALL_SOURCES)


def get_source(name: str) -> Source | None:
    """Look up a source by its registry name."""
    return _SOURCES_BY_NAME.get(name)
