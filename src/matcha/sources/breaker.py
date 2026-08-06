"""Circuit breakers (strategy §6.7) — per-source failure state.

Per-source state is persisted to ``~/.matcha/source_state.json``:

.. code-block:: json

    {"linkedin": {"ok_streak": 12, "fail_streak": 0, "last_ok": 1690000000,
                  "cooldown_until": 0}}

- A source that fails ≥ :data:`FAIL_THRESHOLD` consecutive searches enters a
  cooldown window (:data:`COOLDOWN_SECONDS`) during which ``search_jobs``
  skips it with a visible note (``is_open``).
- Any success resets both streaks and clears the cooldown.
- The doctor reports circuit state (``circuit_status``).

The state file is a private artifact — writes are atomic/0600 and reads are
symlink-rejected via ``matcha.utils`` (Phase 7, strategy §17). Every IO
failure degrades to an empty/untouched state so a breaker problem can never
take a run down (failproof by construction).
"""

import json
import logging
import threading
import time
from typing import Any

from matcha.config import CONFIG_DIR
from matcha.utils import atomic_write_text, read_small_text_no_follow

logger = logging.getLogger(__name__)

STATE_FILE = CONFIG_DIR / "source_state.json"
FAIL_THRESHOLD = 3
COOLDOWN_SECONDS = 30 * 60  # 30 minutes
_MAX_STATE_BYTES = 1024 * 1024

_DEFAULT_ENTRY = {"ok_streak": 0, "fail_streak": 0, "last_ok": 0.0, "cooldown_until": 0.0}

# search_jobs records from up to 12 worker threads; the read-modify-write
# cycle must be serialized or concurrent records lose updates. Atomic
# os.replace writes already prevent torn files for cross-process readers.
_lock = threading.Lock()


def _load_state() -> dict[str, dict[str, Any]]:
    """Load the persisted state dict; any failure degrades to {}."""
    try:
        raw = read_small_text_no_follow(STATE_FILE, max_bytes=_MAX_STATE_BYTES)
    except Exception as e:  # noqa: BLE001 - breaker IO must never crash a run
        logger.warning("Failed to read circuit state: %s", e)
        return {}
    if raw is None:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.warning("Failed to parse circuit state: %s", e)
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): (dict(v) if isinstance(v, dict) else {}) for k, v in data.items()}


def _save_state(state: dict[str, dict[str, Any]]) -> None:
    try:
        atomic_write_text(STATE_FILE, json.dumps(state, indent=2))
    except Exception as e:  # noqa: BLE001 - breaker IO must never crash a run
        logger.warning("Failed to save circuit state: %s", e)


def _entry(name: str) -> dict[str, Any]:
    state = _load_state()
    return dict(_DEFAULT_ENTRY, **state.get(name, {}))


def _store(name: str, entry: dict[str, Any]) -> None:
    state = _load_state()
    state[name] = entry
    _save_state(state)


def record_success(name: str) -> None:
    """A search for ``name`` completed without errors — reset the failure side."""
    with _lock:
        entry = _entry(name)
        entry["ok_streak"] = int(entry.get("ok_streak", 0)) + 1
        entry["fail_streak"] = 0
        entry["last_ok"] = time.time()
        entry["cooldown_until"] = 0.0
        _store(name, entry)


def record_failure(name: str) -> None:
    """A search for ``name`` errored/crashed — count toward the trip threshold."""
    with _lock:
        entry = _entry(name)
        entry["fail_streak"] = int(entry.get("fail_streak", 0)) + 1
        entry["ok_streak"] = 0
        if entry["fail_streak"] >= FAIL_THRESHOLD:
            entry["cooldown_until"] = time.time() + COOLDOWN_SECONDS
            logger.warning(
                "Circuit opened for %s (%d consecutive failures) — skipping until cooldown ends",
                name,
                entry["fail_streak"],
            )
        _store(name, entry)


def is_open(name: str) -> bool:
    """True while ``name`` sits inside its cooldown window (skip it)."""
    entry = _entry(name)
    return float(entry.get("cooldown_until", 0.0)) > time.time()


def circuit_status(name: str) -> dict[str, Any]:
    """Full per-source circuit state with a fresh ``open`` flag (for doctor)."""
    entry = dict(_entry(name))
    entry["open"] = is_open(name)
    return entry


def all_status() -> dict[str, dict[str, Any]]:
    """Circuit state for every known source key."""
    state = _load_state()
    out: dict[str, dict[str, Any]] = {}
    for name in state:
        out[name] = circuit_status(name)
    return out
