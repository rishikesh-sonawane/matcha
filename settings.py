from pathlib import Path
from typing import Any, Optional

import yaml

LOCAL_CONFIG = Path("matcha.yaml")
USER_CONFIG = Path.home() / ".matcha" / "settings.yaml"

DEFAULT_CONFIG = {
    "search": {
        "query": "",
        "location": "",
        "days": 7,
    },
    "ai": {
        "enabled": True,
    },
    "scrapers": {
        "serpapi": False,
    },
}


def load_settings(config_path: Optional[str] = None) -> dict[str, Any]:
    paths: list[Path] = []
    if config_path:
        paths.append(Path(config_path))
    paths.append(LOCAL_CONFIG)
    paths.append(USER_CONFIG)

    settings: dict[str, Any] = dict(DEFAULT_CONFIG)

    for p in paths:
        if p.exists():
            with open(p) as f:
                loaded = yaml.safe_load(f)
                if loaded:
                    _deep_merge(settings, loaded)

    return settings


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> None:
    for key, value in overlay.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
