import json
from pathlib import Path
from typing import Any, Optional

CONFIG_DIR = Path.home() / ".job-finder"
CONFIG_FILE = CONFIG_DIR / "config.json"
PROFILE_FILE = CONFIG_DIR / "profile.json"


def ensure_config_dir() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def load_config() -> dict[str, Any]:
    ensure_config_dir()
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE) as f:
            return json.load(f)
    return {}


def save_config(config: dict[str, Any]) -> None:
    ensure_config_dir()
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)


def load_profile() -> Optional[dict[str, Any]]:
    ensure_config_dir()
    if PROFILE_FILE.exists():
        with open(PROFILE_FILE) as f:
            return json.load(f)
    return None


def save_profile(profile: dict[str, Any]) -> None:
    ensure_config_dir()
    with open(PROFILE_FILE, "w") as f:
        json.dump(profile, f, indent=2)
