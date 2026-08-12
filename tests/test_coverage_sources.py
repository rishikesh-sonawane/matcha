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
    """Minimal DDGS stand-in: context manager with .text() returning rows.

    Accepts the ``timeout`` kwarg the shared ``ddgs_text`` helper passes to
    the factory (Session 23), and records call kwargs for retry assertions.
    """

    def __init__(self, rows=None, exc=None, timeout=None):
        self._rows = rows or []
        self._exc = exc
        self._timeout = timeout
        self.text_calls = []
        self.text_kwargs = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def text(self, query, max_results=5, timelimit=""):
        self.text_calls.append(query)
        self.text_kwargs.append((max_results, timelimit))
        if self._exc:
            raise self._exc
        return self._rows


class _Resp:
    def __init__(self, json_data=None, status_code=200, text="", url=""):
        self.json_data = json_data or {}
        self.status_code = status_code
        self.text = text
        self.url = url or "https://example.com/job/1"

    def json(self):
        return self.json_data

    def close(self):
        pass

    def iter_content(self, chunk_size):
        return iter([self.text.encode("utf-8")])


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

        self.assertEqual(_extract_location("Engineer in Bengaluru, KA", "T"), "Bengaluru")
        self.assertEqual(_extract_location("no location", "T"), "Remote / Unspecified")

    def test_extract_location_prefers_known_city(self):
        # Session 28: the loose regex misreads "in Managing cloud
        # infrastructure" as a location — a known city wins first.
        from matcha.sources.career_sites import _extract_location

        self.assertEqual(
            _extract_location("Join us in Pune to build cloud infra", "DevOps Engineer"), "Pune"
        )
        self.assertEqual(
            _extract_location("in Managing cloud infrastructure", "DevOps"),
            "Remote / Unspecified",
        )

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
            mock.patch("matcha.sources.career_sites.DDGS", lambda *a, **k: fake),
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
                    "title": "Real Engineer Job",
                    "href": "https://careers.google.com/jobs/2",
                    "body": "in Bengaluru",
                },
            ]
        )
        with (
            mock.patch("matcha.sources.career_sites.DDGS", lambda *a, **k: fake),
            mock.patch("matcha.sources.career_sites.limiter.acquire"),
        ):
            result = search_career_sites_jobs("engineer", max_queries=1)
        self.assertEqual([j["title"] for j in result.jobs], ["Real Engineer Job"])

    def test_search_drops_homepage_urls(self):
        # Session 27: ``site:lever.co`` returns the company homepage
        # (``/?lang=fa``) as a "job" — never a posting, always dropped.
        from matcha.sources.career_sites import search_career_sites_jobs

        fake = _FakeDDGS(
            rows=[
                {
                    "title": "Lever",
                    "href": "https://www.lever.co/?lang=fa",
                    "body": "",
                },
                {
                    "title": "Software Engineer - Lever",
                    "href": "https://jobs.lever.co/acme/80f1379e",
                    "body": "in Pune",
                },
            ]
        )
        with (
            mock.patch("matcha.sources.career_sites.DDGS", lambda *a, **k: fake),
            mock.patch("matcha.sources.career_sites.limiter.acquire"),
        ):
            result = search_career_sites_jobs("engineer", "Pune", max_queries=1)
        self.assertEqual([j["title"] for j in result.jobs], ["Software Engineer"])

    def test_search_drops_unrelated_rows(self):
        # Session 27: a ``site:smartrecruiters.com DevOps Engineer Pune`` hit
        # can be an unrelated posting on the same board (e.g. a Canadian
        # hospital's intake assistant) — no query/location token, no role word.
        from matcha.sources.career_sites import search_career_sites_jobs

        fake = _FakeDDGS(
            rows=[
                {
                    "title": "Halton Healthcare Intake Assistant",
                    "href": "https://jobs.smartrecruiters.com/HaltonHealthcare1/3743",
                    "body": "caregiving",
                },
                {
                    "title": "Senior Staff Engineer - Nagarro",
                    "href": "https://jobs.smartrecruiters.com/Nagarro1/7440",
                    "body": "in Pune",
                },
            ]
        )
        with (
            mock.patch("matcha.sources.career_sites.DDGS", lambda *a, **k: fake),
            mock.patch("matcha.sources.career_sites.limiter.acquire"),
        ):
            result = search_career_sites_jobs("DevOps Engineer", "Pune", max_queries=1)
        self.assertEqual([j["title"] for j in result.jobs], ["Senior Staff Engineer"])

    def test_search_old_posting_filtered(self):
        from matcha.sources.career_sites import search_career_sites_jobs

        fake = _FakeDDGS(
            rows=[
                {"title": "Old Job", "href": "https://x.com/job/1", "body": "posted 2 years ago"},
            ]
        )
        with (
            mock.patch("matcha.sources.career_sites.DDGS", lambda *a, **k: fake),
            mock.patch("matcha.sources.career_sites.limiter.acquire"),
        ):
            result = search_career_sites_jobs("engineer", days=7, max_queries=1)
        self.assertEqual(result.jobs, [])

    def test_search_query_exception(self):
        from matcha.sources.career_sites import search_career_sites_jobs

        fake = _FakeDDGS(exc=RuntimeError("ddgs down"))
        with (
            mock.patch("matcha.sources.career_sites.DDGS", lambda *a, **k: fake),
            mock.patch("matcha.sources.career_sites.limiter.acquire"),
            mock.patch("matcha.sources.utils.time.sleep"),  # retry backoff
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
            mock.patch("matcha.sources.career_sites.DDGS", lambda *a, **k: fake),
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
        # Session 21: google_jobs now puts apply URLs under ``apply_options``
        # (``related_links`` is null) — without this every row lost its URL
        # and the quality gate dropped the whole source.
        from matcha.sources.serpapi_jobs import search_serpapi_jobs

        payload = {
            "jobs_results": [
                {
                    "title": "Engineer",
                    "company_name": "Acme",
                    "location": "Remote",
                    "description": "d",
                    "apply_options": [
                        {"title": "Google", "link": "https://www.google.com/search?q=apply"},
                        {"title": "Acme", "link": "https://apply/x"},
                    ],
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

    def test_search_parses_detected_extensions_posted_at(self):
        # Session 22: google_jobs reports the posting date under
        # detected_extensions.posted_at ("3 days ago") — without it every row
        # carried [age?] and skipped the age filter entirely.
        from matcha.sources.serpapi_jobs import search_serpapi_jobs

        payload = {
            "jobs_results": [
                {
                    "title": "Engineer",
                    "company_name": "Acme",
                    "location": "Hyderabad",
                    "description": "d",
                    "apply_options": [{"title": "Acme", "link": "https://apply/x"}],
                    "detected_extensions": {"posted_at": "3 days ago"},
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
        self.assertEqual(result.jobs[0]["listed"], "3 days ago")
        # age pipeline can then parse it into a listed_epoch
        from matcha.normalization import normalize_jobs

        normalize_jobs(result.jobs)
        self.assertIsNotNone(result.jobs[0]["listed_epoch"])

    def test_search_no_posted_at_stamps_window(self):
        # Session 22: SerpAPI omits the date on some rows but applies
        # ``date_posted`` SERVER-SIDE — a row returned under a window IS within
        # it. Stamp the window truthfully ("within week") + a worst-case
        # listed_epoch so the age filter can judge it instead of [age?].
        from matcha.sources.serpapi_jobs import search_serpapi_jobs

        payload = {
            "jobs_results": [
                {
                    "title": "Engineer",
                    "company_name": "Acme",
                    "location": "Hyderabad",
                    "description": "d",
                    "apply_options": [{"title": "Acme", "link": "https://apply/x"}],
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
            result = search_serpapi_jobs("engineer", days=3)
        self.assertEqual(result.jobs[0]["listed"], "within 3days")
        self.assertIsNotNone(result.jobs[0]["listed_epoch"])

    def test_search_no_posted_at_loose_window_keeps_age_tag(self):
        # Reviewer-caught (Session 22): days=5 maps to date_posted="week" — a
        # 7-day window is LOOSER than the requested 5 days, so a window stamp
        # would lie (row could be 6 days old) and the central 5-day filter
        # would then silently drop it. Keep the honest [age?] tag instead.
        from matcha.sources.serpapi_jobs import search_serpapi_jobs

        payload = {
            "jobs_results": [
                {
                    "title": "Engineer",
                    "company_name": "Acme",
                    "location": "Hyderabad",
                    "description": "d",
                    "apply_options": [{"title": "Acme", "link": "https://apply/x"}],
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
            result = search_serpapi_jobs("engineer", days=5)
        self.assertNotIn("listed", result.jobs[0])
        self.assertNotIn("listed_epoch", result.jobs[0])

    def test_search_window_epoch_bounds(self):
        # Worst-case epoch: a "within 3days" row must not be older than 3 days.
        import time

        from matcha.sources.serpapi_jobs import _window_epoch

        self.assertLessEqual(time.time() - _window_epoch("3days"), 3 * 86400 + 60)
        self.assertGreater(time.time() - _window_epoch("3days"), 2 * 86400)

    def test_search_source_link_fallback_when_no_apply_options(self):
        from matcha.sources.serpapi_jobs import search_serpapi_jobs

        payload = {
            "jobs_results": [
                {
                    "title": "Engineer",
                    "company_name": "Acme",
                    "location": "Remote",
                    "description": "d",
                    "source_link": "https://ats.example/123",
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
        self.assertEqual(result.jobs[0]["url"], "https://ats.example/123")

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

    def test_extract_company_from_url(self):
        # Session 30: Exa's ``author`` field is page-scraped noise ("scale"
        # for a Vodafone job) — the posting's own host names the company.
        from matcha.sources.web_search import _extract_company_from_url

        self.assertEqual(
            _extract_company_from_url(
                "https://opportunities.vodafone.com/job/Pune-AWS-Cloud-DevOps/1395729933/"
            ),
            "Vodafone",
        )
        self.assertEqual(
            _extract_company_from_url(
                "https://jobs.sanofi.com/en/job/hyderabad/lead-container-platform-engineer/2"
            ),
            "Sanofi",
        )
        self.assertEqual(
            _extract_company_from_url(
                "https://careers.unitedhealthgroup.com/job/bengaluru/senior-devops-engineer/34088/"
            ),
            "Unitedhealthgroup",
        )
        self.assertEqual(
            _extract_company_from_url(
                "https://koch.avature.net/en_US/careers/JobDetail/Platform-Engineer/188227"
            ),
            "Koch",
        )
        self.assertEqual(
            _extract_company_from_url("https://www.globallogic.com/careers/telecom-devops/1"),
            "Globallogic",
        )
        # Plain host, no noise
        self.assertEqual(_extract_company_from_url("https://acme.com/jobs/3"), "Acme")
        # ATS platform host without a company subdomain: company lives in the
        # path, so the host cannot name it — caller falls back to author/text.
        self.assertEqual(
            _extract_company_from_url("https://boards.greenhouse.io/acme/12345"), ""
        )
        # Company label BEFORE a generic subdomain is still found
        self.assertEqual(
            _extract_company_from_url("https://acme.jobs.lever.co/80f1379e"), "Acme"
        )
        # Generic-label-before-platform: company is in the path (jobs.lever.co/acme)
        self.assertEqual(_extract_company_from_url("https://jobs.lever.co/acme/123"), "")
        # www2. stripped, then company found
        self.assertEqual(_extract_company_from_url("https://www2.globallogic.com/x"), "Globallogic")
        # Workday host prefix carries no company name (company is in the path)
        self.assertEqual(
            _extract_company_from_url("https://wd5.myworkdayjobs.com/Company/job/x"), ""
        )
        # Subdomain TLD mid-host still resolves left→right
        self.assertEqual(_extract_company_from_url("https://jobs.company.com.au/job/1"), "Company")
        self.assertEqual(_extract_company_from_url(""), "")

    def test_url_is_live(self):
        from matcha.sources.web_search import _url_is_live

        # 404 / 410 → hard dead
        with mock.patch(
            "matcha.sources.web_search.resilient_get",
            return_value=_Resp({}, status_code=404),
        ):
            self.assertFalse(_url_is_live("https://a.com/job/1"))
        with mock.patch(
            "matcha.sources.web_search.resilient_get",
            return_value=_Resp({}, status_code=410),
        ):
            self.assertFalse(_url_is_live("https://a.com/job/1"))
        # 200 deep page → alive
        with mock.patch(
            "matcha.sources.web_search.resilient_get",
            return_value=_Resp({}, status_code=200, url="https://a.com/job/1"),
        ):
            self.assertTrue(_url_is_live("https://a.com/job/1"))
        # Redirect chain ends on the bare site root → posting closed
        with mock.patch(
            "matcha.sources.web_search.resilient_get",
            return_value=_Resp({}, status_code=200, url="https://a.com/"),
        ):
            self.assertFalse(_url_is_live("https://a.com/job/1"))
        # Localized-homepage bounce (jobs.sanofi.com/en) is a closed posting too
        with mock.patch(
            "matcha.sources.web_search.resilient_get",
            return_value=_Resp({}, status_code=200, url="https://a.com/en"),
        ):
            self.assertFalse(_url_is_live("https://a.com/job/1"))
        # But a real job deep-link (with locale prefix) is alive
        with mock.patch(
            "matcha.sources.web_search.resilient_get",
            return_value=_Resp({}, status_code=200, url="https://a.com/en/job/1"),
        ):
            self.assertTrue(_url_is_live("https://a.com/en/job/1"))
        # Bot wall (403) is NOT proof of death — Indeed/WWR 403 curl but live
        with mock.patch(
            "matcha.sources.web_search.resilient_get",
            return_value=_Resp({}, status_code=403, url="https://a.com/job/1"),
        ):
            self.assertTrue(_url_is_live("https://a.com/job/1"))
        # 5xx / maintenance is NOT proof of death
        with mock.patch(
            "matcha.sources.web_search.resilient_get",
            return_value=_Resp({}, status_code=503, url="https://a.com/job/1"),
        ):
            self.assertTrue(_url_is_live("https://a.com/job/1"))
        # Session 31: a 403 bot wall that redirects to a literal /Error path
        # (Avature/Koch bounces closed postings there) IS a dead signal —
        # checked for every status, not just 2xx.
        with mock.patch(
            "matcha.sources.web_search.resilient_get",
            return_value=_Resp(
                {},
                status_code=403,
                url="https://koch.avature.net/en_US/careers/Error",
            ),
        ):
            self.assertFalse(
                _url_is_live("https://koch.avature.net/en_US/careers/JobDetail/Platform-Engineer/188227")
            )
        # A 403 IN PLACE (no error-path redirect — Indeed/WWR/Foundit style)
        # is still ambiguous and stays alive.
        with mock.patch(
            "matcha.sources.web_search.resilient_get",
            return_value=_Resp({}, status_code=403, url="https://a.com/job/1"),
        ):
            self.assertTrue(_url_is_live("https://a.com/job/1"))
        # A real job slug that merely CONTAINS "error" must not match
        # (whole-segment match only)
        with mock.patch(
            "matcha.sources.web_search.resilient_get",
            return_value=_Resp({}, status_code=200, url="https://a.com/job/error-handling-engineer"),
        ):
            self.assertTrue(_url_is_live("https://a.com/job/error-handling-engineer"))
        # Error-path redirect on a 200 is dead too (soft-404 with a redirect)
        with mock.patch(
            "matcha.sources.web_search.resilient_get",
            return_value=_Resp({}, status_code=200, url="https://a.com/en/error"),
        ):
            self.assertFalse(_url_is_live("https://a.com/en/job/1"))
        # The orig-path guard: a URL that ALREADY has a dead segment (e.g. a
        # requisition literally named "error" or Exa returning an error page
        # directly, no redirect) is NOT dropped by the redirect check.
        with mock.patch(
            "matcha.sources.web_search.resilient_get",
            return_value=_Resp({}, status_code=200, url="https://a.com/error"),
        ):
            self.assertTrue(_url_is_live("https://a.com/error"))
        # Soft-404: HTTP 200 with a "Page not found" body is a dead posting
        # (Avature/Koch returns exactly this) — the body marker catches it.
        with mock.patch(
            "matcha.sources.web_search.resilient_get",
            return_value=_Resp({}, status_code=200, text="Page not found", url="https://a.com/job/1"),
        ):
            self.assertFalse(_url_is_live("https://a.com/job/1"))
        # 200 with a normal job body is alive
        with mock.patch(
            "matcha.sources.web_search.resilient_get",
            return_value=_Resp({}, status_code=200, text="Hiring now", url="https://a.com/job/1"),
        ):
            self.assertTrue(_url_is_live("https://a.com/job/1"))
        # Network error / timeout → treat as alive (flaky network must not
        # kill a live posting)
        with mock.patch(
            "matcha.sources.web_search.resilient_get", side_effect=TimeoutError("slow")
        ):
            self.assertTrue(_url_is_live("https://a.com/job/1"))

    def test_search_exa_company_prefers_host_over_author(self):
        # Session 30: author field junk ("scale") must not become the company
        # when the posting's own host names it (Vodafone).
        from matcha.sources.web_search import _search_web_exa

        rows = [
            {
                "title": "AWS Cloud DevOps Engineer",
                "url": "https://opportunities.vodafone.com/job/Pune-aws/1395729933/",
                "text": "cloud infrastructure in Pune",
                "author": "scale",
            }
        ]
        with (
            mock.patch("matcha.sources.backends.exa.exa_search", return_value=rows),
            mock.patch("matcha.sources.web_search._url_is_live", return_value=True),
        ):
            result = _search_web_exa("AWS DevOps", "Pune", num=5)
        self.assertEqual(result.jobs[0]["company"], "Vodafone")

    def test_search_exa_drops_dead_links(self):
        # Session 30: expired ATS postings must not reach the results — the
        # probe drops 404s and redirect-to-homepage bounces.
        from matcha.sources.web_search import _search_web_exa

        rows = [
            {
                "title": "Senior DevOps Engineer - UnitedHealth",
                "url": "https://careers.unitedhealthgroup.com/job/x/96580840736",
                "text": "terraform in Bengaluru",
            },
            {
                "title": "DevOps Engineer - Acme",
                "url": "https://acme.com/jobs/3",
                "text": "aws kubernetes in Pune",
            },
        ]
        # URL-keyed side_effect: the probe runs in a parallel pool, so list
        # side_effects would be consumed in nondeterministic order.
        def probe(url):
            return "acme.com" in url

        with (
            mock.patch("matcha.sources.backends.exa.exa_search", return_value=rows),
            mock.patch("matcha.sources.web_search._url_is_live", side_effect=probe),
        ):
            result = _search_web_exa("DevOps Engineer", "Pune", num=5)
        self.assertEqual([j["title"] for j in result.jobs], ["DevOps Engineer"])

    def test_extract_location_and_source(self):
        from matcha.sources.web_search import _extract_location

        self.assertEqual(_extract_location("Engineer in Bengaluru", "u", "t"), "Bengaluru")
        self.assertEqual(_extract_location("", "u", "t"), "Remote / Unspecified")

    def test_rows_tagged_web_search_source(self):
        # Session 28: every Web Search row (Exa AND DDGS) is sourced "Web
        # Search" — the old per-row _identify_source ("Careers", "Foundit")
        # made source_counts disagree with the rows.
        from matcha.sources.web_search import _search_web_exa

        rows = [
            {
                "title": "DevOps Engineer - Acme",
                "url": "https://acme.com/jobs/3",
                "text": "in Pune",
            }
        ]
        with (
            mock.patch("matcha.sources.backends.exa.exa_search", return_value=rows),
            mock.patch("matcha.sources.web_search._url_is_live", return_value=True),
        ):
            result = _search_web_exa("DevOps Engineer", "Pune", num=5)
        self.assertEqual(result.jobs[0]["source"], "Web Search")

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
            mock.patch("matcha.sources.web_search.DDGS", lambda *a, **k: fake),
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
        with (
            mock.patch("matcha.sources.backends.exa.exa_search", return_value=rows),
            mock.patch("matcha.sources.web_search._url_is_live", return_value=True),
        ):
            result = _search_web_exa("engineer", num=5)
        self.assertEqual(len(result.jobs), 1)
        self.assertEqual(result.jobs[0]["company"], "Acme")
        self.assertEqual(result.jobs[0]["listed"], "2025-06-01")

    def test_search_exa_drops_homepages_and_unrelated(self):
        # Session 27: the Exa backend must apply the same junk gates as DDGS
        # — homepages and irrelevant postings leak through semantic search.
        from matcha.sources.web_search import _search_web_exa

        rows = [
            {
                "title": "Lever",
                "url": "https://www.lever.co/?lang=fa",
                "text": "",
            },
            {
                "title": "Halton Healthcare Intake Assistant",
                "url": "https://jobs.smartrecruiters.com/HaltonHealthcare1/3743",
                "text": "caregiving",
            },
            {
                "title": "DevOps Engineer - Acme",
                "url": "https://acme.com/jobs/3",
                "text": "aws kubernetes",
            },
        ]
        with (
            mock.patch("matcha.sources.backends.exa.exa_search", return_value=rows),
            mock.patch("matcha.sources.web_search._url_is_live", return_value=True),
        ):
            result = _search_web_exa("DevOps Engineer", "Pune", num=5)
        self.assertEqual([j["title"] for j in result.jobs], ["DevOps Engineer"])

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
        with (
            mock.patch("matcha.sources.backends.exa.exa_search", return_value=rows),
            mock.patch("matcha.sources.web_search._url_is_live", return_value=True),
        ):
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
            mock.patch("matcha.sources.web_search.DDGS", lambda *a, **k: fake),
            mock.patch("matcha.sources.web_search.limiter.acquire"),
        ):
            result = _search_web_ddgs("engineer")
        self.assertEqual([j["title"] for j in result.jobs], ["Engineer"])

    def test_search_ddgs_drops_homepage_urls(self):
        # Session 27: ``site:lever.co`` returns the company homepage as a job.
        from matcha.sources.web_search import _search_web_ddgs

        fake = _FakeDDGS(
            rows=[
                {"title": "Lever", "href": "https://www.lever.co/?lang=fa", "body": ""},
                {"title": "Engineer - Acme", "href": "https://acme.com/job/2", "body": "in Pune"},
            ]
        )
        with (
            mock.patch("matcha.sources.web_search.DDGS", lambda *a, **k: fake),
            mock.patch("matcha.sources.web_search.limiter.acquire"),
        ):
            result = _search_web_ddgs("engineer")
        self.assertEqual([j["title"] for j in result.jobs], ["Engineer"])

    def test_search_ddgs_drops_howto_articles(self):
        # Session 27: tutorial articles ("How to Become a DevOps Engineer:
        # Skills & Career" from a course marketplace) are not postings.
        from matcha.sources.web_search import _search_web_ddgs

        fake = _FakeDDGS(
            rows=[
                {
                    "title": "How to Become a DevOps Engineer: Skills & Career",
                    "href": "https://www.simplilearn.com/how-to-become-devops-engineer",
                    "body": "learn devops",
                },
                {
                    "title": "Engineer - Acme",
                    "href": "https://acme.com/job/4",
                    "body": "in Pune",
                },
            ]
        )
        with (
            mock.patch("matcha.sources.web_search.DDGS", lambda *a, **k: fake),
            mock.patch("matcha.sources.web_search.limiter.acquire"),
        ):
            result = _search_web_ddgs("DevOps Engineer", "Pune")
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
            # backend override keeps this hermetic: the machine's OpenCLI
            # consent would otherwise route to the browser bridge.
            result = search_linkedin_jobs("engineer", backend="guest-api")
        self.assertEqual(result.backend, "guest-api")


if __name__ == "__main__":
    unittest.main()
