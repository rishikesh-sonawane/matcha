"""Hermetic tests for sources/base.py — probe_url statuses + Source helpers."""

import os
import sys
import unittest
from unittest import mock

from requests.exceptions import ConnectionError, Timeout

from matcha.models import ScraperResult
from matcha.sources.base import Source

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


class _Resp:
    def __init__(self, status_code):
        self.status_code = status_code

    def close(self):
        pass


class TestProbeUrl(unittest.TestCase):
    def test_ok(self):
        from matcha.sources.base import probe_url

        with mock.patch("matcha.sources.base.requests.get", return_value=_Resp(200)):
            self.assertEqual(probe_url("https://x"), ("ok", "HTTP 200"))

    def test_warn_gated(self):
        from matcha.sources.base import probe_url

        with mock.patch("matcha.sources.base.requests.get", return_value=_Resp(401)):
            status, _ = probe_url("https://x")
            self.assertEqual(status, "warn")

    def test_error_status(self):
        from matcha.sources.base import probe_url

        with mock.patch("matcha.sources.base.requests.get", return_value=_Resp(500)):
            self.assertEqual(probe_url("https://x")[0], "error")

    def test_timeout(self):
        from matcha.sources.base import probe_url

        with mock.patch("matcha.sources.base.requests.get", side_effect=Timeout()):
            self.assertEqual(probe_url("https://x")[0], "error")

    def test_connection_error(self):
        from matcha.sources.base import probe_url

        with mock.patch("matcha.sources.base.requests.get", side_effect=ConnectionError("no")):
            self.assertEqual(probe_url("https://x")[0], "error")

    def test_generic_exception(self):
        from matcha.sources.base import probe_url

        with mock.patch("matcha.sources.base.requests.get", side_effect=ValueError("bad")) as get:
            status, _msg = probe_url("https://x")
            self.assertEqual(status, "error")
            get.assert_called_once()


class _ConcreteSource(Source):
    """Minimal Source subclass so abstract helpers are testable."""

    def check(self, config=None):
        return "ok", ""

    def search(self, query, location="", **kwargs):
        return ScraperResult(jobs=[])


class TestSourceHelpers(unittest.TestCase):
    def test_ddgs_status(self):
        s = _ConcreteSource()
        self.assertEqual(s._ddgs_status(True)[0], "ok")
        self.assertEqual(s._ddgs_status(False)[0], "error")

    def test_scrapers_config_subsection(self):
        s = _ConcreteSource()
        self.assertEqual(s._scrapers_config({"scrapers": {"a": 1}}), {"a": 1})
        self.assertEqual(s._scrapers_config({}), {})
        self.assertEqual(s._scrapers_config(None), {})


if __name__ == "__main__":
    unittest.main()
