import copy
import logging
from pathlib import Path
from typing import Any

import yaml

from matcha.models import Settings

logger = logging.getLogger(__name__)

LOCAL_CONFIG = Path("matcha.yaml")
USER_CONFIG = Path.home() / ".matcha" / "settings.yaml"

#: Wall-time budget for one search's scraper batch (seconds). Session 29:
#: raised from the hardcoded 75s — Web Search now runs up to 6 queries and
#: the Exa backend (up to 30s per call, parallel) must not be cut off while
#: other sources are still streaming in. Overridable via ``search.batch_timeout``.
DEFAULT_BATCH_TIMEOUT = 120

#: Per-source query caps — how many of the (up to 6) AI-expanded queries
#: each source runs in one search. Session 21 capped the DDGS-heavy sources
#: so 6 queries don't explode into 40+ slow searches that starve under the
#: batch timeout. Session 28 raised Web Search 3 -> 6: Exa is now the
#: primary backend (one fast mcporter call per query), so every AI query
#: contributes semantic postings. The Web Search entry is ADAPTIVE (Session
#: 29): when Exa is not configured the slow DDGS fallback takes over and the
#: cap is clamped back down to :data:`DDGS_WEB_SEARCH_CAP` (3). Shared with
#: main.run_search's fallback so the defaults can't drift.
DEFAULT_QUERY_CAPS = {"Career Sites": 2, "Web Search": 6, "Naukri": 3}

#: DDGS-safe Web Search cap — the DDGS fallback fans out into 5 rate-limited
#: site queries per search query, so the raised Exa cap would regularly blow
#: the scraper batch timeout on the slow path. Clamped in main.run_search
#: whenever Exa is not configured (Session 29).
DDGS_WEB_SEARCH_CAP = 3

_DEFAULTS: dict[str, Any] = {
    "search": {
        "query": "",
        "location": "",
        "days": 7,
        "max_pages": 2,
        "batch_timeout": DEFAULT_BATCH_TIMEOUT,
    },
    "ai": {
        "enabled": True,
        "top_n": 30,
        "timeout": 60,
        "model_best": "",
        "model_fast": "",
        "max_calls": 60,
        # Disk cache TTL (seconds); 0 = disabled. Opt-in so the tool never
        # serves stale AI output by default (strategy §10.2).
        "cache_ttl": 0,
        # §9.5 optional top-K "would you apply?" verdicts; 0 = disabled.
        "verdict_k": 5,
    },
    "scrapers": {
        "serpapi": False,
        "indeed_domain": "in.indeed.com",
        "career_sites": False,
        "query_caps": dict(DEFAULT_QUERY_CAPS),
    },
    "enrichment": {
        "enabled": True,
        "top_n": 30,
        "timeout": 30,
        "max_workers": 5,
    },
    "filters": {
        "days": 7,
        "strict_age": False,
        "min_must_matches": 1,
        "soft_must_skills": False,
        "remote": False,
        "min_salary": 0,
        "drop_unknown_salary": False,
        "strict_location": False,
    },
    "ranking": {
        "normalize_scores": False,
    },
    "sources": {
        "rss": {"feeds": []},
    },
}


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> None:
    for key, value in overlay.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value


def load_settings(config_path: str | None = None) -> dict[str, Any]:
    paths: list[Path] = []
    if config_path:
        paths.append(Path(config_path))
    paths.append(LOCAL_CONFIG)
    paths.append(USER_CONFIG)

    settings: dict[str, Any] = copy.deepcopy(_DEFAULTS)

    for p in paths:
        if p.exists():
            try:
                with open(p) as f:
                    loaded = yaml.safe_load(f)
                    if loaded:
                        _deep_merge(settings, loaded)
            except (yaml.YAMLError, OSError) as e:
                logger.warning("Failed to load settings from %s: %s", p, e)

    try:
        validated = Settings(**settings)
        merged = validated.model_dump()
        settings.update({k: v for k, v in merged.items() if v is not None})
    except Exception as e:
        logger.warning("Settings validation failed: %s", e)

    return settings
