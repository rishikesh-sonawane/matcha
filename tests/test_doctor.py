import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from matcha.doctor import check_all, format_report, report_to_json

_REPORT_KEYS = {"status", "name", "message", "tier", "backends", "active_backend"}
_ALL_NAMES = {
    "linkedin",
    "indeed",
    "naukri",
    "remoteok",
    "web_search",
    "serpapi",
    "career_sites",
}


class TestDoctorCheckAll(unittest.TestCase):
    def setUp(self):
        patchers = [
            mock.patch("matcha.sources.linkedin.probe_url", return_value=("ok", "probed")),
            mock.patch("matcha.sources.indeed.probe_url", return_value=("ok", "probed")),
            mock.patch("matcha.sources.remoteok.probe_url", return_value=("ok", "probed")),
            mock.patch("matcha.sources.serpapi_jobs.check_serpapi_available", return_value=False),
        ]
        for p in patchers:
            p.start()
            self.addCleanup(p.stop)

    def test_result_shape(self):
        results = check_all()
        self.assertEqual(set(results.keys()), _ALL_NAMES)
        for name, r in results.items():
            self.assertEqual(set(r.keys()), _REPORT_KEYS, name)
            self.assertIn(r["status"], {"ok", "warn", "off", "error"}, name)
            self.assertTrue(r["message"], name)
            self.assertIsInstance(r["tier"], int)
            self.assertIsInstance(r["backends"], list)
            self.assertTrue(
                r["active_backend"] is None or isinstance(r["active_backend"], str), name
            )

    def test_survives_crashing_source(self):
        with mock.patch(
            "matcha.sources.linkedin.LinkedInSource.check", side_effect=RuntimeError("boom")
        ):
            results = check_all()
        self.assertEqual(results["linkedin"]["status"], "error")
        self.assertIsNone(results["linkedin"]["active_backend"])
        # every other source is still reported normally
        self.assertEqual(results["indeed"]["status"], "ok")

    def test_messages_scrubbed(self):
        with mock.patch(
            "matcha.sources.linkedin.LinkedInSource.check",
            return_value=("ok", "see https://user:pass@example.com for details"),
        ):
            results = check_all()
        self.assertNotIn("user:pass@", results["linkedin"]["message"])
        self.assertIn("***@", results["linkedin"]["message"])

    def test_career_sites_off_by_default(self):
        results = check_all()
        self.assertEqual(results["career_sites"]["status"], "off")


class TestDoctorReport(unittest.TestCase):
    def test_format_report(self):
        results = {
            "linkedin": {
                "status": "ok",
                "name": "LinkedIn",
                "message": "HTTP 200",
                "tier": 1,
                "backends": ["guest-api", "ddgs"],
                "active_backend": "guest-api",
            }
        }
        report = format_report(results)
        self.assertIn("Matcha Doctor", report)
        self.assertIn("LinkedIn", report)
        self.assertIn("guest-api", report)
        self.assertIn("1/1", report)

    def test_report_to_json(self):
        results = {
            "x": {
                "status": "ok",
                "name": "X",
                "message": "m",
                "tier": 0,
                "backends": ["b"],
                "active_backend": "b",
            }
        }
        payload = json.loads(report_to_json(results))
        self.assertEqual(payload["x"]["status"], "ok")


if __name__ == "__main__":
    unittest.main()
