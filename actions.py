import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

CONFIG_DIR = Path.home() / ".matcha"
DB_PATH = CONFIG_DIR / "jobs.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    url TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    company TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'saved',
    saved_at TEXT NOT NULL,
    applied_at TEXT,
    notes TEXT DEFAULT ''
)
"""

VALID_STATUSES: set[str] = {"saved", "applied", "dismissed", "interview", "rejected", "offer"}


def _ensure() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(DB_PATH)) as conn:
        conn.executescript(SCHEMA)


@contextmanager
def _db():
    _ensure()
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
    finally:
        conn.close()


def load_saved_jobs() -> dict[str, dict[str, str]]:
    with _db() as conn:
        rows = conn.execute(
            "SELECT url, title, company, source FROM jobs WHERE status != 'dismissed'"
        ).fetchall()
    return {r["url"]: dict(r) for r in rows}


def is_job_saved(job_url: str, saved_ids: Optional[dict[str, Any]] = None) -> bool:
    if saved_ids is not None:
        return job_url in saved_ids
    with _db() as conn:
        row = conn.execute(
            "SELECT 1 FROM jobs WHERE url = ? AND status != 'dismissed'",
            (job_url,),
        ).fetchone()
    return row is not None


def save_job(
    job: dict[str, Any],
    saved_ids: Optional[dict[str, Any]] = None,
) -> None:
    if saved_ids is not None:
        saved_ids[job.get("url", "")] = {
            "title": job.get("title", ""),
            "company": job.get("company", ""),
            "url": job.get("url", ""),
            "source": job.get("source", ""),
        }
        return
    with _db() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO jobs (url, title, company, source, status, saved_at)
               VALUES (?, ?, ?, ?, 'saved', ?)""",
            (
                job.get("url", ""),
                job.get("title", ""),
                job.get("company", ""),
                job.get("source", ""),
                datetime.utcnow().isoformat(),
            ),
        )


def unsave_job(
    job_url: str,
    saved_ids: Optional[dict[str, Any]] = None,
) -> None:
    if saved_ids is not None:
        saved_ids.pop(job_url, None)
        return
    with _db() as conn:
        conn.execute("UPDATE jobs SET status = 'dismissed' WHERE url = ?", (job_url,))


def set_job_status(url: str, status: str) -> None:
    if status not in VALID_STATUSES:
        return
    with _db() as conn:
        now = datetime.utcnow().isoformat()
        if status == "applied":
            conn.execute(
                "UPDATE jobs SET status = ?, applied_at = ? WHERE url = ?",
                (status, now, url),
            )
        else:
            conn.execute("UPDATE jobs SET status = ? WHERE url = ?", (status, url))


def get_job_status(url: str) -> Optional[dict[str, Any]]:
    with _db() as conn:
        row = conn.execute(
            "SELECT status, saved_at, applied_at, notes FROM jobs WHERE url = ?",
            (url,),
        ).fetchone()
    return dict(row) if row else None
