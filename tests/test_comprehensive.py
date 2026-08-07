import os
import sys
import unittest
from unittest import mock

import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


class TestAICallRetry(unittest.TestCase):
    """Test the _call_ai retry logic for ConnectionError, Timeout, and non-200."""

    @mock.patch("matcha.ai._get_api_key", return_value="key")
    @mock.patch("matcha.ai._get_api_url", return_value="https://test.ai/v1")
    @mock.patch("matcha.ai._get_model", return_value="model")
    @mock.patch("matcha.ai.requests.post")
    def test_connection_error_retries_then_none(self, mock_post, *_):
        mock_post.side_effect = [
            requests.ConnectionError("DNS failure"),
            requests.ConnectionError("DNS failure again"),
        ]
        from matcha.ai import _call_ai

        result = _call_ai([{"role": "user", "content": "hi"}])
        self.assertIsNone(result)
        self.assertEqual(mock_post.call_count, 2)

    @mock.patch("matcha.ai._get_api_key", return_value="key")
    @mock.patch("matcha.ai._get_api_url", return_value="https://test.ai/v1")
    @mock.patch("matcha.ai._get_model", return_value="model")
    @mock.patch("matcha.ai.requests.post")
    def test_timeout_retries_then_none(self, mock_post, *_):
        mock_post.side_effect = [requests.Timeout, requests.Timeout]
        from matcha.ai import _call_ai

        result = _call_ai([{"role": "user", "content": "hi"}])
        self.assertIsNone(result)

    @mock.patch("matcha.ai._get_api_key", return_value="key")
    @mock.patch("matcha.ai._get_api_url", return_value="https://test.ai/v1")
    @mock.patch("matcha.ai._get_model", return_value="model")
    @mock.patch("matcha.ai.requests.post")
    def test_connection_error_recovers(self, mock_post, *_):
        mock_response = mock.MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"choices": [{"message": {"content": "hello"}}]}
        mock_post.side_effect = [requests.ConnectionError("DNS failure"), mock_response]
        from matcha.ai import _call_ai

        result = _call_ai([{"role": "user", "content": "hi"}])
        self.assertEqual(result, "hello")

    @mock.patch("matcha.ai._get_api_key", return_value="key")
    @mock.patch("matcha.ai._get_api_url", return_value="https://test.ai/v1")
    @mock.patch("matcha.ai._get_model", return_value="model")
    @mock.patch("matcha.ai.requests.post")
    def test_non_200_retries_then_none(self, mock_post, *_):
        resp_429 = mock.MagicMock()
        resp_429.status_code = 429
        resp_502 = mock.MagicMock()
        resp_502.status_code = 502
        mock_post.side_effect = [resp_429, resp_502]
        from matcha.ai import _call_ai

        result = _call_ai([{"role": "user", "content": "hi"}])
        self.assertIsNone(result)
        self.assertEqual(mock_post.call_count, 2)

    @mock.patch("matcha.ai._get_api_key", return_value="key")
    @mock.patch("matcha.ai._get_api_url", return_value="https://test.ai/v1")
    @mock.patch("matcha.ai._get_model", return_value="model")
    @mock.patch("matcha.ai.requests.post")
    def test_non_200_then_recovers(self, mock_post, *_):
        resp_429 = mock.MagicMock()
        resp_429.status_code = 429
        resp_ok = mock.MagicMock()
        resp_ok.status_code = 200
        resp_ok.json.return_value = {"choices": [{"message": {"content": "recovered"}}]}
        mock_post.side_effect = [resp_429, resp_ok]
        from matcha.ai import _call_ai

        result = _call_ai([{"role": "user", "content": "hi"}])
        self.assertEqual(result, "recovered")

    @mock.patch("matcha.ai._get_api_key", return_value="key")
    @mock.patch("matcha.ai._get_api_url", return_value="https://test.ai/v1")
    @mock.patch("matcha.ai._get_model", return_value="model")
    @mock.patch("matcha.ai.requests.post")
    def test_requests_exception_no_retry(self, mock_post, *_):
        mock_post.side_effect = requests.RequestException("API error")
        from matcha.ai import _call_ai

        result = _call_ai([{"role": "user", "content": "hi"}])
        self.assertIsNone(result)
        self.assertEqual(mock_post.call_count, 1)

    @mock.patch("matcha.ai._get_api_key", return_value="key")
    @mock.patch("matcha.ai._get_api_url", return_value="https://test.ai/v1")
    @mock.patch("matcha.ai._get_model", return_value="model")
    @mock.patch("matcha.ai.requests.post")
    def test_missing_key_returns_none(self, mock_post, *_):
        from matcha.ai import _call_ai

        with mock.patch("matcha.ai._get_api_key", return_value=""):
            result = _call_ai([{"role": "user", "content": "hi"}])
        self.assertIsNone(result)
        mock_post.assert_not_called()


