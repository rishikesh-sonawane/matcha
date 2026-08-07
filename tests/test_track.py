"""Hermetic tests for the new-vs-seen tracker (strategy §13, Phase 6)."""

import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


class TestTrack(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self._db = Path(self._tmp.name) / "jobs.db"
        patcher_db = mock.patch("matcha.track.DB_PATH", self._db)
        patcher_dir = mock.patch("matcha.track.CONFIG_DIR", Path(self._tmp.name))
        patcher_db.start()
        patcher_dir.start()
        self.addCleanup(patcher_db.stop)
        self.addCleanup(patcher_dir.stop)

    def test_partition_all_new_on_empty_table(self):
        from matcha.track import partition_new

        jobs = [{"url": "u1", "title": "A"}, {"url": "u2", "title": "B"}]
        new, seen = partition_new(jobs)
        self.assertEqual([j["url"] for j in new], ["u1", "u2"])
        self.assertEqual(seen, [])

    def test_mark_seen_then_partition(self):
        from matcha.track import mark_seen, partition_new, stats

        jobs1 = [
            {"url": "u1", "title": "A"},
            {"url": "u2", "title": "B", "company": "Co", "source": "Indeed"},
        ]
        self.assertEqual(mark_seen(jobs1), 2)
        self.assertEqual(stats()["seen_urls_total"], 2)

        jobs2 = [{"url": "u2", "title": "B"}, {"url": "u3", "title": "C"}]
        new, seen = partition_new(jobs2)
        self.assertEqual([j["url"] for j in new], ["u3"])
        self.assertEqual([j["url"] for j in seen], ["u2"])
        self.assertEqual(mark_seen(jobs2), 1)  # only u3 newly inserted
        self.assertEqual(stats()["seen_urls_total"], 3)

    def test_no_url_jobs_always_new_and_never_marked(self):
        from matcha.track import mark_seen, partition_new

        jobs = [{"title": "no-url"}, {"url": "", "title": "empty"}]
        new, _seen = partition_new(jobs)
        self.assertEqual(len(new), 2)
        self.assertEqual(mark_seen(jobs), 0)
        new2, _seen2 = partition_new(jobs)
        self.assertEqual(len(new2), 2)  # still new — never recorded

    def test_repeat_sighting_bumps_seen_count(self):
        from contextlib import closing

        from matcha.track import DB_PATH, mark_seen

        mark_seen([{"url": "u1", "title": "A"}])
        mark_seen([{"url": "u1", "title": "A"}])
        # closing(): the sqlite3 connection context manager never closes.
        with closing(sqlite3.connect(str(DB_PATH))) as conn:
            row = conn.execute("SELECT seen_count FROM seen_urls WHERE url = 'u1'").fetchone()
        self.assertEqual(row[0], 2)

    def test_stats_empty(self):
        from matcha.track import stats

        self.assertEqual(stats(), {"seen_urls_total": 0})


if __name__ == "__main__":
    unittest.main()
