import json
import logging
from pathlib import Path
from typing import Any

from matcha.models import ConfigSchema

logger = logging.getLogger(__name__)

CONFIG_DIR = Path.home() / ".matcha"
CONFIG_FILE = CONFIG_DIR / "config.json"
PROFILE_FILE = CONFIG_DIR / "profile.json"
FERNET_KEY_FILE = CONFIG_DIR / "fernet.key"

# Tracks whether keyring is available at import time
_KEYRING_AVAILABLE: bool = False
try:
    import keyring

    _KEYRING_AVAILABLE = True
except ImportError:
    pass

_FERNET_AVAILABLE: bool = False
_Fernet: type | None = None
try:
    from cryptography.fernet import Fernet as _Fernet

    _FERNET_AVAILABLE = True
except ImportError:
    pass

_KEYRING_SERVICE = "matcha"
_KEYRING_KEYS = {"ai_key", "serpapi_key", "ai_url", "ai_model"}
_SECRET_CONFIG_KEYS = {"ai_key", "serpapi_key"}


def _get_fernet() -> Any:
    if not _FERNET_AVAILABLE:
        return None
    if FERNET_KEY_FILE.exists():
        key = FERNET_KEY_FILE.read_bytes()
    else:
        key = _Fernet.generate_key()
        tmp = FERNET_KEY_FILE.with_suffix(".key.tmp")
        tmp.write_bytes(key)
        tmp.chmod(0o600)
        tmp.rename(FERNET_KEY_FILE)
    return _Fernet(key)


def _read_encrypted(key: str) -> str:
    cipher = _get_fernet()
    if cipher is None:
        return ""
    enc_path = CONFIG_DIR / f".{key}.enc"
    if not enc_path.exists():
        return ""
    try:
        return cipher.decrypt(enc_path.read_bytes()).decode("utf-8")
    except Exception as e:
        logger.warning("Failed to decrypt %s: %s", key, e)
        return ""


def _write_encrypted(key: str, value: str) -> None:
    cipher = _get_fernet()
    if cipher is None:
        return
    enc_path = CONFIG_DIR / f".{key}.enc"
    try:
        enc_path.write_bytes(cipher.encrypt(value.encode("utf-8")))
        enc_path.chmod(0o600)
    except Exception as e:
        logger.warning("Failed to encrypt %s: %s", key, e)


def _delete_encrypted(key: str) -> None:
    enc_path = CONFIG_DIR / f".{key}.enc"
    if enc_path.exists():
        enc_path.unlink()


def ensure_config_dir() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def _read_secret(key: str) -> str:
    if _KEYRING_AVAILABLE:
        try:
            val = keyring.get_password(_KEYRING_SERVICE, key)
            if val:
                return val
        except Exception:
            pass
    if _FERNET_AVAILABLE:
        return _read_encrypted(key)
    return ""


def _write_secret(key: str, value: str) -> None:
    if _KEYRING_AVAILABLE:
        try:
            keyring.set_password(_KEYRING_SERVICE, key, value)
            return
        except Exception:
            pass
    if _FERNET_AVAILABLE:
        _write_encrypted(key, value)
    else:
        logger.warning(
            "No secure backend available (install keyring or cryptography). "
            "Secrets stored in plaintext."
        )


def _delete_secret(key: str) -> None:
    if _KEYRING_AVAILABLE:
        try:
            keyring.delete_password(_KEYRING_SERVICE, key)
            return
        except Exception:
            pass
    if _FERNET_AVAILABLE:
        _delete_encrypted(key)


def _load_config_raw() -> dict[str, Any]:
    ensure_config_dir()
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to load config: %s", e)
    return {}


def load_config() -> dict[str, Any]:
    raw = _load_config_raw()
    for key in _KEYRING_KEYS:
        if key in _SECRET_CONFIG_KEYS:
            stored = _read_secret(key)
            if stored:
                raw[key] = stored
        else:
            if key not in raw:
                stored = _read_secret(key)
                if stored:
                    raw[key] = stored
    try:
        validated = ConfigSchema(**raw)
        merged = validated.model_dump()
        raw.update({k: v for k, v in merged.items() if v or k not in raw})
    except Exception as e:
        logger.warning("Config validation failed: %s", e)
    return raw


def save_config(config: dict[str, Any]) -> None:
    ensure_config_dir()
    config = dict(config)
    secrets = {k: config.pop(k, "") for k in _SECRET_CONFIG_KEYS}
    other_secrets = {k: config.pop(k, "") for k in _KEYRING_KEYS - _SECRET_CONFIG_KEYS}
    try:
        validated = ConfigSchema(**config)
        serializable = validated.model_dump()
        unknown_keys = {k: v for k, v in config.items() if k not in ConfigSchema.model_fields}
        serializable.update(unknown_keys)
        with open(CONFIG_FILE, "w") as f:
            json.dump(serializable, f, indent=2)
    except Exception as e:
        logger.warning("Failed to save config JSON: %s", e)
        with open(CONFIG_FILE, "w") as f:
            json.dump(config, f, indent=2)
    for key, value in secrets.items():
        if value:
            _write_secret(key, value)
        else:
            _delete_secret(key)
    for key, value in other_secrets.items():
        if value:
            _write_secret(key, value)


def load_profile() -> dict[str, Any] | None:
    ensure_config_dir()
    if PROFILE_FILE.exists():
        try:
            with open(PROFILE_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to load profile: %s", e)
    return None


def save_profile(profile: dict[str, Any]) -> None:
    ensure_config_dir()
    try:
        with open(PROFILE_FILE, "w") as f:
            json.dump(profile, f, indent=2)
    except OSError as e:
        logger.error("Failed to save profile: %s", e)
