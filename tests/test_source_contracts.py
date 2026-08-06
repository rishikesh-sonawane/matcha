import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from matcha.models import ScraperResult
from matcha.sources import ALL_SOURCES, get_all_sources, get_source
from matcha.sources.base import Source

_VALID_STATUSES = {"ok", "warn", "off", "error"}

# source name -> (module search function to mock, expected job source label)
_SEARCH_TARGETS = {
    "linkedin": ("matcha.sources.linkedin.search_linkedin_jobs", "LinkedIn"),
    "indeed": ("matcha.sources.indeed.search_indeed_jobs", "Indeed"),
    "naukri": ("matcha.sources.naukri.search_naukri_jobs", "Naukri"),
    "remoteok": ("matcha.sources.remoteok.search_remoteok_jobs", "RemoteOK"),
    "web_search": ("matcha.sources.web_search.search_web_for_jobs", "Web Search"),
    "serpapi": ("matcha.sources.serpapi_jobs.search_serpapi_jobs", "Google Jobs"),
    "career_sites": ("matcha.sources.career_sites.search_career_sites_jobs", "Career Sites"),
    "rss": ("matcha.sources.rss.search_rss_jobs", "RSS"),
}


class TestSourceRegistry(unittest.TestCase):
    def test_registry_non_empty(self):
        self.assertTrue(len(ALL_SOURCES) > 0)

    def test_names_unique_and_non_empty(self):
        names = [s.name for s in ALL_SOURCES]
        self.assertEqual(len(names), len(set(names)))
        for n in names:
            self.assertTrue(n)

    def test_all_subclass_source(self):
        for s in ALL_SOURCES:
            self.assertIsInstance(s, Source)

    def test_get_source(self):
        self.assertIs(get_source("linkedin"), ALL_SOURCES[0])
        self.assertIsNone(get_source("nope"))

    def test_get_all_sources_returns_fresh_list(self):
        self.assertEqual(get_all_sources(), ALL_SOURCES)
        self.assertIsNot(get_all_sources(), ALL_SOURCES)


class TestSourceContract(unittest.TestCase):
    """Offline contract checks (mirrors Agent-Reach test_channel_contracts.py)."""

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

    def test_backends_ordered_non_empty(self):
        for s in ALL_SOURCES:
            self.assertTrue(s.backends, f"{s.name} must declare ordered backends")

    def test_ordered_backends_is_permutation(self):
        for s in ALL_SOURCES:
            self.assertEqual(sorted(s.ordered_backends()), sorted(s.backends))

    def test_ordered_backends_override_moves_to_front(self):
        s = ALL_SOURCES[0]
        target = s.backends[-1]
        ordered = s.ordered_backends({"scrapers": {f"{s.name}_backend": target}})
        self.assertEqual(ordered[0], target)

    def test_ordered_backends_unknown_override_ignored(self):
        s = ALL_SOURCES[0]
        ordered = s.ordered_backends({"scrapers": {f"{s.name}_backend": "nope"}})
        self.assertEqual(ordered, s.backends)

    def test_check_returns_valid_status_and_message(self):
        for s in ALL_SOURCES:
            status, message = s.check(None)
            self.assertIn(status, _VALID_STATUSES, f"{s.name}: {status}")
            self.assertIsInstance(message, str)
            self.assertTrue(message.strip(), f"{s.name}: empty message")
            self.assertTrue(
                s.active_backend is None or isinstance(s.active_backend, str),
                f"{s.name}: active_backend={s.active_backend!r}",
            )

    def test_check_sets_active_backend_on_ok(self):
        for s in ALL_SOURCES:
            s.check(None)
            if s.name in ("career_sites", "serpapi", "rss"):
                self.assertIsNone(s.active_backend)  # off by default (no config)
            else:
                self.assertIsNotNone(s.active_backend)

    def test_search_delegates_to_parser(self):
        for s in ALL_SOURCES:
            target, source_label = _SEARCH_TARGETS[s.name]
            with mock.patch(target, return_value=ScraperResult(source=source_label)) as m:
                result = s.search("engineer", "pune")
                m.assert_called_once()
            self.assertIsInstance(result, ScraperResult)
            self.assertEqual(result.source, source_label)


if __name__ == "__main__":
    unittest.main()
