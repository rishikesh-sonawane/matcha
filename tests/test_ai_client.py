"""Hermetic tests for the Phase 5 provider-agnostic AI client (strategy §10.2).

Covers provider presets, model tiering, local (no-key) providers, the budget
guard, the opt-in disk cache, URL normalization, and the provider wizard
config helper. No network, no real config — everything is mocked or pointed
at temp files via ``MATCHA_AI_CACHE``.
"""

import os
import sys
import tempfile
import unittest
from contextlib import ExitStack
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


class TestProviderPresets(unittest.TestCase):
    def setUp(self):
        from matcha.ai import reset_budget

        reset_budget(0)  # unlimited — clean slate per test

    def tearDown(self):
        from matcha.ai import reset_budget

        reset_budget(0)

    def _preset_env(self, provider: str) -> ExitStack:
        stack = ExitStack()
        stack.enter_context(
            mock.patch("matcha.ai.load_config", return_value={"ai_provider": provider})
        )
        stack.enter_context(mock.patch.dict(os.environ, {}, clear=True))
        return stack

    def test_groq_preset_url_and_models(self):
        from matcha.ai import _get_api_url, _get_model

        with self._preset_env("groq"):
            self.assertEqual(_get_api_url(), "https://api.groq.com/openai/v1")
            self.assertEqual(_get_model("best"), "openai/gpt-oss-120b")
            self.assertEqual(_get_model("fast"), "openai/gpt-oss-20b")

    def test_kilo_preset_url_and_models(self):
        from matcha.ai import _get_api_url, _get_model

        with self._preset_env("kilo"):
            self.assertEqual(_get_api_url(), "https://api.kilo.ai/api/gateway")
            self.assertEqual(_get_model("best"), "kilo-auto/small")
            self.assertEqual(_get_model("fast"), "kilo-auto/small")

    def test_local_preset_has_no_default_model(self):
        from matcha.ai import _get_api_url, _get_model

        with self._preset_env("local"):
            self.assertEqual(_get_api_url(), "http://localhost:11434/v1")
            self.assertEqual(_get_model("best"), "")
            self.assertEqual(_get_model("fast"), "")

    def test_explicit_config_overrides_preset(self):
        from matcha.ai import _get_api_url, _get_model

        with (
            mock.patch(
                "matcha.ai.load_config",
                return_value={
                    "ai_provider": "groq",
                    "ai_url": "https://custom.example/v1",
                    "ai_model": "custom-model",
                },
            ),
            mock.patch.dict(os.environ, {}, clear=True),
        ):
            self.assertEqual(_get_api_url(), "https://custom.example/v1")
            self.assertEqual(_get_model("best"), "custom-model")

    def test_no_provider_no_config_returns_empty(self):
        from matcha.ai import _get_api_url, _get_model

        with (
            mock.patch("matcha.ai.load_config", return_value={}),
            mock.patch.dict(os.environ, {}, clear=True),
        ):
            self.assertEqual(_get_api_url(), "")
            self.assertEqual(_get_model("best"), "")

    def test_normalize_chat_url(self):
        from matcha.ai import _normalize_chat_url

        self.assertEqual(
            _normalize_chat_url("https://api.groq.com/openai/v1"),
            "https://api.groq.com/openai/v1/chat/completions",
        )
        self.assertEqual(
            _normalize_chat_url("https://api.kilo.ai/api/gateway/chat/completions"),
            "https://api.kilo.ai/api/gateway/chat/completions",
        )
        self.assertEqual(_normalize_chat_url(""), "")
        self.assertEqual(
            _normalize_chat_url("https://x.ai/v1/"), "https://x.ai/v1/chat/completions"
        )


