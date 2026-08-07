"""Hermetic tests for sources/utils.py — rate limiter + resilient_get retries."""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from requests.exceptions import ConnectionError, Timeout


class TestRateLimiter(unittest.TestCase):
    def test_bucket_refills(self):
        from matcha.sources.utils import RateLimiter

        limiter = RateLimiter()
        limiter.set_rate("example.com", 60)  # 1 token/sec
        limiter.acquire("example.com")  # consumes
        limiter.acquire("example.com")  # instant refill within same tick
        bucket = limiter._buckets["example.com"]
        self.assertLessEqual(bucket.tokens, bucket.max_tokens)
        # a domain without a bucket is a no-op
        limiter.acquire("unknown.example")
        self.assertIsNone(limiter._buckets.get("unknown.example"))

    def test_acquire_waits_when_exhausted(self):
        from matcha.sources.utils import RateLimiter

        limiter = RateLimiter()
        limiter.set_rate("slow.example", 2)  # 2 rpm
        limiter.acquire("slow.example")
        limiter.acquire("slow.example")
        with (
            mock.patch("matcha.sources.utils.time.sleep") as sleep,
            mock.patch(
                "matcha.sources.utils.time.monotonic",
                side_effect=[0.0, 0.0, 0.0, 0.1, 0.1, 0.1, 0.2, 0.2, 0.2],
            ),
        ):
            limiter.acquire("slow.example")  # tokens exhausted -> sleep
            self.assertTrue(sleep.called)


class _Resp:
    def __init__(self, status_code=200):
        self.status_code = status_code


class TestResilientGet(unittest.TestCase):
    def test_success(self):
        from matcha.sources.utils import resilient_get

        session = mock.Mock()
        session.get.return_value = _Resp(200)
        with mock.patch("matcha.sources.utils.limiter.acquire"):
            resp = resilient_get("https://x.example", session=session)
        self.assertEqual(resp.status_code, 200)
        session.get.assert_called_once()

    def test_retries_retryable_status(self):
        from matcha.sources.utils import resilient_get

        session = mock.Mock()
        session.get.side_effect = [_Resp(429), _Resp(503), _Resp(200)]
        with (
            mock.patch("matcha.sources.utils.limiter.acquire"),
            mock.patch("matcha.sources.utils.time.sleep"),
        ):
            resp = resilient_get("https://x.example", session=session)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(session.get.call_count, 3)

    def test_retries_connection_error_then_succeeds(self):
        from matcha.sources.utils import resilient_get

        session = mock.Mock()
        session.get.side_effect = [ConnectionError("down"), _Resp(200)]
        with (
            mock.patch("matcha.sources.utils.limiter.acquire"),
            mock.patch("matcha.sources.utils.time.sleep"),
        ):
            resp = resilient_get("https://x.example", session=session)
        self.assertEqual(resp.status_code, 200)

    def test_connection_error_raises_after_retries(self):
        from matcha.sources.utils import resilient_get

        session = mock.Mock()
        session.get.side_effect = ConnectionError("down")
        with (
            mock.patch("matcha.sources.utils.limiter.acquire"),
            mock.patch("matcha.sources.utils.time.sleep"),
            self.assertRaises(ConnectionError),
        ):
            resilient_get("https://x.example", session=session)

    def test_timeout_raises(self):
        from matcha.sources.utils import resilient_get

        session = mock.Mock()
        session.get.side_effect = Timeout("slow")
        with (
            mock.patch("matcha.sources.utils.limiter.acquire"),
            mock.patch("matcha.sources.utils.time.sleep"),
            self.assertRaises(Timeout),
        ):
            resilient_get("https://x.example", session=session)


class _FakeClient:
    """DDGS-ish client: context manager with .text() returning rows.

    ``fail_times`` lets the first N calls raise (transient blip) and later
    calls succeed — mirrors the real library's flaky free-tier behaviour.
    """

    def __init__(self, rows, exc=None, fail_times=0):
        self._rows = rows or []
        self._exc = exc
        self._fail_times = fail_times
        self.calls = 0

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def text(self, query, max_results=5, timelimit=""):
        self.calls += 1
        if self._fail_times > 0:
            self._fail_times -= 1
            raise self._exc if self._exc else RuntimeError("transient")
        return self._rows


class TestDdgsText(unittest.TestCase):
    """Session 23: the shared DDGS helper must retry transient failures."""

    def _factory(self, client):
        return lambda *a, **k: client

    def test_happy_path(self):
        from matcha.sources.utils import ddgs_text

        client = _FakeClient([{"title": "t", "href": "u"}])
        rows = ddgs_text("engineer", ddgs=self._factory(client))
        self.assertEqual(len(rows), 1)
        self.assertEqual(client.calls, 1)

    def test_retries_once_then_succeeds(self):
        from matcha.sources.utils import ddgs_text

        client = _FakeClient([{"title": "t"}], exc=TimeoutError("timed out"), fail_times=1)
        with mock.patch("matcha.sources.utils.time.sleep"):
            rows = ddgs_text("engineer", ddgs=self._factory(client))
        self.assertEqual(len(rows), 1)  # transient failure recovered
        self.assertEqual(client.calls, 2)  # 1 failure + 1 retry

    def test_persistent_failure_raises(self):
        from matcha.sources.utils import ddgs_text

        client = _FakeClient([], exc=RuntimeError("ddgs down"), fail_times=9)
        with (
            mock.patch("matcha.sources.utils.time.sleep"),
            self.assertRaises(RuntimeError),
        ):
            ddgs_text("engineer", ddgs=self._factory(client))
        self.assertEqual(client.calls, 2)  # both attempts exhausted

    def test_timelimit_passed_through(self):
        from matcha.sources.utils import ddgs_text

        client = _FakeClient([])
        with mock.patch("matcha.sources.utils.time.sleep"):
            ddgs_text("engineer", timelimit="w", ddgs=self._factory(client))
        self.assertEqual(client.calls, 1)

    def test_ddgs_rate_is_30_rpm(self):
        # Session 23: 6 rpm (1 req/10s) starved the DDGS sources under the 75s
        # batch timeout; 30 rpm keeps the pipeline inside budget while staying
        # polite to DuckDuckGo.
        from matcha.sources.utils import limiter

        self.assertEqual(limiter._buckets["duckduckgo.com"].max_tokens, 30)


if __name__ == "__main__":
    unittest.main()
