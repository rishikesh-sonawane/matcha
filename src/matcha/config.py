import json
import logging
from pathlib import Path
from typing import Any

from matcha.models import ConfigSchema
from matcha.utils import (
    ConfigSecurityError,
    atomic_write_text,
    make_private_dir,
    read_small_text_no_follow,
)

logger = logging.getLogger(__name__)

CONFIG_DIR = Path.home() / ".matcha"
CONFIG_FILE = CONFIG_DIR / "config.json"
PROFILE_FILE = CONFIG_DIR / "profile.json"
FERNET_KEY_FILE = CONFIG_DIR / "fernet.key"

#: Size cap for private JSON reads (Phase 7, strategy §17) — a config larger
#: than this is an attack or corruption, never a legit file.
_MAX_CONFIG_BYTES = 1024 * 1024

# Tracks whether keyring is available at import time
_KEYRING_AVAILABLE: bool = False
try:
    import keyring

    _KEYRING_AVAILABLE = True
except ImportError:
    pass

_FERNET_AVAILABLE: bool = False
_Fernet: Any = None
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
    try:
        raw = read_small_text_no_follow(FERNET_KEY_FILE, max_bytes=_MAX_CONFIG_BYTES)
    except ConfigSecurityError as e:
        logger.error("Refusing fernet key read: %s", e)
        return None
    if raw is not None:
        key = raw.encode("utf-8")
    else:
        try:
            key = _Fernet.generate_key()
            atomic_write_text(FERNET_KEY_FILE, key.decode("utf-8"))
        except (ConfigSecurityError, OSError) as e:
            # TOCTOU: key missing at read, symlink/inaccessible at write.
            logger.error("Refusing fernet key write: %s", e)
            return None
    return _Fernet(key)


def _read_encrypted(key: str) -> str:
    cipher = _get_fernet()
    if cipher is None:
        return ""
    enc_path = CONFIG_DIR / f".{key}.enc"
    try:
        raw = read_small_text_no_follow(enc_path, max_bytes=_MAX_CONFIG_BYTES)
    except ConfigSecurityError as e:
        logger.error("Refusing encrypted read for %s: %s", key, e)
        return ""
    if raw is None:
        return ""
    try:
        return cipher.decrypt(raw.encode("utf-8")).decode("utf-8")
    except Exception as e:
        logger.warning("Failed to decrypt %s: %s", key, e)
        return ""


def _write_encrypted(key: str, value: str) -> None:
    cipher = _get_fernet()
    if cipher is None:
        return
    enc_path = CONFIG_DIR / f".{key}.enc"
    try:
        atomic_write_text(enc_path, cipher.encrypt(value.encode("utf-8")).decode("utf-8"))
    except Exception as e:
        logger.warning("Failed to encrypt %s: %s", key, e)


def _delete_encrypted(key: str) -> None:
    enc_path = CONFIG_DIR / f".{key}.enc"
    if enc_path.exists():
        enc_path.unlink()


def ensure_config_dir() -> None:
    """Create the private config directory (0700) — writes only."""
    make_private_dir(CONFIG_DIR)


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
    """Read config.json without creating anything and refusing symlinks."""
    try:
        raw = read_small_text_no_follow(CONFIG_FILE, max_bytes=_MAX_CONFIG_BYTES)
    except ConfigSecurityError as e:
        logger.error("Refusing config read: %s", e)
        return {}
    if raw is None:
        return {}
    try:
        loaded = json.loads(raw)
        return loaded if isinstance(loaded, dict) else {}
    except json.JSONDecodeError as e:
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


def save_config(config: dict[str, Any], remove_keys: set[str] | None = None) -> None:
    """Persist config atomically, merging over the current file.

    Merge semantics: partial updates (e.g. the TUI persisting only
    ``last_query``/``last_days``) must never drop keys owned by another
    section — a full-file replace here silently wiped ``ai_provider`` and the
    OpenCLI consents on every interactive run (Session 19 regression).
    Secrets are stored in keyring/fernet, never in config.json, and only the
    secrets THIS caller passed are touched (a partial save never deletes
    another section's stored credential). ``remove_keys`` deletes persisted
    keys — used by ``ai.configure_provider`` when it clears a slot back to
    the provider preset / env default.
    """
    config = dict(config)
    secrets = {k: config.pop(k) for k in _SECRET_CONFIG_KEYS if k in config}
    other_secrets = {k: config.pop(k) for k in (_KEYRING_KEYS - _SECRET_CONFIG_KEYS) if k in config}
    merged = _load_config_raw()
    merged.update(config)
    for key in remove_keys or ():
        merged.pop(key, None)
    # Drop empty credential slots so a cleared provider never leaves stale
    # empty keys behind (falsy values would resolve fine, but clutter the file).
    for key in _KEYRING_KEYS | {"ai_provider"}:
        if not merged.get(key):
            merged.pop(key, None)
    try:
        ConfigSchema(**merged)  # validate the merged state; raises on corruption
        serializable = {k: v for k, v in merged.items() if k in ConfigSchema.model_fields}
        unknown_keys = {k: v for k, v in merged.items() if k not in ConfigSchema.model_fields}
        serializable.update(unknown_keys)
        payload = json.dumps(serializable, indent=2)
    except Exception as e:
        logger.warning("Failed to save config JSON: %s", e)
        payload = json.dumps(merged, indent=2)
    # Phase 7 (§17): atomic, owner-only (0600), symlink-rejected.
    try:
        atomic_write_text(CONFIG_FILE, payload)
    except ConfigSecurityError as e:
        logger.error("Refusing config write: %s", e)
    for key, value in secrets.items():
        if value:
            _write_secret(key, value)
        else:
            _delete_secret(key)
    for key, value in other_secrets.items():
        if value:
            _write_secret(key, value)


def load_profile() -> dict[str, Any] | None:
    """Read profile.json without creating anything and refusing symlinks."""
    try:
        raw = read_small_text_no_follow(PROFILE_FILE, max_bytes=_MAX_CONFIG_BYTES)
    except ConfigSecurityError as e:
        logger.error("Refusing profile read: %s", e)
        return None
    if raw is None:
        return None
    try:
        loaded = json.loads(raw)
        return loaded if isinstance(loaded, dict) else None
    except json.JSONDecodeError as e:
        logger.warning("Failed to load profile: %s", e)
    return None


def save_profile(profile: dict[str, Any]) -> None:
    # Phase 7 (§17): atomic, owner-only (0600), symlink-rejected.
    try:
        atomic_write_text(PROFILE_FILE, json.dumps(profile, indent=2))
    except ConfigSecurityError as e:
        logger.error("Refusing profile write: %s", e)
    except OSError as e:
        logger.error("Failed to save profile: %s", e)