class TestModelTiers(unittest.TestCase):
    def test_fast_env_override_wins(self):
        from matcha.ai import _get_model

        with (
            mock.patch.dict(os.environ, {"AI_MODEL_FAST": "cheap-model"}),
            mock.patch("matcha.ai.load_config", return_value={"ai_provider": "groq"}),
        ):
            self.assertEqual(_get_model("fast"), "cheap-model")

    def test_fast_settings_override_wins(self):
        from matcha.ai import _get_model

        with (
            mock.patch.dict(os.environ, {}, clear=True),
            mock.patch("matcha.ai.load_config", return_value={"ai_provider": "groq"}),
            mock.patch("matcha.ai._ai_settings", return_value={"ai": {"model_fast": "yaml-fast"}}),
        ):
            self.assertEqual(_get_model("fast"), "yaml-fast")

    def test_fast_falls_back_to_best_when_no_fast_default(self):
        from matcha.ai import _get_model

        with (
            mock.patch.dict(os.environ, {}, clear=True),
            mock.patch("matcha.ai.load_config", return_value={"ai_provider": "local"}),
            mock.patch("matcha.ai._ai_settings", return_value={"ai": {"model_best": "llama3"}}),
        ):
            # local has no fast preset default → reuses the best model
            self.assertEqual(_get_model("fast"), "llama3")

    def test_best_env_override_wins(self):
        from matcha.ai import _get_model

        with (
            mock.patch.dict(os.environ, {"AI_MODEL": "env-best"}),
            mock.patch("matcha.ai.load_config", return_value={"ai_provider": "openrouter"}),
        ):
            self.assertEqual(_get_model("best"), "env-best")


class TestAvailability(unittest.TestCase):
    def test_local_provider_needs_no_key(self):
        from matcha.ai import check_ai_available

        with (
            mock.patch("matcha.ai._get_provider", return_value="local"),
            mock.patch("matcha.ai._get_api_key", return_value=""),
            mock.patch("matcha.ai._get_api_url", return_value="http://localhost:11434/v1"),
            mock.patch("matcha.ai._get_model", return_value="llama3"),
        ):
            self.assertTrue(check_ai_available())

    def test_local_provider_without_model_unavailable(self):
        from matcha.ai import check_ai_available

        with (
            mock.patch("matcha.ai._get_provider", return_value="local"),
            mock.patch("matcha.ai._get_api_key", return_value=""),
            mock.patch("matcha.ai._get_api_url", return_value="http://localhost:11434/v1"),
            mock.patch("matcha.ai._get_model", return_value=""),
        ):
            self.assertFalse(check_ai_available())

    def test_remote_provider_requires_key(self):
        from matcha.ai import check_ai_available

        with (
            mock.patch("matcha.ai._get_provider", return_value="groq"),
            mock.patch("matcha.ai._get_api_key", return_value=""),
            mock.patch("matcha.ai._get_api_url", return_value="https://api.groq.com/openai/v1"),
            mock.patch("matcha.ai._get_model", return_value="m"),
        ):
            self.assertFalse(check_ai_available())


class TestBudgetGuard(unittest.TestCase):
    def setUp(self):
        from matcha.ai import reset_budget

        reset_budget(0)

    def tearDown(self):
        from matcha.ai import reset_budget

        reset_budget(0)

    def _ok_response(self):
        resp = mock.MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"choices": [{"message": {"content": "x"}}]}
        return resp

    def test_unlimited_by_default(self):
        from matcha.ai import budget_remaining

        self.assertEqual(budget_remaining(), -1)

    def test_budget_exhausts_after_max_calls(self):
        from matcha.ai import _call_ai, budget_remaining, budget_used, reset_budget

        reset_budget(2)
        with (
            mock.patch("matcha.ai._get_api_key", return_value="key"),
            mock.patch("matcha.ai._get_api_url", return_value="https://test.ai/v1"),
            mock.patch("matcha.ai._get_model", return_value="model"),
            mock.patch("matcha.ai.requests.post", return_value=self._ok_response()) as mock_post,
        ):
            self.assertEqual(_call_ai([{"role": "user", "content": "hi"}]), "x")
            self.assertEqual(_call_ai([{"role": "user", "content": "hi"}]), "x")
            self.assertIsNone(_call_ai([{"role": "user", "content": "hi"}]))
        self.assertEqual(mock_post.call_count, 2)
        self.assertEqual(budget_used(), 2)
        self.assertEqual(budget_remaining(), 0)

    def test_reset_budget_restores_headroom(self):
        from matcha.ai import _call_ai, budget_remaining, reset_budget

        reset_budget(1)
        with (
            mock.patch("matcha.ai._get_api_key", return_value="key"),
            mock.patch("matcha.ai._get_api_url", return_value="https://test.ai/v1"),
            mock.patch("matcha.ai._get_model", return_value="model"),
            mock.patch("matcha.ai.requests.post", return_value=self._ok_response()),
        ):
            self.assertEqual(_call_ai([{"role": "user", "content": "hi"}]), "x")
            self.assertIsNone(_call_ai([{"role": "user", "content": "hi"}]))
            reset_budget(1)
            self.assertEqual(_call_ai([{"role": "user", "content": "hi"}]), "x")
            self.assertEqual(budget_remaining(), 0)

    def test_local_provider_posts_without_auth_header(self):
        from matcha.ai import _call_ai

        with (
            mock.patch("matcha.ai._get_provider", return_value="local"),
            mock.patch("matcha.ai._get_api_key", return_value=""),
            mock.patch("matcha.ai._get_api_url", return_value="http://localhost:11434/v1"),
            mock.patch("matcha.ai._get_model", return_value="llama3"),
            mock.patch("matcha.ai.requests.post", return_value=self._ok_response()) as mock_post,
        ):
            result = _call_ai([{"role": "user", "content": "hi"}])
            self.assertEqual(result, "x")
            kwargs = mock_post.call_args.kwargs
            self.assertNotIn("Authorization", kwargs["headers"])
            self.assertTrue(mock_post.call_args.args[0].endswith("/chat/completions"))

    def test_remote_provider_posts_with_bearer_header(self):
        from matcha.ai import _call_ai

        with (
            mock.patch("matcha.ai._get_api_key", return_value="sk-test"),
            mock.patch("matcha.ai._get_api_url", return_value="https://api.groq.com/openai/v1"),
            mock.patch("matcha.ai._get_model", return_value="m"),
            mock.patch("matcha.ai.requests.post", return_value=self._ok_response()) as mock_post,
        ):
            _call_ai([{"role": "user", "content": "hi"}])
            self.assertEqual(
                mock_post.call_args.kwargs["headers"]["Authorization"], "Bearer sk-test"
            )


