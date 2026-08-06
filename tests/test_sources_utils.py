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


if __name__ == "__main__":
    unittest.main()