class TestComputeRelevanceEdgeCases(unittest.TestCase):
    """Test matcher.compute_relevance with edge case inputs."""

    def setUp(self):
        self.profile = {
            "title": "Platform Engineer",
            "headline": "DevOps Engineer",
            "skills": ["aws", "docker", "kubernetes", "terraform", "ci/cd", "linux"],
            "experience": "4",
            "summary": "Cloud engineer",
            "location": "Pune",
        }

    def test_empty_profile_skills(self):
        """Empty skills list should not cause division by zero."""
        profile = {k: v for k, v in self.profile.items()}
        profile["skills"] = []
        job = {
            "title": "Platform Engineer",
            "description": "some work",
            "location": "Pune",
        }
        from matcha.matcher import compute_relevance

        result = compute_relevance(job, profile)
        self.assertIsInstance(result["score"], (int, float))
        self.assertGreaterEqual(result["score"], 0)

    def test_empty_job_title(self):
        """Empty job title should not crash."""
        job = {
            "title": "",
            "description": "aws docker kubernetes terraform",
            "location": "Pune",
        }
        from matcha.matcher import compute_relevance

        result = compute_relevance(job, self.profile)
        self.assertIsInstance(result["score"], (int, float))

    def test_missing_job_fields(self):
        """Minimal job dict should not crash."""
        from matcha.matcher import compute_relevance

        result = compute_relevance({}, self.profile)
        self.assertIsInstance(result["score"], (int, float))

    def test_negative_experience(self):
        """Negative experience string should not cause issues."""
        profile = dict(self.profile)
        profile["experience"] = "-5"
        job = {"title": "Intern", "description": "", "location": ""}
        from matcha.matcher import compute_relevance

        result = compute_relevance(job, profile)
        self.assertIsInstance(result["score"], (int, float))

    def test_very_high_experience(self):
        """Very high experience should return staff level."""
        profile = dict(self.profile)
        profile["experience"] = "20"
        job = {
            "title": "Junior Engineer",
            "description": "",
            "location": "Remote",
        }
        from matcha.matcher import compute_relevance

        result = compute_relevance(job, profile)
        self.assertIsInstance(result["score"], (int, float))

    def test_skill_word_boundary_no_false_positive(self):
        """'aws' in 'claws' or 'paws' should NOT match via word boundary."""
        profile = dict(self.profile)
        profile["skills"] = ["aws"]
        job = {
            "title": "Claw Sharpener",
            "description": "sharpening claws for animals",
            "location": "",
        }
        from matcha.matcher import compute_relevance

        result = compute_relevance(job, profile)
        self.assertNotIn("Skills:", "; ".join(result["reasons"]))

    def test_skill_word_boundary_positive(self):
        """'aws' standalone in title should match."""
        profile = dict(self.profile)
        profile["skills"] = ["aws"]
        job = {
            "title": "AWS Engineer",
            "description": "work with aws services",
            "location": "Remote",
        }
        from matcha.matcher import compute_relevance

        result = compute_relevance(job, profile)
        combined = "; ".join(result["reasons"])
        self.assertIn("aws", combined)

    def test_reasons_capped_at_8(self):
        """Reasons list should be capped at 8 items."""
        profile = dict(self.profile)
        profile["skills"] = [
            "aws",
            "docker",
            "kubernetes",
            "terraform",
            "ci/cd",
            "linux",
            "python",
            "ansible",
            "prometheus",
            "grafana",
        ]
        job = {
            "title": "Senior Platform Engineer",
            "description": (
                "aws docker kubernetes terraform ci/cd linux python ansible prometheus grafana"
            ),
            "location": "Pune, India",
        }
        from matcha.matcher import compute_relevance

        result = compute_relevance(job, self.profile)
        self.assertLessEqual(len(result["reasons"]), 8)

    def test_score_floor_at_5(self):
        """Minimum score should be 5.0."""
        profile = {
            "title": "A",
            "headline": "",
            "skills": [],
            "experience": "",
            "summary": "",
            "location": "",
        }
        job = {"title": "B", "description": "", "location": ""}
        from matcha.matcher import compute_relevance

        result = compute_relevance(job, profile)
        self.assertGreaterEqual(result["score"], 5.0)

    def test_score_ceiling_at_100(self):
        """Maximum score should be capped at 100."""
        profile = {
            "title": "Platform Engineer",
            "headline": "Platform Engineer",
            "skills": ["aws", "docker"],
            "experience": "4",
            "summary": "",
            "location": "Pune",
        }
        job = {
            "title": "Platform Engineer",
            "description": "aws docker",
            "location": "Pune",
        }
        from matcha.matcher import compute_relevance

        result = compute_relevance(job, profile)
        self.assertLessEqual(result["score"], 100.0)


