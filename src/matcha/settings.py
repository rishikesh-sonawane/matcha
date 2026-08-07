import copy
import logging
from pathlib import Path
from typing import Any

import yaml

from matcha.models import Settings

logger = logging.getLogger(__name__)

LOCAL_CONFIG = Path("matcha.yaml")
USER_CONFIG = Path.home() / ".matcha" / "settings.yaml"

_DEFAULTS: dict[str, Any] = {
    "search": {
        "query": "",
        "location": "",
        "days": 7,
        "max_pages": 2,
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
