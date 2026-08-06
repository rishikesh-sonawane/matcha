"""Hermetic tests for the circuit breakers (strategy §6.7, Phase 7).

The state file is redirected to a temp path; time is patched so cooldown
semantics are deterministic. No real files outside the temp dir.
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


class TestBreaker(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.state_file = Path(self._tmp.name) / "source_state.json"
        patcher = mock.patch("matcha.sources.breaker.STATE_FILE", self.state_file)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _state(self):
        if not self.state_file.exists():
            return {}
        return json.loads(self.state_file.read_text(encoding="utf-8"))

    def test_empty_state_is_not_open(self):
        from matcha.sources.breaker import is_open

        self.assertFalse(is_open("linkedin"))

    def test_success_resets_and_records(self):
        from matcha.sources.breaker import circuit_status, record_failure, record_success

        record_failure("linkedin")
        record_failure("linkedin")
        record_success("linkedin")
        entry = circuit_status("linkedin")
        self.assertEqual(entry["ok_streak"], 1)
        self.assertEqual(entry["fail_streak"], 0)
        self.assertFalse(entry["open"])

    def test_three_failures_open_circuit(self):
        from matcha.sources.breaker import circuit_status, is_open, record_failure

        record_failure("linkedin")
        self.assertFalse(is_open("linkedin"))
        record_failure("linkedin")
        self.assertFalse(is_open("linkedin"))
        record_failure("linkedin")
        self.assertTrue(is_open("linkedin"))
        self.assertTrue(circuit_status("linkedin")["open"])
        self.assertEqual(circuit_status("linkedin")["fail_streak"], 3)

    def test_cooldown_expiry_closes_circuit(self):
        from matcha.sources.breaker import COOLDOWN_SECONDS, is_open, record_failure, record_success

        with mock.patch("matcha.sources.breaker.time.time") as t:
            t.return_value = 1_000_000.0
            record_failure("indeed")
            record_failure("indeed")
            record_failure("indeed")
            self.assertTrue(is_open("indeed"))
            # after the cooldown window elapses the circuit closes by itself
            t.return_value = 1_000_000.0 + COOLDOWN_SECONDS + 1
            self.assertFalse(is_open("indeed"))
        # and a success clears the cooldown immediately
        record_success("indeed")
        self.assertFalse(is_open("indeed"))

    def test_state_persists_across_module_calls(self):
        from matcha.sources.breaker import circuit_status, record_success

        record_success("naukri")
        # a fresh read (new process view) sees the persisted entry
        entry = circuit_status("naukri")
        self.assertEqual(entry["ok_streak"], 1)

    def test_corrupt_state_file_degrades(self):
        from matcha.sources.breaker import is_open, record_failure

        self.state_file.write_text("{not json", encoding="utf-8")
        self.assertFalse(is_open("remoteok"))
        # record still works after a corrupt read (self-healing write)
        record_failure("remoteok")
        self.assertIn("remoteok", self._state())

    def test_all_status_returns_state(self):
        from matcha.sources.breaker import all_status, record_success

        record_success("web_search")
        status = all_status()
        self.assertIn("web_search", status)
        self.assertIn("open", status["web_search"])

    def test_concurrent_records_no_lost_updates(self):
        from concurrent.futures import ThreadPoolExecutor

        from matcha.sources.breaker import circuit_status, record_success

        with ThreadPoolExecutor(max_workers=8) as ex:
            list(ex.map(lambda _: record_success("concurrent"), range(20)))
        entry = circuit_status("concurrent")
        # all 20 successes must be counted, not clobbered by a race
        self.assertEqual(entry["ok_streak"], 20)


if __name__ == "__main__":
    unittest.main()
