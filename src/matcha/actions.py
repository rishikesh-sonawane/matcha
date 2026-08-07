import sqlite3
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now_iso() -> str:
    """Timezone-aware UTC timestamp for saved-job columns (py3.14-safe)."""
    return datetime.now(timezone.utc).isoformat()


CONFIG_DIR = Path.home() / ".matcha"
DB_PATH = CONFIG_DIR / "jobs.db"

#: Enriched/normalized columns added for saved jobs (strategy §8/§14). Fresh
#: databases get them via SCHEMA; existing ones via the idempotent
#: ``_migrate`` ALTER TABLE pass below.
ENRICHED_COLUMNS: list[tuple[str, str]] = [
    ("apply_url", "TEXT NOT NULL DEFAULT ''"),
    ("salary", "TEXT NOT NULL DEFAULT ''"),
    ("salary_int", "INTEGER"),
    ("workplace_type", "TEXT NOT NULL DEFAULT ''"),
    ("company_url", "TEXT NOT NULL DEFAULT ''"),
    ("listed_epoch", "INTEGER"),
]

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    url TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    company TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'saved',
    saved_at TEXT NOT NULL,
    applied_at TEXT,
    notes TEXT DEFAULT '',
    apply_url TEXT NOT NULL DEFAULT '',
    salary TEXT NOT NULL DEFAULT '',
    salary_int INTEGER,
    workplace_type TEXT NOT NULL DEFAULT '',
    company_url TEXT NOT NULL DEFAULT '',
    listed_epoch INTEGER
)
"""

VALID_STATUSES: set[str] = {"saved", "applied", "dismissed", "interview", "rejected", "offer"}


def _migrate(conn: sqlite3.Connection) -> None:
    """Idempotently add the enriched/normalized columns to older databases.

    ``CREATE TABLE IF NOT EXISTS`` never touches an existing table, so legacy
    ``jobs`` tables lack the enriched columns until this pass adds them.
    """
    existing = {row[1] for row in conn.execute("PRAGMA table_info(jobs)").fetchall()}
    for col, decl in ENRICHED_COLUMNS:
        if col not in existing:
            conn.execute(f"ALTER TABLE jobs ADD COLUMN {col} {decl}")


def _ensure() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    # closing(): the sqlite3 connection context manager only commits/rolls
    # back — it never closes, leaking a handle per call.
    with closing(sqlite3.connect(str(DB_PATH))) as conn:
        conn.executescript(SCHEMA)
        _migrate(conn)


@contextmanager
def _db():
    _ensure()
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def load_saved_jobs() -> dict[str, dict[str, Any]]:
    with _db() as conn:
        rows = conn.execute(
            "SELECT url, title, company, source, salary, salary_int, apply_url, "
            "workplace_type, company_url, listed_epoch FROM jobs "
            "WHERE status != 'dismissed'"
        ).fetchall()
    return {r["url"]: dict(r) for r in rows}


def is_job_saved(job_url: str, saved_ids: dict[str, Any] | None = None) -> bool:
    if saved_ids is not None:
        return job_url in saved_ids
    with _db() as conn:
        row = conn.execute(
            "SELECT 1 FROM jobs WHERE url = ? AND status != 'dismissed'",
            (job_url,),
        ).fetchone()
    return row is not None


def job_entry(job: dict[str, Any]) -> dict[str, Any]:
    """The saved-job row shape (base + enriched/normalized fields).

    Shared by the SQLite write and the in-memory ``saved_ids`` mirror so the
    TUI's live Saved view and the persisted DB never diverge.
    """
    return {
        "title": job.get("title", ""),
        "company": job.get("company", ""),
        "url": job.get("url", ""),
        "source": job.get("source", ""),
        "salary": job.get("salary", ""),
        "salary_int": job.get("salary_int"),
        "apply_url": job.get("apply_url", ""),
        "workplace_type": job.get("workplace_type", ""),
        "company_url": job.get("company_url", ""),
        "listed_epoch": job.get("listed_epoch"),
    }


def save_job(
    job: dict[str, Any],
    saved_ids: dict[str, Any] | None = None,
) -> None:
    if saved_ids is not None:
        saved_ids[job.get("url", "")] = job_entry(job)
        return
    entry = job_entry(job)
    with _db() as conn:
        # UPSERT (not INSERT OR REPLACE): re-saving a job refreshes its
        # metadata but keeps status/applied_at/notes — applying to a job must
        # never be silently reset by a later search + save.
        conn.execute(
            """INSERT INTO jobs (url, title, company, source, status, saved_at,
                                apply_url, salary, salary_int, workplace_type,
                                company_url, listed_epoch)
               VALUES (?, ?, ?, ?, 'saved', ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(url) DO UPDATE SET
                 title = excluded.title,
                 company = excluded.company,
                 source = excluded.source,
                 apply_url = excluded.apply_url,
                 salary = excluded.salary,
                 salary_int = excluded.salary_int,
                 workplace_type = excluded.workplace_type,
                 company_url = excluded.company_url,
                 listed_epoch = excluded.listed_epoch""",
            (
                entry["url"],
                entry["title"],
                entry["company"],
                entry["source"],
                _now_iso(),
                entry["apply_url"],
                entry["salary"],
                entry["salary_int"],
                entry["workplace_type"],
                entry["company_url"],
                entry["listed_epoch"],
            ),
        )


def unsave_job(
    job_url: str,
    saved_ids: dict[str, Any] | None = None,
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
        now = _now_iso()
        if status == "applied":
            conn.execute(
                "UPDATE jobs SET status = ?, applied_at = ? WHERE url = ?",
                (status, now, url),
            )
        else:
            conn.execute("UPDATE jobs SET status = ? WHERE url = ?", (status, url))


def get_job_status(url: str) -> dict[str, Any] | None:
    with _db() as conn:
        row = conn.execute(
            "SELECT status, saved_at, applied_at, notes FROM jobs WHERE url = ?",
            (url,),
        ).fetchone()
    return dict(row) if row else None
