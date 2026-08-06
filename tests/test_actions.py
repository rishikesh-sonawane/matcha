"""Hermetic tests for the saved-jobs SQLite lifecycle (actions.py, Phase 7)."""

import os
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


if __name__ == "__main__":
    unittest.main()
