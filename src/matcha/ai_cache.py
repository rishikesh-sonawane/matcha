"""Disk cache for AI results (strategy §10.2, Phase 5).

SQLite-backed (stdlib ``sqlite3`` — same pattern as ``actions.py``), keyed by
``task + sha256(inputs)`` with a per-entry TTL. Caching is **opt-in**: it only
engages when ``settings.ai.cache_ttl > 0`` (default 0 = disabled), so the tool
never serves stale AI output or surprises tests by default.

Credential boundary: only AI *completions* (task + input hashes + raw text)
are stored — never API keys. The cache file path defaults to
``~/.matcha/ai_cache.sqlite`` and can be overridden with ``MATCHA_AI_CACHE``
(used by the test suite for hermeticity).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sqlite3
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_ENV_CACHE_FILE = "MATCHA_AI_CACHE"
DEFAULT_CACHE_FILE = Path.home() / ".matcha" / "ai_cache.sqlite"

# Expired rows are pruned lazily (probabilistically on put) to keep the file
# from growing without bound; anything older than this is always prunable.
_MAX_ROW_AGE_SECONDS = 7 * 24 * 3600
_PRUNE_EVERY_N_PUTS = 32

_SCHEMA = """
CREATE TABLE IF NOT EXISTS ai_cache (
    task    TEXT NOT NULL,
    key     TEXT NOT NULL,
    value   TEXT NOT NULL,
    created REAL NOT NULL,
    PRIMARY KEY (task, key)
)
"""

_put_counter = 0


def cache_path() -> Path:
    """Resolve the cache file (``MATCHA_AI_CACHE`` override wins)."""
    override = os.environ.get(_ENV_CACHE_FILE)
    if override:
        return Path(override)
    return DEFAULT_CACHE_FILE


def cache_key(task: str, *inputs: Any) -> str:
    """Stable sha256 key for a task name + hashable inputs.

    ``inputs`` may contain dicts/lists/strings — serialized with sorted keys
    so semantically identical inputs hash identically.
    """
    hasher = hashlib.sha256()
    hasher.update(task.encode("utf-8"))
    for item in inputs:
        hasher.update(b"\x00")
        hasher.update(
            json.dumps(item, sort_keys=True, default=str, ensure_ascii=False).encode("utf-8")
        )
    return hasher.hexdigest()


def _connect() -> sqlite3.Connection | None:
    try:
        path = cache_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(path), timeout=5)
        conn.execute(_SCHEMA)
        conn.commit()
        return conn
    except (OSError, sqlite3.Error) as e:
        logger.warning("AI cache unavailable: %s", e)
        return None


def get(task: str, key: str, ttl: int) -> str | None:
    """Return the cached completion for (task, key) if fresh, else None.

    Any storage error degrades to a cache miss (AI still works, just uncached).
    """
    if ttl <= 0:
        return None
    conn = _connect()
    if conn is None:
        return None
    try:
        row = conn.execute(
            "SELECT value, created FROM ai_cache WHERE task=? AND key=?",
            (task, key),
        ).fetchone()
    except sqlite3.Error as e:
        logger.warning("AI cache read failed: %s", e)
        return None
    finally:
        conn.close()
    if not row:
        return None
    value, created = row
    if time.time() - created > ttl:
        return None
    return value


def put(task: str, key: str, value: str) -> None:
    """Store a completion; lazily prunes expired rows every N puts."""
    global _put_counter
    conn = _connect()
    if conn is None:
        return
    try:
        conn.execute(
            "INSERT OR REPLACE INTO ai_cache (task, key, value, created) VALUES (?,?,?,?)",
            (task, key, value, time.time()),
        )
        _put_counter += 1
        if _put_counter % _PRUNE_EVERY_N_PUTS == 0:
            conn.execute(
                "DELETE FROM ai_cache WHERE created < ?",
                (time.time() - _MAX_ROW_AGE_SECONDS,),
            )
        conn.commit()
    except sqlite3.Error as e:
        logger.warning("AI cache write failed: %s", e)
    finally:
        conn.close()


def clear() -> None:
    """Drop all cached rows (used by tests and a hypothetical `matcha doctor`)."""
    conn = _connect()
    if conn is None:
        return
    try:
        conn.execute("DELETE FROM ai_cache")
        conn.commit()
    except sqlite3.Error as e:
        logger.warning("AI cache clear failed: %s", e)
    finally:
        conn.close()
