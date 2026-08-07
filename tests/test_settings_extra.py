"""Hermetic tests for settings.py — defaults, deep-merge, validation (Phase 7)."""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import matcha.settings as settings_mod


class TestLoadSettings(unittest.TestCase):
    def test_defaults(self):
        with mock.patch("pathlib.Path.exists", return_value=False):
            s = settings_mod.load_settings()
        self.assertEqual(s["search"]["days"], 7)
        self.assertEqual(s["sources"]["rss"]["feeds"], [])
        self.assertEqual(s["enrichment"]["top_n"], 30)

    def test_local_yaml_merges(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = Path(d) / "matcha.yaml"
            cfg.write_text("search:\n  days: 3\nfilters:\n  min_salary: 10\n", encoding="utf-8")
            with (
                mock.patch.object(settings_mod, "LOCAL_CONFIG", cfg),
                mock.patch.object(settings_mod, "USER_CONFIG", Path(d) / "none.yaml"),
            ):
                s = settings_mod.load_settings()
        self.assertEqual(s["search"]["days"], 3)
        self.assertEqual(s["filters"]["min_salary"], 10)
        self.assertEqual(s["enrichment"]["top_n"], 30)  # untouched default

    def test_malformed_yaml_logs_and_defaults(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = Path(d) / "matcha.yaml"
            cfg.write_text("{not: [valid", encoding="utf-8")
            with (
                mock.patch.object(settings_mod, "LOCAL_CONFIG", cfg),
                mock.patch.object(settings_mod, "USER_CONFIG", Path(d) / "none.yaml"),
            ):
                s = settings_mod.load_settings()
        self.assertEqual(s["search"]["days"], 7)

    def test_explicit_config_path(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = Path(d) / "custom.yaml"
            cfg.write_text("ai:\n  enabled: false\n", encoding="utf-8")
            s = settings_mod.load_settings(config_path=str(cfg))
        self.assertFalse(s["ai"]["enabled"])

    def test_career_sites_flag_survives_validation(self):
        """Regression: `scrapers.career_sites` was silently dropped by the
        pydantic round-trip, so the doctor's "enable via ..." hint was a
        dead end. The flag must survive load_settings."""
        with tempfile.TemporaryDirectory() as d:
            cfg = Path(d) / "custom.yaml"
            cfg.write_text("scrapers:\n  career_sites: true\n", encoding="utf-8")
            s = settings_mod.load_settings(config_path=str(cfg))
        self.assertTrue(s["scrapers"]["career_sites"])
        self.assertEqual(s["scrapers"]["indeed_domain"], "in.indeed.com")  # default intact


if __name__ == "__main__":
    unittest.main()
