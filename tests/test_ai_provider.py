import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import unittest
from unittest import mock


class TestAIProviderFunctions(unittest.TestCase):
    def test_check_ai_available_returns_false_when_missing(self):
        from ai import check_ai_available

        with (
            mock.patch("ai._get_api_key", return_value=""),
            mock.patch("ai._get_api_url", return_value=""),
            mock.patch("ai._get_model", return_value=""),
        ):
            self.assertFalse(check_ai_available())

    def test_check_ai_available_returns_true_when_all_set(self):
        from ai import check_ai_available

        with (
            mock.patch("ai._get_api_key", return_value="key"),
            mock.patch("ai._get_api_url", return_value="url"),
            mock.patch("ai._get_model", return_value="model"),
        ):
            self.assertTrue(check_ai_available())

    @mock.patch.dict(
        os.environ,
        {"MINIMAX": "env-key", "AI_API_URL": "https://env.test/v1", "AI_MODEL": "env-model"},
    )
    def test_env_vars_override_config(self):
        from ai import _get_api_key, _get_api_url, _get_model

        self.assertEqual(_get_api_key(), "env-key")
        self.assertEqual(_get_api_url(), "https://env.test/v1")
        self.assertEqual(_get_model(), "env-model")

    @mock.patch.dict(os.environ, {}, clear=True)
    def test_fallback_to_config(self):
        with mock.patch("ai.load_config") as mock_load:
            mock_load.return_value = {
                "ai_key": "config-key",
                "ai_url": "https://config.test/v1",
                "ai_model": "config-model",
            }
            from ai import _get_api_key, _get_api_url, _get_model

            self.assertEqual(_get_api_key(), "config-key")
            self.assertEqual(_get_api_url(), "https://config.test/v1")
            self.assertEqual(_get_model(), "config-model")


class TestAIEmptyContent(unittest.TestCase):
    @mock.patch("ai._call_ai", return_value=None)
    @mock.patch("ai.check_ai_available", return_value=True)
    def test_ai_score_job_handles_none(self, mock_check, mock_call):
        from ai import ai_score_job

        result = ai_score_job(
            {"title": "Engineer", "skills": ["aws"]},
            {
                "title": "Platform Engineer",
                "company": "Co",
                "description": "test",
                "location": "Remote",
            },
        )
        self.assertIsNone(result)

    @mock.patch("ai._call_ai", return_value=None)
    @mock.patch("ai.check_ai_available", return_value=True)
    def test_ai_extract_profile_handles_none(self, mock_check, mock_call):
        from ai import ai_extract_profile

        result = ai_extract_profile("some resume text")
        self.assertIsNone(result)

    @mock.patch("ai._call_ai", return_value=None)
    @mock.patch("ai.check_ai_available", return_value=True)
    def test_ai_generate_queries_handles_none(self, mock_check, mock_call):
        from ai import ai_generate_queries

        result = ai_generate_queries({"title": "Engineer", "skills": ["aws"]})
        self.assertIsNone(result)


class TestMaxTokens(unittest.TestCase):
    def test_scoring_uses_16384(self):
        from ai import ai_score_job

        profile = {
            "title": "E",
            "headline": "E",
            "skills": ["aws"],
            "experience": "5",
            "summary": "x",
            "location": "Remote",
        }
        job = {
            "title": "Platform Engineer",
            "company": "Co",
            "description": "test",
            "location": "Remote",
        }
        with mock.patch(
            "ai._call_ai", return_value='{"score": 80, "reasons": ["ok"]}'
        ) as mock_call:
            with mock.patch("ai.check_ai_available", return_value=True):
                ai_score_job(profile, job)
                self.assertEqual(mock_call.call_args.kwargs["max_tokens"], 16384)

    def test_generate_queries_uses_8192(self):
        from ai import ai_generate_queries

        with mock.patch("ai._call_ai", return_value='{"queries": ["python backend"]}') as mock_call:
            with mock.patch("ai.check_ai_available", return_value=True):
                ai_generate_queries({"title": "Dev", "skills": ["Python"], "summary": "x", "location": "Remote"})
                self.assertEqual(mock_call.call_args.kwargs["max_tokens"], 8192)

    def test_suggest_titles_uses_4096(self):
        from ai import ai_suggest_titles

        with mock.patch("ai._call_ai", return_value='{"titles": ["DevOps Engineer"]}') as mock_call:
            with mock.patch("ai.check_ai_available", return_value=True):
                ai_suggest_titles(["aws", "docker"])
                self.assertEqual(mock_call.call_args.kwargs["max_tokens"], 4096)

    def test_extract_profile_uses_16384(self):
        from ai import ai_extract_profile

        with mock.patch("ai._call_ai", return_value='{"name": "Test", "skills": []}') as mock_call:
            with mock.patch("ai.check_ai_available", return_value=True):
                ai_extract_profile("resume text")
                self.assertEqual(mock_call.call_args.kwargs["max_tokens"], 16384)


if __name__ == "__main__":
    unittest.main()
