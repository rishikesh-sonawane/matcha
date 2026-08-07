import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from matcha.doctor import check_all, format_report, report_to_json

_REPORT_KEYS = {"status", "name", "message", "tier", "backends", "active_backend", "circuit"}
_AI_KEYS = {
    "status",
    "name",
    "message",
    "provider",
    "provider_label",
    "known_provider",
    "requires_key",
    "key_set",
    "url",
    "model_best",
    "model_fast",
    "available",
}
_ALL_NAMES = {
    "linkedin",
    "indeed",
    "naukri",
    "remoteok",
    "web_search",
    "serpapi",
    "career_sites",
    "rss",
    "ai",
}

_AI_OK = {
    "provider": "kilo",
    "provider_label": "Kilo Gateway (default)",
    "known_provider": True,
    "requires_key": True,
    "key_set": True,
    "url": "https://api.kilo.ai/api/gateway",
    "model_best": "kilo-auto/small",
    "model_fast": "kilo-auto/small",
    "available": True,
}

_AI_UNCONFIGURED = {
    "provider": "",
    "provider_label": "Not configured",
    "known_provider": False,
    "requires_key": True,
    "key_set": False,
    "url": "",
    "model_best": "",
    "model_fast": "",
    "available": False,
}


def _patch_ai(snapshot: dict):
    return mock.patch("matcha.doctor.ai_status", return_value=dict(snapshot))


class TestDoctorCheckAll(unittest.TestCase):
    def setUp(self):
        patchers = [
            mock.patch("matcha.sources.linkedin.probe_url", return_value=("ok", "probed")),
            mock.patch("matcha.sources.indeed.probe_url", return_value=("ok", "probed")),
            mock.patch("matcha.sources.remoteok.probe_url", return_value=("ok", "probed")),
            mock.patch("matcha.sources.serpapi_jobs.check_serpapi_available", return_value=False),
            _patch_ai(_AI_OK),
        ]
        for p in patchers:
            p.start()
            self.addCleanup(p.stop)

    def test_result_shape(self):
        results = check_all()
        self.assertEqual(set(results.keys()), _ALL_NAMES)
        for name, r in results.items():
            if name == "ai":
                self.assertEqual(set(r.keys()), _AI_KEYS, name)
                self.assertIn(r["status"], {"ok", "warn", "off", "error"}, name)
                self.assertIsInstance(r["key_set"], bool, name)
                self.assertIsInstance(r["available"], bool, name)
                continue
            self.assertEqual(set(r.keys()), _REPORT_KEYS, name)
            self.assertIn(r["status"], {"ok", "warn", "off", "error"}, name)
            self.assertTrue(r["message"], name)
            self.assertIsInstance(r["tier"], int)
            self.assertIsInstance(r["backends"], list)
            self.assertTrue(
                r["active_backend"] is None or isinstance(r["active_backend"], str), name
            )

    def test_ai_reports_resolved_config(self):
        ai = check_all()["ai"]
        self.assertEqual(ai["status"], "ok")
        self.assertEqual(ai["provider"], "kilo")
        self.assertEqual(ai["model_best"], "kilo-auto/small")
        self.assertEqual(ai["model_fast"], "kilo-auto/small")
        self.assertTrue(ai["key_set"])
        self.assertTrue(ai["available"])
        self.assertIn("AI available", ai["message"])
        self.assertNotIn("sk-", ai["message"])  # the key itself never leaks

    def test_ai_off_when_not_configured(self):
        with _patch_ai(_AI_UNCONFIGURED):
            ai = check_all()["ai"]
        self.assertEqual(ai["status"], "off")
        self.assertIn("heuristic-only", ai["message"])
        self.assertFalse(ai["available"])
        self.assertFalse(ai["key_set"])

    def test_ai_warn_when_key_without_provider(self):
        partial = dict(_AI_UNCONFIGURED, key_set=True)  # key present, nothing wired
        with _patch_ai(partial):
            ai = check_all()["ai"]
        self.assertEqual(ai["status"], "warn")
        self.assertIn("missing", ai["message"])
        self.assertIn("provider", ai["message"])

    def test_ai_warn_on_unknown_provider(self):
        unknown = dict(_AI_UNCONFIGURED, provider="wat", key_set=True)
        with _patch_ai(unknown):
            ai = check_all()["ai"]
        self.assertEqual(ai["status"], "warn")
        self.assertIn("Unknown AI provider", ai["message"])
        self.assertIn("kilo", ai["message"])  # valid providers are listed

    def test_ai_url_scrubbed(self):
        cred_url = dict(_AI_OK, url="https://user:secret@api.openai.com/v1")
        with _patch_ai(cred_url):
            ai = check_all()["ai"]
        self.assertNotIn("user:secret@", ai["url"])
        self.assertNotIn("secret", ai["message"])

    def test_survives_crashing_source(self):
        with mock.patch(
            "matcha.sources.linkedin.LinkedInSource.check", side_effect=RuntimeError("boom")
        ):
            results = check_all()
        self.assertEqual(results["linkedin"]["status"], "error")
        self.assertIsNone(results["linkedin"]["active_backend"])
        # every other source is still reported normally
        self.assertEqual(results["indeed"]["status"], "ok")
        self.assertEqual(results["ai"]["status"], "ok")

    def test_ai_check_failure_degrades_to_error(self):
        with mock.patch("matcha.doctor.ai_status", side_effect=RuntimeError("boom")):
            results = check_all()
        self.assertEqual(results["ai"]["status"], "error")
        self.assertIn("failed", results["ai"]["message"])
        self.assertFalse(results["ai"]["available"])
        # the rest of the report is unaffected
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

    def test_format_report_includes_ai_section(self):
        results = {
            "linkedin": {
                "status": "ok",
                "name": "LinkedIn",
                "message": "HTTP 200",
                "tier": 1,
                "backends": ["guest-api", "ddgs"],
                "active_backend": "guest-api",
            },
            "ai": {
                "status": "ok",
                "name": "AI matching — Kilo Gateway (default)",
                "message": "AI available — provider Kilo Gateway (default) · key set",
                "provider": "kilo",
                "provider_label": "Kilo Gateway (default)",
                "known_provider": True,
                "requires_key": True,
                "key_set": True,
                "url": "https://api.kilo.ai/api/gateway",
                "model_best": "kilo-auto/small",
                "model_fast": "kilo-auto/small",
                "available": True,
            },
        }
        report = format_report(results)
        self.assertIn("AI matching", report)
        self.assertIn("AI available", report)
        self.assertIn("1/1", report)  # AI is not counted in the source total

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

    def test_report_to_json_includes_ai(self):
        results = {
            "x": {
                "status": "ok",
                "name": "X",
                "message": "m",
                "tier": 0,
                "backends": ["b"],
                "active_backend": "b",
            },
            "ai": dict(
                {
                    "status": "off",
                    "name": "AI matching — Not configured",
                    "message": "AI off — heuristic-only. Set $MINIMAX or run `matcha --configure`",
                },
                **_AI_UNCONFIGURED,
            ),
        }
        payload = json.loads(report_to_json(results))
        self.assertEqual(payload["ai"]["provider"], "")
        self.assertFalse(payload["ai"]["key_set"])
        self.assertFalse(payload["ai"]["available"])
        self.assertEqual(payload["ai"]["status"], "off")


if __name__ == "__main__":
    unittest.main()
