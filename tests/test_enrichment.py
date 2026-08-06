"""Tests for top-N enrichment via OpenCLI job-detail (strategy §8).

Covers the per-source merge contracts (incl. F-06: LinkedIn enrichment never
claims salary), per-job failure isolation, consent + bridge gates, parallel
top-N selection, and the Jina Reader zero-config fallback.

Mock convention: stacked @patch decorators pass mocks in top-to-bottom order.
"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from matcha.sources.backends.opencli import OpenCLIStatus
from matcha.sources.enrichment import enrich_job, enrich_top_n

READY = OpenCLIStatus(installed=True, extension_connected=True)
DOWN = OpenCLIStatus(installed=True)  # not ready

# Most tests exercise the enrichment mechanics; the consent gate is a
# contract on its own (TestGates). Default to consent granted here.
CONSENT = mock.patch("matcha.sources.enrichment.consent_granted", return_value=True)


def _ranked(*jobs):
    return [(50.0, dict(job), []) for job in jobs]


def _linkedin_job(url="https://www.linkedin.com/jobs/view/123"):
    return {"title": "Dev", "company": "Acme", "location": "Pune", "url": url, "source": "LinkedIn"}


def _indeed_job(job_key="dccc07ac5a6a3683"):
    return {
        "title": "Eng",
        "company": "Acme",
        "location": "Pune",
        "job_key": job_key,
        "source": "Indeed",
    }


class TestEnrichLinkedIn(unittest.TestCase):
    @mock.patch("matcha.sources.enrichment.opencli_status", return_value=READY)
    @mock.patch("matcha.sources.enrichment.linkedin_job_detail")
    def test_merges_detail_fields_and_upgrades_quality(self, detail, status):
        with CONSENT:
            detail.return_value = {
                "title": "Dev",
                "description": "Full description...",
                "apply_url": "https://www.linkedin.com/jobs/view/123/apply",
                "workplace_type": "Hybrid",
                "job_type": "Full-time",
                "applicants": "50 applicants",
                "listed": "3 days ago",
                "company_url": "https://acme.example",
                "salary": "₹50L",  # present in payload — must NOT be merged (F-06)
            }
            job = _linkedin_job()
            self.assertTrue(enrich_job(job, config={}))
        self.assertEqual(job["description"], "Full description...")
        self.assertEqual(job["apply_url"], "https://www.linkedin.com/jobs/view/123/apply")
        self.assertEqual(job["workplace_type"], "Hybrid")
        self.assertEqual(job["data_quality"], "full")
        self.assertEqual(job["enrich_source"], "opencli")
        self.assertNotIn("salary", job)  # F-06: LinkedIn detail has no salary

    @mock.patch("matcha.sources.enrichment.opencli_status", return_value=READY)
    @mock.patch("matcha.sources.enrichment.linkedin_job_detail")
    def test_non_job_url_skipped(self, detail, status):
        with CONSENT:
            job = _linkedin_job(url="https://example.com/careers")
            self.assertFalse(enrich_job(job))
        detail.assert_not_called()

    @mock.patch("matcha.sources.enrichment.opencli_status", return_value=READY)
    @mock.patch("matcha.sources.enrichment.linkedin_job_detail", return_value=None)
    def test_detail_failure_isolated(self, detail, status):
        with CONSENT:
            job = _linkedin_job()
            self.assertFalse(enrich_job(job))
        self.assertIn("enrich_error", job)
        self.assertEqual(job.get("description", ""), "")  # search data untouched
        self.assertNotIn("data_quality", job)


class TestEnrichIndeed(unittest.TestCase):
    @mock.patch("matcha.sources.enrichment.opencli_status", return_value=READY)
    @mock.patch("matcha.sources.enrichment.indeed_job_detail")
    def test_merges_detail_fields(self, detail, status):
        with CONSENT:
            detail.return_value = {
                "id": "dccc07ac5a6a3683",
                "description": "Full description...",
                "job_type": "Full-time",
                "salary": "₹30L",
                "url": "https://www.indeed.com/viewjob?jk=dccc07ac5a6a3683",
            }
            job = _indeed_job()
            self.assertTrue(enrich_job(job))
        self.assertEqual(job["description"], "Full description...")
        self.assertEqual(job["salary"], "₹30L")  # Indeed detail DOES have salary
        self.assertEqual(job["data_quality"], "full")
        self.assertEqual(job["enrich_source"], "opencli")

    @mock.patch("matcha.sources.enrichment.opencli_status", return_value=READY)
    @mock.patch("matcha.sources.enrichment.indeed_job_detail")
    def test_missing_job_key_skipped(self, detail, status):
        with CONSENT:
            job = {"title": "Eng", "source": "Indeed"}
            self.assertFalse(enrich_job(job))
        detail.assert_not_called()

    @mock.patch("matcha.sources.enrichment.indeed_job_detail")
    @mock.patch("matcha.sources.enrichment.opencli_status", return_value=DOWN)
    def test_bridge_down_skips_indeed(self, status, detail):
        with CONSENT:
            job = _indeed_job()
            self.assertFalse(enrich_job(job))
        detail.assert_not_called()  # no zero-config fallback for Indeed yet


class TestGates(unittest.TestCase):
    @mock.patch("matcha.sources.enrichment.opencli_status", return_value=READY)
    @mock.patch("matcha.sources.enrichment.consent_granted", return_value=False)
    @mock.patch("matcha.sources.enrichment.linkedin_job_detail")
    def test_no_consent_skips_opencli_path(self, detail, consent, status):
        job = _linkedin_job()
        self.assertFalse(enrich_job(job))
        detail.assert_not_called()

    def test_unknown_source_skipped(self):
        self.assertFalse(enrich_job({"title": "x", "source": "RemoteOK"}))

    @mock.patch("matcha.sources.enrichment.opencli_status", return_value=READY)
    @mock.patch("matcha.sources.enrichment.linkedin_job_detail", side_effect=RuntimeError("boom"))
    def test_exception_isolated(self, detail, status):
        with CONSENT:
            job = _linkedin_job()
            self.assertFalse(enrich_job(job))
        self.assertIn("enrich_error", job)
        self.assertEqual(job["title"], "Dev")  # job intact


class TestEnrichTopN(unittest.TestCase):
    @mock.patch("matcha.sources.enrichment.opencli_status", return_value=READY)
    @mock.patch("matcha.sources.enrichment.linkedin_job_detail")
    def test_only_top_n_enriched_parallel(self, detail, status):
        jobs = [_linkedin_job(url=f"https://www.linkedin.com/jobs/view/{i}") for i in range(6)]
        ranked = _ranked(*jobs)
        with CONSENT:
            detail.return_value = {"description": "desc"}
            enriched, out = enrich_top_n(ranked, top_n=3, max_workers=2)
        self.assertEqual(enriched, 3)
        for i in range(3):
            self.assertEqual(out[i][1]["description"], "desc")
            self.assertEqual(out[i][1]["data_quality"], "full")
        for i in range(3, 6):
            self.assertNotIn("description", out[i][1])
        # ranking order preserved
        self.assertEqual([score for score, _, _ in out], [50.0] * 6)

    @mock.patch("matcha.sources.enrichment.opencli_status", return_value=READY)
    @mock.patch("matcha.sources.enrichment.linkedin_job_detail")
    def test_per_job_failure_does_not_take_down_batch(self, detail, status):
        jobs = [_linkedin_job(url=f"https://www.linkedin.com/jobs/view/{i}") for i in range(4)]
        ranked = _ranked(*jobs)

        def flaky(url, timeout=30):
            if url.endswith("/1"):
                raise RuntimeError("boom")
            return {"description": "desc"}

        detail.side_effect = flaky
        with CONSENT:
            enriched, out = enrich_top_n(ranked, top_n=4, max_workers=2)
        self.assertEqual(enriched, 3)  # 3 succeeded, 1 failed in isolation
        self.assertIn("enrich_error", out[1][1])

    def test_empty_input(self):
        self.assertEqual(enrich_top_n([]), (0, []))

    @mock.patch("matcha.sources.enrichment.requests.get")
    @mock.patch("matcha.sources.enrichment.opencli_status", return_value=DOWN)
    def test_bridge_down_uses_jina_fallback(self, status, get):
        resp = mock.Mock()
        resp.status_code = 200
        resp.text = "# Python Dev\n\nFull markdown description"
        get.return_value = resp
        ranked = _ranked(_linkedin_job())
        with CONSENT:
            enriched, out = enrich_top_n(ranked, top_n=1, config={})
        self.assertEqual(enriched, 1)
        job = out[0][1]
        self.assertIn("Full markdown description", job["description"])
        self.assertEqual(job["data_quality"], "partial")
        self.assertEqual(job["enrich_source"], "jina")
        get.assert_called_once()
        self.assertIn("https://r.jina.ai/", get.call_args.args[0])

    @mock.patch("matcha.sources.enrichment.requests.get")
    @mock.patch("matcha.sources.enrichment.opencli_status", return_value=DOWN)
    def test_jina_failure_isolated(self, status, get):
        get.side_effect = OSError("network down")
        ranked = _ranked(_linkedin_job())
        with CONSENT:
            enriched, out = enrich_top_n(ranked, top_n=1)
        self.assertEqual(enriched, 0)
        self.assertEqual(out[0][1]["title"], "Dev")

    @mock.patch("matcha.sources.enrichment.requests.get")
    @mock.patch("matcha.sources.enrichment.opencli_status", return_value=DOWN)
    def test_jina_runs_without_consent(self, status, get):
        """Jina is zero-config (no browser/login) — it must not need OpenCLI consent."""
        resp = mock.Mock()
        resp.status_code = 200
        resp.text = "markdown body"
        get.return_value = resp
        ranked = _ranked(_linkedin_job())
        enriched, out = enrich_top_n(ranked, top_n=1)  # no consent anywhere
        self.assertEqual(enriched, 1)
        self.assertEqual(out[0][1]["enrich_source"], "jina")

    @mock.patch("matcha.sources.enrichment.requests.get")
    @mock.patch("matcha.sources.enrichment.opencli_status", return_value=DOWN)
    def test_bridge_down_jina_failure_no_enrichment(self, status, get):
        resp = mock.Mock()
        resp.status_code = 429  # rate-limited
        get.return_value = resp
        ranked = _ranked(_linkedin_job())
        enriched, _ = enrich_top_n(ranked, top_n=1)
        self.assertEqual(enriched, 0)

    @mock.patch("matcha.sources.enrichment.requests.get")
    @mock.patch("matcha.sources.enrichment.opencli_status", return_value=DOWN)
    def test_jina_fallback_capped(self, status, get):
        """Bridge-down batches never fire more than _JINA_MAX_JOBS fetches."""
        from matcha.sources.enrichment import _JINA_MAX_JOBS

        resp = mock.Mock()
        resp.status_code = 200
        resp.text = "x"
        get.return_value = resp
        jobs = [_linkedin_job(url=f"https://www.linkedin.com/jobs/view/{i}") for i in range(15)]
        ranked = _ranked(*jobs)
        enriched, out = enrich_top_n(ranked, top_n=15, max_workers=5)
        self.assertEqual(enriched, _JINA_MAX_JOBS)
        self.assertEqual(get.call_count, _JINA_MAX_JOBS)
        # only the top _JINA_MAX_JOBS were touched
        for i in range(_JINA_MAX_JOBS):
            self.assertEqual(out[i][1]["enrich_source"], "jina")
        self.assertNotIn("enrich_source", out[_JINA_MAX_JOBS][1])


if __name__ == "__main__":
    unittest.main()