class TestScraperResult(unittest.TestCase):
    """Test ScraperResult dataclass behavior."""

    def test_default_construction(self):
        from matcha.models import ScraperResult

        r = ScraperResult()
        self.assertEqual(r.jobs, [])
        self.assertEqual(r.errors, [])
        self.assertEqual(r.source, "")

    def test_with_jobs(self):
        from matcha.models import ScraperResult

        r = ScraperResult(jobs=[{"title": "Engineer"}], source="Indeed")
        self.assertEqual(len(r.jobs), 1)
        self.assertEqual(r.source, "Indeed")

    def test_with_errors(self):
        from matcha.models import ScraperResult

        r = ScraperResult(errors=["timeout"], source="LinkedIn")
        self.assertEqual(len(r.errors), 1)


class TestConfigValidation(unittest.TestCase):
    """Test ConfigSchema and Settings models."""

    def test_config_schema_defaults(self):
        from matcha.models import ConfigSchema

        c = ConfigSchema()
        self.assertEqual(c.ai_key, "")
        self.assertEqual(c.last_days, 7)

    def test_settings_defaults(self):
        from matcha.models import Settings

        s = Settings()
        self.assertEqual(s.search.max_pages, 2)
        self.assertEqual(s.ai.top_n, 30)
        self.assertEqual(s.ai.timeout, 60)
        self.assertEqual(s.scrapers.indeed_domain, "in.indeed.com")

    def test_settings_override(self):
        from matcha.models import Settings

        s = Settings(
            **{
                "search": {"max_pages": 5},
                "ai": {"top_n": 10, "timeout": 120},
                "scrapers": {"indeed_domain": "ca.indeed.com"},
            }
        )
        self.assertEqual(s.search.max_pages, 5)
        self.assertEqual(s.ai.top_n, 10)
        self.assertEqual(s.ai.timeout, 120)
        self.assertEqual(s.scrapers.indeed_domain, "ca.indeed.com")


class TestDeduplicateEdgeCases(unittest.TestCase):
    """Test main.deduplicate with edge case inputs."""

    def test_empty_list(self):
        from matcha.main import deduplicate

        self.assertEqual(deduplicate([]), [])

    def test_single_job(self):
        from matcha.main import deduplicate

        result = deduplicate([{"title": "Engineer", "company": "Co"}])
        self.assertEqual(len(result), 1)

    def test_no_title_or_company(self):
        from matcha.main import deduplicate

        jobs = [
            {"title": "", "company": ""},
            {"title": "", "company": ""},
        ]
        self.assertEqual(len(deduplicate(jobs)), 1)

    def test_special_characters(self):
        from matcha.main import deduplicate

        jobs = [
            {"title": "C++ Engineer", "company": "Meta✶"},
            {"title": "C++ Engineer", "company": "Meta✶"},
        ]
        self.assertEqual(len(deduplicate(jobs)), 1)

    def test_unicode_normalization(self):
        from matcha.main import deduplicate

        jobs = [
            {"title": "DevOps Engineer", "company": "Caf\u00e9 Corp"},
            {"title": "DevOps Engineer", "company": "Caf\u00e9 Corp"},
        ]
        self.assertEqual(len(deduplicate(jobs)), 1)


