"""New-vs-seen tracking for ``matcha watch`` (strategy §13, Phase 6).

Stores seen job URLs in a ``seen_urls`` table inside the shared
``~/.matcha/jobs.db`` (same DB as ``actions.py``) so ``watch`` surfaces only
jobs not already seen. Design:

- ``mark_seen(jobs)`` upserts URLs (first_seen / last_seen / seen_count).
- ``partition_new(jobs)`` splits a batch into ``(new, seen)`` by URL
  membership — new = URL absent from the seen table.
- URLs without a ``url`` key can't be tracked and are always treated as new
  (and never marked).

Only ``watch`` consumes this table: interactive TUI runs don't pollute the
newness signal.
"""

import sqlite3
import time
from contextlib import closing
from typing import Any

from matcha.actions import CONFIG_DIR, DB_PATH

_SEEN_SCHEMA = """
CREATE TABLE IF NOT EXISTS seen_urls (
    url        TEXT PRIMARY KEY,
    title      TEXT NOT NULL DEFAULT '',
    company    TEXT NOT NULL DEFAULT '',
    source     TEXT NOT NULL DEFAULT '',
    first_seen REAL NOT NULL,
    last_seen  REAL NOT NULL,
    seen_count INTEGER NOT NULL DEFAULT 1
)
"""


def _ensure_seen() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    # closing(): the sqlite3 connection context manager commits/rolls back
    # but never closes — close explicitly to avoid leaking a handle.
    with closing(sqlite3.connect(str(DB_PATH))) as conn:
        conn.execute(_SEEN_SCHEMA)


def _known_urls() -> set[str]:
    _ensure_seen()
    with closing(sqlite3.connect(str(DB_PATH))) as conn:
        rows = conn.execute("SELECT url FROM seen_urls").fetchall()
    return {r[0] for r in rows}


def partition_new(jobs: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split ``jobs`` into ``(new, seen)`` by seen_urls membership.

    Jobs without a URL count as new (nothing to compare against).
    """
    known = _known_urls()
    new: list[dict[str, Any]] = []
    seen: list[dict[str, Any]] = []
    for job in jobs:
        url = (job.get("url") or "").strip()
        if url and url in known:
            seen.append(job)
        else:
            new.append(job)
    return new, seen


def mark_seen(jobs: list[dict[str, Any]]) -> int:
    """Upsert every job URL into seen_urls.

    Returns the number of URLs newly inserted (0 for repeat sightings).
    Empty URLs are skipped. ``seen_count`` bumps on re-sightings so watch
    can tell "new this run" from "seen N times before".
    """
    _ensure_seen()
    now = time.time()
    inserted = 0
    with closing(sqlite3.connect(str(DB_PATH))) as conn:
        try:
            for job in jobs:
                url = (job.get("url") or "").strip()
                if not url:
                    continue
                title = str(job.get("title", ""))[:500]
                company = str(job.get("company", ""))[:200]
                source = str(job.get("source", ""))[:100]
                row = conn.execute("SELECT 1 FROM seen_urls WHERE url = ?", (url,)).fetchone()
                if row is None:
                    conn.execute(
                        "INSERT INTO seen_urls "
                        "(url, title, company, source, first_seen, last_seen, seen_count) "
                        "VALUES (?, ?, ?, ?, ?, ?, 1)",
                        (url, title, company, source, now, now),
                    )
                    inserted += 1
                else:
                    conn.execute(
                        "UPDATE seen_urls SET last_seen = ?, seen_count = seen_count + 1 "
                        "WHERE url = ?",
                        (now, url),
                    )
            # closing() alone never commits (the sqlite3 context manager did) —
            # without this the writes above would roll back on close.
            conn.commit()
        except Exception:  # noqa: BLE001 — roll back and let the caller decide
            conn.rollback()
            raise
    return inserted


def stats() -> dict[str, int]:
    """``{"seen_urls_total": N}`` — total distinct URLs ever tracked."""
    _ensure_seen()
    with closing(sqlite3.connect(str(DB_PATH))) as conn:
        row = conn.execute("SELECT COUNT(*) FROM seen_urls").fetchone()
    return {"seen_urls_total": int(row[0])}
