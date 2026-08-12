import os
import sys
import time
import unittest
from datetime import datetime, timedelta
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from matcha.sources.indeed import search_indeed_jobs
from matcha.sources.naukri import search_naukri_jobs
from matcha.sources.remoteok import search_remoteok_jobs
from matcha.sources.serpapi_jobs import search_serpapi_jobs
from matcha.sources.web_search import _is_older_than_days, search_web_for_jobs


class TestIndeedDaysFilter(unittest.TestCase):
    @mock.patch("matcha.sources.indeed._fetch_indeed_page")
    def test_fromage_passed_when_days_given(self, mock_fetch):
        mock_fetch.return_value.status_code = 200
        mock_fetch.return_value.text = "<html></html>"
        # backend="html" keeps this hermetic: the consented OpenCLI route
        # (machine state) would never touch _fetch_indeed_page.
        search_indeed_jobs("platform engineer", "pune", days=3, backend="html")
        args, kwargs = mock_fetch.call_args
        self.assertEqual(args[1].get("fromage"), "3")

    @mock.patch("matcha.sources.indeed._fetch_indeed_page")
    def test_fromage_omitted_when_no_days(self, mock_fetch):
        mock_fetch.return_value.status_code = 200
        mock_fetch.return_value.text = "<html></html>"
        search_indeed_jobs("platform engineer", "pune", backend="html")
        args, kwargs = mock_fetch.call_args
        self.assertNotIn("fromage", args[1])


class TestSerpapiDaysFilter(unittest.TestCase):
    @mock.patch("matcha.sources.serpapi_jobs.resilient_get")
    @mock.patch("matcha.sources.serpapi_jobs.get_serpapi_config")
    def test_date_posted_today(self, mock_config, mock_get):
        mock_config.return_value = {"serpapi_key": "test-key"}
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {"jobs_results": []}
        search_serpapi_jobs("platform engineer", days=1)
        self.assertEqual(mock_get.call_args[1]["params"]["date_posted"], "today")

    @mock.patch("matcha.sources.serpapi_jobs.resilient_get")
    @mock.patch("matcha.sources.serpapi_jobs.get_serpapi_config")
    def test_date_posted_3days(self, mock_config, mock_get):
        mock_config.return_value = {"serpapi_key": "test-key"}
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {"jobs_results": []}
        search_serpapi_jobs("platform engineer", days=3)
        self.assertEqual(mock_get.call_args[1]["params"]["date_posted"], "3days")

    @mock.patch("matcha.sources.serpapi_jobs.resilient_get")
    @mock.patch("matcha.sources.serpapi_jobs.get_serpapi_config")
    def test_date_posted_week(self, mock_config, mock_get):
        mock_config.return_value = {"serpapi_key": "test-key"}
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {"jobs_results": []}
        search_serpapi_jobs("platform engineer", days=7)
        self.assertEqual(mock_get.call_args[1]["params"]["date_posted"], "week")

    @mock.patch("matcha.sources.serpapi_jobs.resilient_get")
    @mock.patch("matcha.sources.serpapi_jobs.get_serpapi_config")
    def test_date_posted_month_default(self, mock_config, mock_get):
        mock_config.return_value = {"serpapi_key": "test-key"}
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {"jobs_results": []}
        search_serpapi_jobs("platform engineer")
        self.assertEqual(mock_get.call_args[1]["params"]["date_posted"], "week")

    @mock.patch("matcha.sources.serpapi_jobs.resilient_get")
    @mock.patch("matcha.sources.serpapi_jobs.get_serpapi_config")
    def test_date_posted_month_for_large_days(self, mock_config, mock_get):
        mock_config.return_value = {"serpapi_key": "test-key"}
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {"jobs_results": []}
        search_serpapi_jobs("platform engineer", days=14)
        self.assertEqual(mock_get.call_args[1]["params"]["date_posted"], "month")


class TestRemoteokDaysFilter(unittest.TestCase):
    @mock.patch("matcha.sources.remoteok.resilient_get")
    def test_filters_old_jobs(self, mock_get):
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = [
            {},
            {"position": "Platform Engineer", "company": "Co", "epoch": time.time() - 10},
            {"position": "Old Job", "company": "Co2", "epoch": time.time() - 86400 * 10},
        ]
        result = search_remoteok_jobs("platform", days=7)
        self.assertEqual(len(result.jobs), 1)

    @mock.patch("matcha.sources.remoteok.resilient_get")
    def test_no_cutoff_when_no_days(self, mock_get):
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = [
            {},
            {"position": "Platform Engineer", "company": "Co", "epoch": time.time() - 86400 * 30},
        ]
        result = search_remoteok_jobs("platform")
        self.assertEqual(len(result.jobs), 1)


