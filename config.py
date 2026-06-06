import json
from pathlib import Path
from typing import Any, Optional

from rich.console import Console

CONFIG_DIR = Path.home() / ".matcha"
CONFIG_FILE = CONFIG_DIR / "config.json"
PROFILE_FILE = CONFIG_DIR / "profile.json"

console = Console()


def ensure_config_dir() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def _try_load_json(path: Path) -> Optional[dict[str, Any]]:
    if not path.exists():
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        console.print(f"[yellow]Warning: Corrupted config file {path.name}: {e}[/yellow]")
        return None
    except OSError as e:
        console.print(f"[yellow]Warning: Could not read {path.name}: {e}[/yellow]")
        return None


def _try_save_json(path: Path, data: dict[str, Any]) -> bool:
    ensure_config_dir()
    try:
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
        return True
    except OSError as e:
        console.print(f"[red]Error: Could not write {path.name}: {e}[/red]")
        return False


def load_config() -> dict[str, Any]:
    result = _try_load_json(CONFIG_FILE)
    return result or {}


def save_config(config: dict[str, Any]) -> bool:
    return _try_save_json(CONFIG_FILE, config)


def load_profile() -> Optional[dict[str, Any]]:
    return _try_load_json(PROFILE_FILE)


def save_profile(profile: dict[str, Any]) -> bool:
    return _try_save_json(PROFILE_FILE, profile)