class TestTokenBucket(unittest.TestCase):
    """Test RateLimiter/TokenBucket behavior."""

    def test_initial_state(self):
        from matcha.sources.utils import TokenBucket

        tb = TokenBucket(60)
        self.assertEqual(tb.tokens, 60.0)
        self.assertEqual(tb.max_tokens, 60)

    def test_acquire_no_wait_with_tokens(self):
        from matcha.sources.utils import RateLimiter

        rl = RateLimiter()
        rl.set_rate("test.example.com", 100)
        import time

        start = time.monotonic()
        rl.acquire("test.example.com")
        elapsed = time.monotonic() - start
        self.assertLess(elapsed, 1.0)

    def test_domain_isolation(self):
        """Acquiring from one domain should not affect another."""
        from matcha.sources.utils import RateLimiter

        rl = RateLimiter()
        rl.set_rate("slow.example.com", 2)
        rl.set_rate("fast.example.com", 100)
        rl.acquire("slow.example.com")
        rl.acquire("slow.example.com")
        import time

        start = time.monotonic()
        rl.acquire("fast.example.com")
        elapsed = time.monotonic() - start
        self.assertLess(elapsed, 0.5, "Fast domain should not wait for slow domain")

    def test_unlimited_domain_no_wait(self):
        """Domains without a rate set should not block."""
        import time

        from matcha.sources.utils import RateLimiter

        rl = RateLimiter()
        start = time.monotonic()
        rl.acquire("unknown.example.com")
        elapsed = time.monotonic() - start
        self.assertLess(elapsed, 0.1)


class TestSearchJobsScraperKwargs(unittest.TestCase):
    """Test that scraper_kwargs correctly passes domain to Indeed."""

    def test_indeed_domain_present_in_kwargs(self):
        """Verify Indeed domain kwarg is set correctly."""
        from matcha.main import search_jobs

        scrapers = {"Indeed": mock.MagicMock()}

        fake_future = mock.MagicMock()
        fake_future.result.return_value = (
            "Indeed",
            mock.MagicMock(jobs=[], errors=[], source="Indeed"),
        )

        fake_executor = mock.MagicMock()
        fake_executor.submit.return_value = fake_future
        fake_executor.__enter__.return_value = fake_executor

        with (
            mock.patch("matcha.main.SCRAPER_DEFS", scrapers),
            mock.patch("matcha.main.check_serpapi_available", return_value=False),
            mock.patch("matcha.main.deduplicate", side_effect=lambda x: x),
            mock.patch("matcha.main.ThreadPoolExecutor", return_value=fake_executor),
            mock.patch("matcha.main.Live"),
            mock.patch("matcha.main.as_completed", return_value=[fake_future]),
            # Hermetic: never consult the real ~/.matcha/source_state.json — an
            # open circuit for a source would silently empty ``scrapers`` and
            # break this kwargs-assertion (live-run state is not test input).
            mock.patch("matcha.main.breaker_is_open", return_value=False),
        ):
            search_jobs(
                queries=["Engineer"],
                location="Pune",
                days=7,
                max_pages=1,
                indeed_domain="ca.indeed.com",
            )

        self.assertTrue(fake_executor.submit.called)
        call_kwargs = fake_executor.submit.call_args
        self.assertIsNotNone(call_kwargs)
        _, kwargs = call_kwargs
        self.assertIn("domain", kwargs)
        self.assertEqual(kwargs["domain"], "ca.indeed.com")


if __name__ == "__main__":
    unittest.main()