class TestWebSearchDaysFilter(unittest.TestCase):
    @mock.patch("matcha.sources.web_search.limiter.acquire")
    @mock.patch("matcha.sources.web_search.DDGS")
    @mock.patch("matcha.sources.web_search._exa_should_run", return_value=False)
    def test_timelimit_passed(self, mock_exa, mock_ddgs, mock_acquire):
        mock_instance = mock.MagicMock()
        mock_ddgs.return_value.__enter__.return_value = mock_instance
        mock_instance.text.return_value = []
        search_web_for_jobs("platform engineer", days=3)
        for call in mock_instance.text.call_args_list:
            self.assertIn("timelimit", call[1])

    @mock.patch("matcha.sources.web_search.limiter.acquire")
    @mock.patch("matcha.sources.web_search.DDGS")
    @mock.patch("matcha.sources.web_search._exa_should_run", return_value=False)
    def test_no_linkedin_queries(self, mock_exa, mock_ddgs, mock_acquire):
        mock_instance = mock.MagicMock()
        mock_ddgs.return_value.__enter__.return_value = mock_instance
        mock_instance.text.return_value = []
        search_web_for_jobs("platform engineer")
        for call in mock_instance.text.call_args_list:
            q = call[0][0]
            self.assertNotIn("linkedin.com", q, f"Web Search should not query LinkedIn: {q}")

    @mock.patch("matcha.sources.web_search.limiter.acquire")
    @mock.patch("matcha.sources.web_search.DDGS")
    @mock.patch("matcha.sources.web_search._exa_should_run", return_value=False)
    def test_no_timelimit_without_days(self, mock_exa, mock_ddgs, mock_acquire):
        mock_instance = mock.MagicMock()
        mock_ddgs.return_value.__enter__.return_value = mock_instance
        mock_instance.text.return_value = []
        search_web_for_jobs("platform engineer")
        for call in mock_instance.text.call_args_list:
            self.assertNotIn("timelimit", call[1])


class TestNaukriDaysFilter(unittest.TestCase):
    @mock.patch("matcha.sources.naukri.limiter.acquire")
    @mock.patch("matcha.sources.naukri.DDGS")
    def test_timelimit_passed(self, mock_ddgs, mock_acquire):
        mock_instance = mock.MagicMock()
        mock_ddgs.return_value.__enter__.return_value = mock_instance
        mock_instance.text.return_value = []
        search_naukri_jobs("platform engineer", days=7)
        for call in mock_instance.text.call_args_list:
            self.assertIn("timelimit", call[1])

    @mock.patch("matcha.sources.naukri.limiter.acquire")
    @mock.patch("matcha.sources.naukri.DDGS")
    def test_no_timelimit_without_days(self, mock_ddgs, mock_acquire):
        mock_instance = mock.MagicMock()
        mock_ddgs.return_value.__enter__.return_value = mock_instance
        mock_instance.text.return_value = []
        search_naukri_jobs("platform engineer")
        for call in mock_instance.text.call_args_list:
            self.assertNotIn("timelimit", call[1])


class TestWebSearchSnippetAgeFilter(unittest.TestCase):
    def test_x_years_ago_exceeds_days(self):
        self.assertTrue(_is_older_than_days("Posted 2 years ago", 7))

    def test_x_years_ago_within_days(self):
        self.assertFalse(_is_older_than_days("Posted 0 years ago", 365))

    def test_x_months_ago_exceeds(self):
        self.assertTrue(_is_older_than_days("2 months ago", 30))

    def test_x_months_ago_within(self):
        self.assertFalse(_is_older_than_days("1 month ago", 31))

    def test_x_weeks_ago_exceeds(self):
        self.assertTrue(_is_older_than_days("3 weeks ago", 14))

    def test_x_days_ago_exceeds(self):
        self.assertTrue(_is_older_than_days("10 days ago", 3))

    def test_x_days_ago_within(self):
        self.assertFalse(_is_older_than_days("2 days ago", 7))

    def test_date_string_exceeds(self):
        self.assertTrue(_is_older_than_days("Posted: January 1, 2024", 7))

    def test_date_string_within(self):
        # F-09: dates must be relative to now — the old fixed "June 6, 2026"
        # fixture failed on any run after mid-June 2026 (it fails now).
        past = datetime.now() - timedelta(days=2)
        posted = f"Posted: {past.strftime('%B')} {past.day}, {past.year}"
        self.assertFalse(_is_older_than_days(posted, 7))

    def test_date_string_relative_exceeds(self):
        past = datetime.now() - timedelta(days=30)
        posted = f"Posted: {past.strftime('%B')} {past.day}, {past.year}"
        self.assertTrue(_is_older_than_days(posted, 7))

    def test_no_date_info_returns_false(self):
        self.assertFalse(_is_older_than_days("No date information in this snippet", 7))

    def test_large_days_does_not_filter(self):
        self.assertFalse(_is_older_than_days("Posted 2 years ago", 9999))


if __name__ == "__main__":
    unittest.main()
