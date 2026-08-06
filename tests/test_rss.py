"""Hermetic tests for the RSS job source (strategy §6.2, Phase 7).

Network fetches are replaced with a stub returning an in-memory RSS payload;
check() states (off/ok/error) are exercised without any network.
"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

_RSS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Acme Careers</title>
    <link>https://acme.example/careers</link>
    <description>Jobs at Acme</description>
    <item>
      <title>Platform Engineer</title>
      <link>https://acme.example/jobs/platform-engineer</link>
      <description>Build kubernetes and aws infrastructure with terraform.</description>
      <pubDate>Mon, 03 Aug 2026 10:00:00 GMT</pubDate>
    </item>
    <item>
      <title>Office Manager</title>
      <link>https://acme.example/jobs/office-manager</link>
      <description>Run the front desk.</description>
      <pubDate>Tue, 04 Aug 2026 10:00:00 GMT</pubDate>
    </item>
  </channel>
</rss>
"""


class _Resp:
    def __init__(self, text, status_code=200):
        self.text = text
        self.status_code = status_code


class TestSearchRss(unittest.TestCase):
    def test_matches_query_and_maps_fields(self):
        from matcha.sources.rss import search_rss_jobs

        with mock.patch("matcha.sources.rss.resilient_get", return_value=_Resp(_RSS_XML)) as get:
            result = search_rss_jobs("kubernetes", feeds=["https://acme.example/feed"])
        get.assert_called_once()
        self.assertEqual(result.source, "RSS")
        self.assertEqual(result.backend, "rss")
        self.assertEqual(result.data_quality, "partial")
        self.assertEqual(len(result.jobs), 1)
        job = result.jobs[0]
        self.assertEqual(job["title"], "Platform Engineer")
        self.assertEqual(job["company"], "Acme Careers")
        self.assertIn("kubernetes", job["description"])
        self.assertIn("listed_epoch", job)
        self.assertTrue(job["listed_epoch"] > 0)

    def test_no_feeds_returns_empty(self):
        from matcha.sources.rss import search_rss_jobs

        result = search_rss_jobs("python", feeds=[])
        self.assertEqual(result.jobs, [])
        self.assertEqual(result.errors, [])

    def test_dead_feed_isolated(self):
        from matcha.sources.rss import search_rss_jobs

        with mock.patch("matcha.sources.rss.resilient_get", side_effect=OSError("boom")):
            result = search_rss_jobs("python", feeds=["https://x.example/feed"])
        self.assertEqual(result.jobs, [])
        self.assertTrue(any("boom" in e for e in result.errors))

    def test_http_error_feed_isolated(self):
        from matcha.sources.rss import search_rss_jobs

        with mock.patch(
            "matcha.sources.rss.resilient_get", return_value=_Resp("", status_code=500)
        ):
            result = search_rss_jobs("python", feeds=["https://x.example/feed"])
        self.assertEqual(result.jobs, [])
        self.assertTrue(any("500" in e for e in result.errors))

    def test_unparseable_feed_recorded(self):
        from matcha.sources.rss import search_rss_jobs

        with mock.patch(
            "matcha.sources.rss.resilient_get", return_value=_Resp("<html>not a feed</html>")
        ):
            result = search_rss_jobs("python", feeds=["https://x.example/feed"])
        self.assertEqual(result.jobs, [])
        self.assertTrue(any("unparseable" in e for e in result.errors))


class TestRssSourceCheck(unittest.TestCase):
    def setUp(self):
        from matcha.sources.rss import RSSSource

        self.src = RSSSource()

    def test_off_without_feeds(self):
        status, msg = self.src.check(None)
        self.assertEqual(status, "off")
        self.assertIsNone(self.src.active_backend)
        self.assertIn("feeds", msg)

    def test_ok_with_feeds(self):
        status, msg = self.src.check({"sources": {"rss": {"feeds": ["https://a/feed"]}}})
        self.assertEqual(status, "ok")
        self.assertEqual(self.src.active_backend, "rss")
        self.assertIn("1 feed", msg)

    def test_error_without_feedparser(self):
        with mock.patch("matcha.sources.rss.feedparser", None):
            status, _msg = self.src.check(None)
        self.assertEqual(status, "error")

    def test_feeds_from_config_helpers(self):
        from matcha.sources.rss import feeds_from_config

        self.assertEqual(feeds_from_config(None), [])
        self.assertEqual(feeds_from_config({"sources": {"rss": {"feeds": ["a", "", 3]}}}), ["a"])
        self.assertEqual(feeds_from_config({"sources": {}}), [])

    def test_search_delegates(self):
        with mock.patch("matcha.sources.rss.search_rss_jobs", return_value=mock.Mock()) as s:
            self.src.search("engineer", "pune", feeds=["https://a/feed"])
            s.assert_called_once()


if __name__ == "__main__":
    unittest.main()
