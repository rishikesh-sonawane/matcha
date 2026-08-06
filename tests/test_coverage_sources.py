"""Hermetic coverage tests for source modules (Phase 7 coverage gate).

Covers career_sites.py, serpapi_jobs.py, web_search.py and linkedin.py —
pure helpers, DDGS/exa routing, source check/search classes, and the
mocked-HTTP paths. No network, no real config.
"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from matcha.models import ScraperResult


class _FakeDDGS:
    """Minimal DDGS stand-in: context manager with .text() returning rows."""

    def __init__(self, rows=None, exc=None):
        self._rows = rows or []
        self._exc = exc
        self.text_calls = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def text(self, query, max_results=5, timelimit=""):
        self.text_calls.append(query)
        if self._exc:
            raise self._exc
        return self._rows


class _Resp:
    def __init__(self, json_data=None, status_code=200, text=""):
        self.json_data = json_data or {}
        self.status_code = status_code
        self.text = text

    def json(self):
        return self.json_data


# ── career_sites.py ──────────────────────────────────────────────────


class TestCareerSitesHelpers(unittest.TestCase):
    def test_dedup_jobs(self):
        from matcha.sources.career_sites import _dedup_jobs

        jobs = [{"url": "a"}, {"url": "b"}, {"url": "a"}]
        out = _dedup_jobs(jobs)
        self.assertEqual([j["url"] for j in out], ["a", "b"])

    def test_is_older_than_days(self):
        from matcha.sources.career_sites import _is_older_than_days

        self.assertTrue(_is_older_than_days("posted 2 years ago", 30))
        self.assertTrue(_is_older_than_days("3 months ago", 30))
        self.assertTrue(_is_older_than_days("2 weeks ago", 7))
        self.assertTrue(_is_older_than_days("posted 5 days ago", 3))
        self.assertFalse(_is_older_than_days("2 days ago", 7))
        self.assertFalse(_is_older_than_days("no date here", 7))
        self.assertFalse(_is_older_than_days("", 7))

    def test_is_older_than_days_month_name(self):
        from matcha.sources.career_sites import _is_older_than_days

        # Ancient month in a past year is old
        self.assertTrue(_is_older_than_days("Posted: January 1, 2020", 30))
        # Recent month with no year resolves to current year -> young
        self.assertFalse(_is_older_than_days("posted: july 1", 3650))

    def test_is_search_page(self):
        from matcha.sources.career_sites import _is_search_page

        self.assertTrue(_is_search_page("Jobs in Bengaluru", "https://x/jobs"))
        self.assertTrue(_is_search_page("T", "https://x/search?q=y"))
        self.assertFalse(_is_search_page("Engineer job", "https://x/job/1"))

    def test_clean_title(self):
        from matcha.sources.career_sites import _clean_title

        self.assertEqual(_clean_title("Software Engineer - Google"), "Software Engineer")
        self.assertEqual(_clean_title("Engineer | LinkedIn"), "Engineer")
        self.assertEqual(_clean_title("Engineer - Hiring - Google"), "Engineer")
        self.assertEqual(_clean_title("Single Title"), "Single Title")

    def test_match_company(self):
        from matcha.sources.career_sites import _match_company

        self.assertEqual(_match_company("https://careers.google.com/jobs/1"), "Google")
        self.assertEqual(_match_company("https://www.amazon.jobs/job/x"), "Amazon")
        self.assertEqual(_match_company("https://careers.examplecorp.com/x"), "Careers")
        self.assertEqual(_match_company("https://unknown-org.example"), "Unknown-Org")

    def test_extract_location(self):
        from matcha.sources.career_sites import _extract_location

        self.assertEqual(_extract_location("Engineer in Bengaluru, KA", "T"), "Bengaluru, KA")
        self.assertEqual(_extract_location("no location", "T"), "Remote / Unspecified")

    def test_build_queries(self):
        from matcha.sources.career_sites import _build_queries

        queries = _build_queries("engineer", "Pune")
        self.assertTrue(any("myworkdayjobs" in q for q in queries))
        self.assertTrue(any("careers.google.com" in q for q in queries))
        self.assertTrue(all("engineer" in q for q in queries))

    def test_search_no_ddgs(self):
        from matcha.sources.career_sites import search_career_sites_jobs

        with mock.patch("matcha.sources.career_sites.DDGS", None):
            result = search_career_sites_jobs("engineer")
        self.assertEqual(result.errors, ["ddgs library not available"])

    def test_search_happy_path(self):
        from matcha.sources.career_sites import search_career_sites_jobs

        fake = _FakeDDGS(
            rows=[
                {
                    "title": "Backend Engineer - Google",
                    "href": "https://careers.google.com/jobs/1",
                    "body": "Join us in Bengaluru",
                }
            ]
        )
        with (
            mock.patch("matcha.sources.career_sites.DDGS", lambda: fake),
            mock.patch("matcha.sources.career_sites.limiter.acquire"),
        ):
            result = search_career_sites_jobs("engineer", "Pune", days=7, max_queries=2)
        self.assertEqual(len(result.jobs), 1)
        self.assertEqual(result.jobs[0]["company"], "Google")
        self.assertEqual(result.backend, "ddgs")

    def test_search_filters_search_pages(self):
        from matcha.sources.career_sites import search_career_sites_jobs

        fake = _FakeDDGS(
            rows=[
                {
                    "title": "Jobs at Google",
                    "href": "https://careers.google.com/search?q=x",
                    "body": "",
                },
                {
                    "title": "Real Job",
                    "href": "https://careers.google.com/jobs/2",
                    "body": "in Bengaluru",
                },
            ]
        )
        with (
            mock.patch("matcha.sources.career_sites.DDGS", lambda: fake),
            mock.patch("matcha.sources.career_sites.limiter.acquire"),
        ):
            result = search_career_sites_jobs("engineer", max_queries=1)
        self.assertEqual([j["title"] for j in result.jobs], ["Real Job"])

    def test_search_old_posting_filtered(self):
        from matcha.sources.career_sites import search_career_sites_jobs

        fake = _FakeDDGS(
            rows=[
                {"title": "Old Job", "href": "https://x.com/job/1", "body": "posted 2 years ago"},
            ]
        )
        with (
            mock.patch("matcha.sources.career_sites.DDGS", lambda: fake),
            mock.patch("matcha.sources.career_sites.limiter.acquire"),
        ):
            result = search_career_sites_jobs("engineer", days=7, max_queries=1)
        self.assertEqual(result.jobs, [])

    def test_search_query_exception(self):
        from matcha.sources.career_sites import search_career_sites_jobs

        fake = _FakeDDGS(exc=RuntimeError("ddgs down"))
        with (
            mock.patch("matcha.sources.career_sites.DDGS", lambda: fake),
            mock.patch("matcha.sources.career_sites.limiter.acquire"),
        ):
            result = search_career_sites_jobs("engineer", max_queries=1)
        self.assertTrue(result.errors)

    def test_search_parse_exception(self):
        from matcha.sources.career_sites import search_career_sites_jobs

        class _BadRow:
            def get(self, *a):
                raise AttributeError("boom")

        fake = _FakeDDGS(rows=[_BadRow()])
        with (
            mock.patch("matcha.sources.career_sites.DDGS", lambda: fake),
            mock.patch("matcha.sources.career_sites.limiter.acquire"),
        ):
            result = search_career_sites_jobs("engineer", max_queries=1)
        self.assertEqual(result.jobs, [])


class TestCareerSitesSource(unittest.TestCase):
    def test_check_disabled(self):
        from matcha.sources.career_sites import CareerSitesSource

        s = CareerSitesSource()
        status, msg = s.check({"scrapers": {}})
        self.assertEqual(status, "off")
        self.assertIsNone(s.active_backend)

    def test_check_enabled_ok(self):
        from matcha.sources.career_sites import CareerSitesSource

        s = CareerSitesSource()
        with mock.patch("matcha.sources.career_sites.DDGS", object()):
            status, msg = s.check({"scrapers": {"career_sites": True}})
        self.assertEqual(status, "ok")
        self.assertEqual(s.active_backend, "ddgs")

    def test_check_enabled_no_ddgs(self):
        from matcha.sources.career_sites import CareerSitesSource

        s = CareerSitesSource()
        with mock.patch("matcha.sources.career_sites.DDGS", None):
            status, msg = s.check({"scrapers": {"career_sites": True}})
        self.assertEqual(status, "error")

    def test_search_delegates(self):
        from matcha.sources.career_sites import CareerSitesSource

        s = CareerSitesSource()
        with mock.patch(
            "matcha.sources.career_sites.search_career_sites_jobs",
            return_value=ScraperResult(jobs=[], source="Career Sites"),
        ) as f:
            s.search("q", "loc")
        f.assert_called_once()


# ── serpapi_jobs.py ──────────────────────────────────────────────────


class TestSerpapi(unittest.TestCase):
    def test_search_no_key(self):
        from matcha.sources.serpapi_jobs import search_serpapi_jobs

        with mock.patch("matcha.sources.serpapi_jobs.get_serpapi_config", return_value={}):
            result = search_serpapi_jobs("engineer")
        self.assertEqual(result.errors, ["SerpAPI key not configured"])

    def test_search_happy_path(self):
        from matcha.sources.serpapi_jobs import search_serpapi_jobs

        payload = {
            "jobs_results": [
                {
                    "title": "Engineer",
                    "company_name": "Acme",
                    "location": "Bengaluru",
                    "description": "desc",
                    "related_links": [{"link": "https://apply"}],
                }
            ]
        }
        with (
            mock.patch(
                "matcha.sources.serpapi_jobs.get_serpapi_config",
                return_value={"serpapi_key": "k"},
            ),
            mock.patch("matcha.sources.serpapi_jobs.resilient_get", return_value=_Resp(payload)),
        ):
            result = search_serpapi_jobs("engineer", "Pune", days=7)
        self.assertEqual(len(result.jobs), 1)
        self.assertEqual(result.jobs[0]["company"], "Acme")
        self.assertEqual(result.backend, "serpapi")

    def test_search_pagination_and_no_results(self):
        from matcha.sources.serpapi_jobs import search_serpapi_jobs

        with (
            mock.patch(
                "matcha.sources.serpapi_jobs.get_serpapi_config",
                return_value={"serpapi_key": "k"},
            ),
            mock.patch(
                "matcha.sources.serpapi_jobs.resilient_get",
                side_effect=[_Resp({"jobs_results": []})],
            ),
        ):
            result = search_serpapi_jobs("engineer", max_pages=3)
        self.assertEqual(result.jobs, [])

    def test_search_bad_status(self):
        from matcha.sources.serpapi_jobs import search_serpapi_jobs

        with (
            mock.patch(
                "matcha.sources.serpapi_jobs.get_serpapi_config",
                return_value={"serpapi_key": "k"},
            ),
            mock.patch(
                "matcha.sources.serpapi_jobs.resilient_get", return_value=_Resp({}, status_code=500)
            ),
        ):
            result = search_serpapi_jobs("engineer")
        self.assertTrue(result.errors)

    def test_search_api_error(self):
        from matcha.sources.serpapi_jobs import search_serpapi_jobs

        with (
            mock.patch(
                "matcha.sources.serpapi_jobs.get_serpapi_config",
                return_value={"serpapi_key": "k"},
            ),
            mock.patch(
                "matcha.sources.serpapi_jobs.resilient_get",
                return_value=_Resp({"error": "invalid key"}),
            ),
        ):
            result = search_serpapi_jobs("engineer")
        self.assertTrue(any("invalid key" in e for e in result.errors))

    def test_search_application_link_fallback(self):
        from matcha.sources.serpapi_jobs import search_serpapi_jobs

        payload = {
            "jobs_results": [
                {
                    "title": "Engineer",
                    "company_name": "Acme",
                    "location": "Remote",
                    "description": "d",
                    "related_links": [{"type": "application", "link": "https://apply/x"}],
                }
            ]
        }
        with (
            mock.patch(
                "matcha.sources.serpapi_jobs.get_serpapi_config",
                return_value={"serpapi_key": "k"},
            ),
            mock.patch("matcha.sources.serpapi_jobs.resilient_get", return_value=_Resp(payload)),
        ):
            result = search_serpapi_jobs("engineer")
        self.assertEqual(result.jobs[0]["url"], "https://apply/x")

    def test_source_check_and_search(self):
        from matcha.sources.serpapi_jobs import SerpapiSource

        s = SerpapiSource()
        with mock.patch("matcha.sources.serpapi_jobs.check_serpapi_available", return_value=True):
            status, msg = s.check()
        self.assertEqual(status, "ok")
        self.assertEqual(s.active_backend, "serpapi")
        with mock.patch("matcha.sources.serpapi_jobs.check_serpapi_available", return_value=False):
            status, msg = s.check()
        self.assertEqual(status, "off")

    def test_check_serpapi_available(self):
        from matcha.sources.serpapi_jobs import check_serpapi_available

        with mock.patch(
            "matcha.sources.serpapi_jobs.get_serpapi_config", return_value={"serpapi_key": "k"}
        ):
            self.assertTrue(check_serpapi_available())

    def test_get_serpapi_config_import_fallback(self):
        from matcha.sources.serpapi_jobs import get_serpapi_config

        with mock.patch("matcha.config.load_config", side_effect=ImportError):
            self.assertEqual(get_serpapi_config(), {})


# ── web_search.py ────────────────────────────────────────────────────


class TestWebSearch(unittest.TestCase):
    def test_dedup(self):
        from matcha.sources.web_search import _dedup_jobs

        self.assertEqual([j["url"] for j in _dedup_jobs([{"url": "a"}, {"url": "a"}])], ["a"])

    def test_iso_older_than_days(self):
        from matcha.sources.web_search import _iso_older_than_days

        self.assertTrue(_iso_older_than_days("2020-01-01", 30))
        self.assertFalse(_iso_older_than_days("", 30))
        self.assertFalse(_iso_older_than_days("not-a-date", 30))
        # Future date -> young
        self.assertFalse(_iso_older_than_days("2999-01-01", 30))

    def test_clean_title_variants(self):
        from matcha.sources.web_search import _clean_title

        self.assertEqual(
            _clean_title("Acme is hiring a Backend Engineer in Pune"), "a Backend Engineer"
        )
        self.assertEqual(_clean_title("Engineer - Indeed"), "Engineer")

    def test_extract_company_from_snippet(self):
        from matcha.sources.web_search import _extract_company

        self.assertEqual(
            _extract_company("https://x", "Acme Corp is looking for engineers", "T"), "Acme Corp"
        )
        self.assertEqual(_extract_company("https://www.lever.co/x", "no match", "T"), "Lever")

    def test_extract_location_and_source(self):
        from matcha.sources.web_search import _extract_location, _identify_source

        self.assertEqual(_extract_location("Engineer in Bengaluru", "u", "t"), "Bengaluru")
        self.assertEqual(_extract_location("", "u", "t"), "Remote / Unspecified")
        self.assertEqual(_identify_source("https://www.greenhouse.io/jobs/x"), "Greenhouse")
        self.assertEqual(_identify_source("https://example.com/jobs/x"), "Example")

    def test_search_exa_routing(self):
        from matcha.sources.web_search import search_web_for_jobs

        with (
            mock.patch("matcha.sources.web_search._exa_should_run", return_value=True),
            mock.patch(
                "matcha.sources.web_search._search_web_exa",
                return_value=ScraperResult(jobs=[], source="Web Search", backend="exa"),
            ) as exa,
        ):
            result = search_web_for_jobs("engineer")
        self.assertEqual(result.backend, "exa")
        exa.assert_called_once()

    def test_search_exa_returns_none_falls_back(self):
        from matcha.sources.web_search import search_web_for_jobs

        fake = _FakeDDGS(
            rows=[
                {
                    "title": "Engineer - Acme",
                    "href": "https://acme.com/jobs/1",
                    "body": "in Bengaluru",
                }
            ]
        )
        with (
            mock.patch("matcha.sources.web_search._search_web_exa", return_value=None),
            mock.patch("matcha.sources.web_search.DDGS", lambda: fake),
            mock.patch("matcha.sources.web_search.limiter.acquire"),
        ):
            result = search_web_for_jobs("engineer")
        self.assertEqual(result.backend, "ddgs")
        self.assertEqual(len(result.jobs), 1)

    def test_search_exa_parse_rows(self):
        from matcha.sources.web_search import _search_web_exa

        rows = [
            {
                "title": "Senior Engineer - Acme",
                "url": "https://acme.com/jobs/1",
                "text": "text",
                "author": "Acme",
                "publishedDate": "2025-06-01",
                "score": 0.9,
            }
        ]
        with mock.patch("matcha.sources.backends.exa.exa_search", return_value=rows):
            result = _search_web_exa("engineer", num=5)
        self.assertEqual(len(result.jobs), 1)
        self.assertEqual(result.jobs[0]["company"], "Acme")
        self.assertEqual(result.jobs[0]["listed"], "2025-06-01")

    def test_search_exa_none(self):
        from matcha.sources.web_search import _search_web_exa

        with mock.patch("matcha.sources.backends.exa.exa_search", return_value=None):
            self.assertIsNone(_search_web_exa("engineer"))

    def test_search_exa_old_posting_skipped(self):
        from matcha.sources.web_search import _search_web_exa

        rows = [
            {
                "title": "Old",
                "url": "https://acme.com/jobs/2",
                "text": "t",
                "publishedDate": "2020-01-01",
            }
        ]
        with mock.patch("matcha.sources.backends.exa.exa_search", return_value=rows):
            result = _search_web_exa("engineer", days=30, num=5)
        self.assertEqual(result.jobs, [])

    def test_search_ddgs_no_lib(self):
        from matcha.sources.web_search import _search_web_ddgs

        with mock.patch("matcha.sources.web_search.DDGS", None):
            result = _search_web_ddgs("engineer")
        self.assertEqual(result.errors, ["ddgs library not available"])

    def test_search_ddgs_filters(self):
        from matcha.sources.web_search import _search_web_ddgs

        fake = _FakeDDGS(
            rows=[
                {"title": "Jobs at X", "href": "https://x/search?q=1", "body": ""},
                {"title": "Engineer - Acme", "href": "https://acme.com/job/2", "body": "in Pune"},
            ]
        )
        with (
            mock.patch("matcha.sources.web_search.DDGS", lambda: fake),
            mock.patch("matcha.sources.web_search.limiter.acquire"),
        ):
            result = _search_web_ddgs("engineer")
        self.assertEqual([j["title"] for j in result.jobs], ["Engineer"])

    def test_web_search_source_check(self):
        from matcha.sources.web_search import WebSearchSource

        s = WebSearchSource()
        with mock.patch(
            "matcha.sources.backends.exa.exa_status", return_value=("warn", "configured")
        ):
            status, msg = s.check()
        self.assertEqual(status, "warn")
        self.assertEqual(s.active_backend, "exa")

        with (
            mock.patch(
                "matcha.sources.backends.exa.exa_status", return_value=("off", "no mcporter")
            ),
            mock.patch("matcha.sources.web_search.DDGS", object()),
        ):
            status, msg = s.check()
        self.assertEqual(status, "ok")
        self.assertEqual(s.active_backend, "ddgs")


# ── linkedin.py ──────────────────────────────────────────────────────


class TestLinkedIn(unittest.TestCase):
    def test_date_posted_flag(self):
        from matcha.sources.linkedin import _date_posted_flag

        self.assertEqual(_date_posted_flag(7), "week")
        self.assertEqual(_date_posted_flag(30), "month")
        self.assertEqual(_date_posted_flag(90), "any")

    def test_parse_rows(self):
        from matcha.sources.linkedin import _parse_linkedin_rows

        rows = [
            {
                "title": "Engineer",
                "company": "Acme",
                "location": "Pune",
                "url": "https://li/x",
                "salary": "10L",
            },
            {"title": "", "company": "X"},  # skipped: blank title
        ]
        jobs = _parse_linkedin_rows(rows, "India")
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["salary"], "10L")

    def test_opencli_backend_happy(self):
        from matcha.sources.linkedin import _search_linkedin_opencli

        with mock.patch(
            "matcha.sources.linkedin.run_opencli",
            return_value={"ok": True, "rows": [{"title": "E", "url": "https://li/1"}], "error": ""},
        ) as run:
            result = _search_linkedin_opencli("engineer", "Pune", days=7)
        self.assertEqual(len(result.jobs), 1)
        self.assertEqual(result.backend, "opencli")
        run.assert_called_once()
        self.assertIn("--date-posted", run.call_args.args[0])

    def test_opencli_backend_failure_returns_none(self):
        from matcha.sources.linkedin import _search_linkedin_opencli

        with mock.patch(
            "matcha.sources.linkedin.run_opencli",
            return_value={"ok": False, "rows": [], "error": "boom"},
        ):
            self.assertIsNone(_search_linkedin_opencli("engineer", days=7))

    def test_guest_api_happy(self):
        from matcha.sources.linkedin import _search_linkedin_guest_api

        html = (
            "<li><a class='base-card__full-link' href='/jobs/view/1'>"
            "<h3 class='base-search-card__title'>Engineer</h3>"
            "<span class='job-search-card__company-name'>Acme</span>"
            "<span class='job-search-card__location'>Pune</span></a></li>"
        )
        with mock.patch("matcha.sources.linkedin.resilient_get", return_value=_Resp({}, text=html)):
            result = _search_linkedin_guest_api("engineer", "Pune", days=7)
        self.assertEqual(len(result.jobs), 1)
        self.assertTrue(result.jobs[0]["url"].startswith("https://www.linkedin.com"))
        self.assertEqual(result.backend, "guest-api")

    def test_guest_api_bad_status(self):
        from matcha.sources.linkedin import _search_linkedin_guest_api

        with mock.patch(
            "matcha.sources.linkedin.resilient_get", return_value=_Resp({}, status_code=429)
        ):
            result = _search_linkedin_guest_api("engineer")
        self.assertTrue(result.errors)

    def test_guest_api_request_exception(self):
        import requests

        from matcha.sources.linkedin import _search_linkedin_guest_api

        with mock.patch(
            "matcha.sources.linkedin.resilient_get",
            side_effect=requests.RequestException("down"),
        ):
            result = _search_linkedin_guest_api("engineer")
        self.assertTrue(result.errors)

    def test_search_routing_opencli_fallback(self):
        from matcha.sources.linkedin import search_linkedin_jobs

        with (
            mock.patch("matcha.sources.linkedin._search_linkedin_opencli", return_value=None),
            mock.patch(
                "matcha.sources.linkedin._search_linkedin_guest_api",
                return_value=ScraperResult(jobs=[], source="LinkedIn", backend="guest-api"),
            ),
        ):
            result = search_linkedin_jobs("engineer", backend="opencli")
        self.assertEqual(result.backend, "guest-api")

    def test_search_guest_direct(self):
        from matcha.sources.linkedin import search_linkedin_jobs

        with mock.patch(
            "matcha.sources.linkedin._search_linkedin_guest_api",
            return_value=ScraperResult(jobs=[], source="LinkedIn", backend="guest-api"),
        ):
            result = search_linkedin_jobs("engineer")
        self.assertEqual(result.backend, "guest-api")


if __name__ == "__main__":
    unittest.main()