class TestDiskCache(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self._cache_env = mock.patch.dict(
            os.environ,
            {"MATCHA_AI_CACHE": os.path.join(self._tmp.name, "cache.sqlite")},
        )
        self._cache_env.start()
        self.addCleanup(self._cache_env.stop)
        from matcha.ai import reset_budget

        reset_budget(0)

    def tearDown(self):
        from matcha.ai import reset_budget

        reset_budget(0)
        from matcha import ai_cache

        ai_cache.clear()

    def test_cache_key_is_stable_and_order_sensitive(self):
        from matcha.ai_cache import cache_key

        self.assertEqual(
            cache_key("score_job", {"a": 1, "b": 2}, {"c": 3}),
            cache_key("score_job", {"b": 2, "a": 1}, {"c": 3}),
        )
        self.assertNotEqual(
            cache_key("score_job", {"a": 1}, {"c": 3}),
            cache_key("score_job", {"a": 1}, {"c": 4}),
        )

    def test_put_get_roundtrip_and_zero_ttl(self):
        from matcha import ai_cache

        ai_cache.put("t", "k", "v")
        self.assertEqual(ai_cache.get("t", "k", 3600), "v")
        # ttl 0 = never served from cache
        self.assertIsNone(ai_cache.get("t", "k", 0))

    def test_ttl_expiry_uses_created_timestamp(self):
        from matcha import ai_cache

        with mock.patch("matcha.ai_cache.time") as mock_time:
            mock_time.time.return_value = 1000.0
            ai_cache.put("t", "k", "v")
            mock_time.time.return_value = 1005.0
            self.assertEqual(ai_cache.get("t", "k", 10), "v")
            self.assertIsNone(ai_cache.get("t", "k", 3))
        ai_cache.clear()
        self.assertIsNone(ai_cache.get("t", "k", 3600))

    def test_clear_removes_rows(self):
        from matcha import ai_cache

        ai_cache.put("t", "k", "v")
        ai_cache.clear()
        self.assertIsNone(ai_cache.get("t", "k", 3600))


class TestRunWithCache(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self._cache_env = mock.patch.dict(
            os.environ,
            {"MATCHA_AI_CACHE": os.path.join(self._tmp.name, "cache.sqlite")},
        )
        self._cache_env.start()
        self.addCleanup(self._cache_env.stop)

    def test_cache_hit_skips_call_ai_when_ttl_enabled(self):
        from matcha.ai import _run_with_cache

        msg_a = [{"role": "user", "content": "score job A"}]
        msg_b = [{"role": "user", "content": "score job B"}]
        with (
            mock.patch("matcha.ai._call_ai", return_value='{"score": 80}') as mock_call,
            mock.patch("matcha.ai._ai_settings", return_value={"ai": {"cache_ttl": 86400}}),
        ):
            r1 = _run_with_cache("score_job", msg_a, 16384, 60, "best")
            r2 = _run_with_cache("score_job", msg_a, 16384, 60, "best")
            r3 = _run_with_cache("score_job", msg_b, 16384, 60, "best")
        self.assertEqual(r1, '{"score": 80}')
        self.assertEqual(r2, '{"score": 80}')
        self.assertEqual(r3, '{"score": 80}')
        # first + different-prompt call hit the API; the identical second was cached
        self.assertEqual(mock_call.call_count, 2)

    def test_cache_key_includes_model(self):
        from matcha.ai import _run_with_cache

        msg = [{"role": "user", "content": "hi"}]
        with (
            mock.patch("matcha.ai._call_ai", return_value="x") as mock_call,
            mock.patch("matcha.ai._ai_settings", return_value={"ai": {"cache_ttl": 86400}}),
        ):
            with mock.patch("matcha.ai._get_model", return_value="model-v1"):
                _run_with_cache("score_job", msg, 16384, 60, "best")
                _run_with_cache("score_job", msg, 16384, 60, "best")
            with mock.patch("matcha.ai._get_model", return_value="model-v2"):
                _run_with_cache("score_job", msg, 16384, 60, "best")
        # switching models bypasses the cache (no stale cross-model results)
        self.assertEqual(mock_call.call_count, 2)

    def test_cache_disabled_by_default_calls_every_time(self):
        from matcha.ai import _run_with_cache

        msg = [{"role": "user", "content": "hi"}]
        with (
            mock.patch("matcha.ai._call_ai", return_value="x") as mock_call,
            mock.patch("matcha.ai._ai_settings", return_value={"ai": {"cache_ttl": 0}}),
        ):
            _run_with_cache("score_job", msg, 16384, 60, "best")
            _run_with_cache("score_job", msg, 16384, 60, "best")
        self.assertEqual(mock_call.call_count, 2)

    def test_task_functions_wire_through_cache(self):
        from matcha.ai import ai_score_job

        profile = {"title": "Engineer", "skills": ["aws"]}
        job = {
            "title": "Platform Engineer",
            "company": "Co",
            "description": "aws kubernetes terraform",
            "location": "Remote",
        }
        with (
            mock.patch("matcha.ai.check_ai_available", return_value=True),
            mock.patch(
                "matcha.ai._call_ai", return_value='{"score": 80, "reasons": ["ok"]}'
            ) as mock_call,
            mock.patch("matcha.ai._ai_settings", return_value={"ai": {"cache_ttl": 86400}}),
        ):
            first = ai_score_job(profile, job)
            second = ai_score_job(profile, job)
        self.assertEqual(first["score"], 80)
        self.assertEqual(second["score"], 80)
        self.assertEqual(mock_call.call_count, 1)


class TestConfigureProvider(unittest.TestCase):
    def test_configure_provider_stores_and_clears_stale_overrides(self):
        from matcha.ai import configure_provider

        saved: dict = {}

        def fake_save(config, remove_keys=None):
            saved.update(config)

        with (
            mock.patch("matcha.ai.load_config", return_value={"ai_url": "old", "ai_model": "old"}),
            mock.patch("matcha.ai.save_config", side_effect=fake_save),
        ):
            configure_provider("groq", key="sk-test")
        self.assertEqual(saved["ai_provider"], "groq")
        self.assertEqual(saved["ai_key"], "sk-test")
        self.assertNotIn("ai_url", saved)
        self.assertNotIn("ai_model", saved)

    def test_configure_provider_keeps_explicit_overrides(self):
        from matcha.ai import configure_provider

        with (
            mock.patch("matcha.ai.load_config", return_value={}),
            mock.patch("matcha.ai.save_config") as mock_save,
        ):
            configure_provider("openai", key="k", url="https://x.example/v1", model="gpt-x")
        config = mock_save.call_args.args[0]
        self.assertEqual(config["ai_provider"], "openai")
        self.assertEqual(config["ai_url"], "https://x.example/v1")
        self.assertEqual(config["ai_model"], "gpt-x")

    def test_configure_provider_unknown_raises(self):
        from matcha.ai import configure_provider

        with (
            mock.patch("matcha.ai.load_config", return_value={}),
            mock.patch("matcha.ai.save_config"),
        ):
            with self.assertRaises(ValueError):
                configure_provider("not-a-provider", key="k")


class TestVerdict(unittest.TestCase):
    """§9.5 optional go/no-go verdict task (Phase 3-adjacent polish)."""

    def setUp(self):
        from matcha.ai import reset_budget

        reset_budget(0)
        # Hermetic: never consult the real AI disk cache (a hit would skip
        # _call_ai and break the budget/call assertions).
        self._settings_patch = mock.patch(
            "matcha.ai._ai_settings", return_value={"ai": {"cache_ttl": 0}}
        )
        self._settings_patch.start()
        self.addCleanup(self._settings_patch.stop)

    def tearDown(self):
        from matcha.ai import reset_budget

        reset_budget(0)

    def _profile(self):
        return {
            "title": "Platform Engineer",
            "headline": "DevOps Engineer",
            "skills": ["aws", "kubernetes"],
            "experience": "4",
            "summary": "Infrastructure engineer",
            "location": "Pune",
        }

    def _job(self):
        return {
            "title": "Senior DevOps Engineer",
            "company": "Acme",
            "location": "Pune",
            "salary": "₹30 LPA",
            "description": "aws kubernetes terraform",
        }

    def test_parses_recommendation(self):
        from matcha.ai import ai_verdict

        with (
            mock.patch("matcha.ai.check_ai_available", return_value=True),
            mock.patch(
                "matcha.ai._call_ai",
                return_value='{"recommend": true, "line": "Strong skills overlap, right seniority."}',
            ),
        ):
            result = ai_verdict(self._profile(), self._job())
        self.assertEqual(
            result, {"recommend": True, "line": "Strong skills overlap, right seniority."}
        )

    def test_gated_on_availability(self):
        from matcha.ai import ai_verdict

        with mock.patch("matcha.ai.check_ai_available", return_value=False):
            self.assertIsNone(ai_verdict(self._profile(), self._job()))

    def test_malformed_output_none(self):
        from matcha.ai import ai_verdict

        with (
            mock.patch("matcha.ai.check_ai_available", return_value=True),
            mock.patch("matcha.ai._call_ai", return_value="not json at all"),
        ):
            self.assertIsNone(ai_verdict(self._profile(), self._job()))

    def test_invalid_shape_none(self):
        from matcha.ai import ai_verdict

        for raw in ('{"recommend": "maybe"}', '{"recommend": true}'):
            with (
                mock.patch("matcha.ai.check_ai_available", return_value=True),
                mock.patch("matcha.ai._call_ai", return_value=raw),
            ):
                self.assertIsNone(ai_verdict(self._profile(), self._job()))

    def test_consumes_budget(self):
        from matcha.ai import ai_verdict, budget_used, reset_budget

        reset_budget(1)
        resp = mock.MagicMock()
        resp.status_code = 200
        resp.json.return_value = {
            "choices": [
                {"message": {"content": '{"recommend": false, "line": "Salary below your floor."}'}}
            ]
        }
        with (
            mock.patch("matcha.ai.check_ai_available", return_value=True),
            mock.patch("matcha.ai._get_api_key", return_value="key"),
            mock.patch("matcha.ai._get_api_url", return_value="https://test.ai/v1"),
            mock.patch("matcha.ai._get_model", return_value="model"),
            mock.patch("matcha.ai.requests.post", return_value=resp),
        ):
            result = ai_verdict(self._profile(), self._job())
        self.assertEqual(result["recommend"], False)
        self.assertEqual(budget_used(), 1)

    def test_wires_through_cache(self):
        from matcha.ai import ai_verdict

        with tempfile.TemporaryDirectory() as tmp:
            with (
                mock.patch.dict(
                    os.environ,
                    {"MATCHA_AI_CACHE": os.path.join(tmp, "cache.sqlite")},
                ),
                mock.patch("matcha.ai.check_ai_available", return_value=True),
                mock.patch(
                    "matcha.ai._call_ai",
                    return_value='{"recommend": true, "line": "Good fit."}',
                ) as mock_call,
                mock.patch("matcha.ai._ai_settings", return_value={"ai": {"cache_ttl": 86400}}),
            ):
                first = ai_verdict(self._profile(), self._job())
                second = ai_verdict(self._profile(), self._job())
        self.assertEqual(first, second)
        self.assertEqual(mock_call.call_count, 1)


if __name__ == "__main__":
    unittest.main()
