"""Hermetic tests for the saved-jobs SQLite lifecycle (actions.py, Phase 7).

Phase 3-adjacent polish (2026-08-06): saved jobs now persist the
enriched/normalized fields (salary, salary_int, apply_url, workplace_type,
company_url, listed_epoch) via an idempotent ALTER TABLE migration, and
re-saving UPSERTs so status/applied_at/notes are never reset.
"""

import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import matcha.actions as actions


class TestActions(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db = Path(self._tmp.name) / "jobs.db"
        for name in ("CONFIG_DIR", "DB_PATH"):
            patcher = mock.patch.object(
                actions, name, Path(self._tmp.name) if name == "CONFIG_DIR" else self.db
            )
            patcher.start()
            self.addCleanup(patcher.stop)

    def _job(self, url="https://x/1", title="T", company="C"):
        return {"url": url, "title": title, "company": company, "source": "X"}

    def test_save_load_unsave(self):
        actions.save_job(self._job())
        saved = actions.load_saved_jobs()
        self.assertIn("https://x/1", saved)
        self.assertEqual(saved["https://x/1"]["title"], "T")
        self.assertTrue(actions.is_job_saved("https://x/1"))
        actions.unsave_job("https://x/1")
        self.assertFalse(actions.is_job_saved("https://x/1"))

    def test_dismissed_excluded_from_loads(self):
        actions.save_job(self._job("https://x/2"))
        actions.set_job_status("https://x/2", "dismissed")
        self.assertNotIn("https://x/2", actions.load_saved_jobs())

    def test_status_lifecycle(self):
        actions.save_job(self._job("https://x/3"))
        actions.set_job_status("https://x/3", "applied")
        row = actions.get_job_status("https://x/3")
        self.assertEqual(row["status"], "applied")
        self.assertIsNotNone(row["applied_at"])
        actions.set_job_status("https://x/3", "interview")
        self.assertEqual(actions.get_job_status("https://x/3")["status"], "interview")
        # invalid status is ignored
        actions.set_job_status("https://x/3", "bogus")
        self.assertEqual(actions.get_job_status("https://x/3")["status"], "interview")
        self.assertIsNone(actions.get_job_status("https://missing"))

    def test_in_memory_saved_ids_paths(self):
        ids: dict = {}
        actions.save_job(self._job("https://x/4"), saved_ids=ids)
        self.assertIn("https://x/4", ids)
        self.assertTrue(actions.is_job_saved("https://x/4", ids))
        actions.unsave_job("https://x/4", saved_ids=ids)
        self.assertFalse(actions.is_job_saved("https://x/4", ids))

    def test_replace_existing_job(self):
        actions.save_job(self._job())
        actions.save_job(self._job(title="T2"))
        self.assertEqual(actions.load_saved_jobs()["https://x/1"]["title"], "T2")

    def _enriched_job(self, url="https://x/10"):
        return {
            "url": url,
            "title": "Platform Engineer",
            "company": "Acme",
            "source": "LinkedIn",
            "salary": "₹28-35 LPA",
            "salary_int": 35,
            "apply_url": "https://x/apply",
            "workplace_type": "Remote",
            "company_url": "https://acme.example",
            "listed_epoch": 1780000000,
        }

    def test_enriched_fields_persisted(self):
        actions.save_job(self._enriched_job())
        row = actions.load_saved_jobs()["https://x/10"]
        self.assertEqual(row["salary"], "₹28-35 LPA")
        self.assertEqual(row["salary_int"], 35)
        self.assertEqual(row["apply_url"], "https://x/apply")
        self.assertEqual(row["workplace_type"], "Remote")
        self.assertEqual(row["company_url"], "https://acme.example")
        self.assertEqual(row["listed_epoch"], 1780000000)

    def test_legacy_db_migrated_idempotently(self):
        # Build a pre-polish schema (no enriched columns) + one existing row,
        # then let the normal save path run the ALTER TABLE migration.
        conn = sqlite3.connect(str(self.db))
        conn.executescript(
            """CREATE TABLE jobs (
                url TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                company TEXT NOT NULL DEFAULT '',
                source TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'saved',
                saved_at TEXT NOT NULL,
                applied_at TEXT,
                notes TEXT DEFAULT ''
            );"""
        )
        conn.execute(
            "INSERT INTO jobs (url, title, status, saved_at) "
            "VALUES ('legacy-1', 'Old', 'saved', '2026-01-01')"
        )
        conn.commit()
        conn.close()

        actions.save_job(self._enriched_job("https://new/1"))

        conn = sqlite3.connect(str(self.db))
        cols = {r[1] for r in conn.execute("PRAGMA table_info(jobs)").fetchall()}
        conn.close()
        for col, _decl in actions.ENRICHED_COLUMNS:
            self.assertIn(col, cols)
        saved = actions.load_saved_jobs()
        self.assertIn("legacy-1", saved)  # old row preserved
        self.assertEqual(saved["legacy-1"]["salary"], "")
        self.assertEqual(saved["https://new/1"]["salary_int"], 35)
        # Second migration run must be a no-op (idempotent).
        actions.save_job(self._enriched_job("https://new/2"))

    def test_resave_preserves_status_and_notes(self):
        actions.save_job(self._job("https://x/5"))
        actions.set_job_status("https://x/5", "applied")
        actions.save_job(self._job("https://x/5", title="T-new"))
        row = actions.get_job_status("https://x/5")
        self.assertEqual(row["status"], "applied")  # not reset to 'saved'
        self.assertIsNotNone(row["applied_at"])
        self.assertEqual(actions.load_saved_jobs()["https://x/5"]["title"], "T-new")

    def test_in_memory_saved_ids_include_enriched(self):
        ids: dict = {}
        actions.save_job(self._enriched_job("https://x/11"), saved_ids=ids)
        entry = ids["https://x/11"]
        self.assertEqual(entry["salary"], "₹28-35 LPA")
        self.assertEqual(entry["salary_int"], 35)
        self.assertEqual(entry["apply_url"], "https://x/apply")

    def test_job_entry_shape(self):
        entry = actions.job_entry(self._enriched_job("https://x/12"))
        self.assertEqual(entry["url"], "https://x/12")
        self.assertEqual(entry["listed_epoch"], 1780000000)
        self.assertIsNone(actions.job_entry({})["salary_int"])


if __name__ == "__main__":
    unittest.main()
