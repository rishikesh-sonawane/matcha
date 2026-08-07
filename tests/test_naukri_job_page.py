"""Tests for the Naukri job-page backend (strategy §6.2, Phase 1).

Covers the real ``job-listings-*`` page pipeline: embedded JSON parsing
(JSON-LD JobPosting + Next.js ``__NEXT_DATA__``), the Jina-rendered-markdown
parser (live page fields + expired→search-page redirect detection), the
backend dispatch in ``search_naukri_jobs`` (cap, per-job isolation, ddgs
fallback) and the ``NaukriSource`` contract. Hermetic — DDGS and every page
fetch are mocked; no network.
"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from matcha.sources.naukri import (
    _DIRECT_FETCH_TIMEOUT,
    _EXPIRED,
    _JOB_PAGE_MAX,
    NaukriSource,
    _company_from_slug,
    _extract_job_fields,
    _fetch_job_page,
    _is_search_page_render,
    _locations_from_slug,
    _looks_server_rendered,
    _parse_rendered_text,
    search_naukri_jobs,
)

JOB_URL = (
    "https://www.naukri.com/job-listings-python-developer-varite-kolkata-"
    "hyderabad-bengaluru-8-to-13-years-100326009734"
)

#: Jina-rendered markdown of a LIVE Naukri job page (synthetic, structure
#: verified against real r.jina.ai output on 2026-08-06).
LIVE_MARKDOWN = f"""Title: Python Developer - Varite - Kolkata, Hyderabad, Bengaluru - 8 to 13 years - Naukri.com

URL Source: {JOB_URL}

Markdown Content:
[**Python Developer**]({JOB_URL})
[Varite](https://www.naukri.com/company/varite)

Kolkata, Hyderabad, Bengaluru

₹ 8-13 LPA

8 to 13 Years

Full-Time

Posted: 2 days ago

**About the job**
We are looking for a Python Developer with strong Django and AWS experience to build
scalable backend services. You will work with cross-functional teams on cloud-native
platforms.

**Key Skills**
Python, Django, AWS, PostgreSQL

**About Company**
Varite is a global staffing company.

[Apply Now]({JOB_URL}?src=apply)
"""

#: Jina-rendered markdown of an EXPIRED posting (redirected to a search page).
EXPIRED_MARKDOWN = """Title: Python Developer Jobs In New Delhi - 561 Python Developer Job Vacancies In New Delhi - Naukri.com

URL Source: https://www.naukri.com/job-listings-python-developer-total-shape-kolkata-mumbai-new-delhi-hyderabad-pune-chennai-bengaluru-1-to-4-years-280525501795

Markdown Content:
*   [Jobs](https://www.naukri.com/ "Search Jobs")
*   [Popular categories](https://www.naukri.com/job-listings-python-developer-total-shape-kolkata-mumbai-new-delhi-hyderabad-pune-chennai-bengaluru-1-to-4-years-280525501795)
"""

JSONLD_HTML = """<html><head>
<script type="application/ld+json">
{
  "@context": "https://schema.org/",
  "@type": "JobPosting",
  "title": "Python Developer",
  "description": "Build backend services with Django.",
  "datePosted": "2026-08-05",
  "hiringOrganization": {"@type": "Organization", "name": "Varite"},
  "jobLocation": {"@type": "Place", "address": {
    "@type": "PostalAddress", "addressLocality": "Pune",
    "addressRegion": "Maharashtra", "addressCountry": "IN"}},
  "baseSalary": {"@type": "MonetaryAmount", "currency": "INR", "value": {
    "@type": "QuantitativeValue", "value": "13", "unitText": "LPA"}},
  "skills": ["Python", "Django", "AWS"]
}
</script>
</head><body></body></html>
"""

NEXT_DATA_HTML = """<html><head>
<script id="__NEXT_DATA__" type="application/json">
{"props":{"pageProps":{"jobDetails":{
  "title": "Data Engineer",
  "jobDescription": "Build data pipelines at scale.",
  "companyName": "Acme",
  "location": "Hyderabad",
  "salary": "\\u20b920-25 LPA",
  "minExperience": "3",
  "maxExperience": "6",
  "keySkills": ["Spark", "Airflow"],
  "applyUrl": "https://apply.example/x",
  "createdDate": "2026-08-01"
}}}}
</script>
</head><body></body></html>
"""


def _search_ok(job_url=JOB_URL):
    """Mocked DDGS result list for one discovery hit."""
    return [
        {
            "href": job_url,
            "title": "Python Developer - Varite - Kolkata, Hyderabad, Bengaluru - 8 to 13 years - Naukri.com",
            "body": "Python Developer - Varite - Kolkata, Hyderabad, Bengaluru - 8 to 13 years - "
            "Naukri.com. ₹ 8-13 LPA.",
        }
    ]


def _patch_ddgs(urls):
    """Patch module DDGS to return ``urls``; return the instance mock."""
    instance = mock.MagicMock()
    instance.text.return_value = urls
    ddgs = mock.patch("matcha.sources.naukri.DDGS")
    m = ddgs.start()
    m.return_value.__enter__.return_value = instance
    return ddgs, instance


class TestRenderedParse(unittest.TestCase):
    def test_live_job_page_fields(self):
        fields = _parse_rendered_text(LIVE_MARKDOWN, JOB_URL)
        self.assertIsNotNone(fields)
        self.assertEqual(fields["title"], "Python Developer")
        self.assertEqual(fields["company"], "Varite")
        self.assertEqual(fields["location"], "Kolkata, Hyderabad, Bengaluru")
        self.assertEqual(fields["salary"], "₹8-13 LPA")
        self.assertEqual(fields["experience"], "8-13 Years")
        self.assertEqual(fields["listed"], "2 days ago")
        self.assertEqual(fields["keyskills"], "Python, Django, AWS, PostgreSQL")
        self.assertIn("strong Django and AWS experience", fields["description"])
        self.assertEqual(fields["apply_url"], f"{JOB_URL}?src=apply")

    def test_expired_posting_redirect_detected(self):
        self.assertTrue(_is_search_page_render(EXPIRED_MARKDOWN))
        self.assertIsNone(_parse_rendered_text(EXPIRED_MARKDOWN, JOB_URL))
        # The field-level entry point must surface the dead-posting signal so
        # the dispatcher can DROP it (not keep it as a stale snippet)…
        self.assertIs(_extract_job_fields(EXPIRED_MARKDOWN, JOB_URL), _EXPIRED)
        # …while a LIVE page must never be misdetected (the drop is destructive).
        self.assertIsNot(_extract_job_fields(LIVE_MARKDOWN, JOB_URL), _EXPIRED)

    def test_empty_text_returns_none(self):
        self.assertIsNone(_parse_rendered_text("", JOB_URL))

    def test_company_from_slug(self):
        self.assertEqual(_company_from_slug(JOB_URL), "Varite")
        tcs = (
            "https://www.naukri.com/job-listings-python-developer-tata-consultancy-"
            "services-hyderabad-chennai-bengaluru-6-to-8-years-020326002686"
        )
        self.assertEqual(_company_from_slug(tcs), "Tata Consultancy Services")

    def test_locations_from_slug(self):
        self.assertEqual(_locations_from_slug(JOB_URL), "Kolkata, Hyderabad, Bengaluru")
        self.assertEqual(
            _locations_from_slug("https://www.naukri.com/job-listings-x-y-z-5-to-8-years-123"),
            "",
        )


class TestEmbeddedParse(unittest.TestCase):
    def test_jsonld_jobposting(self):
        fields = _extract_job_fields(JSONLD_HTML, JOB_URL)
        self.assertIsNotNone(fields)
        self.assertEqual(fields["title"], "Python Developer")
        self.assertEqual(fields["company"], "Varite")
        self.assertEqual(fields["location"], "Pune, Maharashtra, IN")
        self.assertEqual(fields["listed"], "2026-08-05")
        self.assertEqual(fields["salary"], "INR 13")
        self.assertEqual(fields["keyskills"], "Python, Django, AWS")
        self.assertEqual(fields["description"], "Build backend services with Django.")

    def test_next_data(self):
        fields = _extract_job_fields(NEXT_DATA_HTML, JOB_URL)
        self.assertIsNotNone(fields)
        self.assertEqual(fields["title"], "Data Engineer")
        self.assertEqual(fields["company"], "Acme")
        self.assertEqual(fields["location"], "Hyderabad")
        self.assertEqual(fields["description"], "Build data pipelines at scale.")
        self.assertEqual(fields["salary"], "₹20-25 LPA")
        self.assertEqual(fields["experience"], "3-6")
        self.assertEqual(fields["keyskills"], "Spark, Airflow")
        self.assertEqual(fields["apply_url"], "https://apply.example/x")
        self.assertEqual(fields["listed"], "2026-08-01")

    def test_rendered_fallback_when_no_embedded_data(self):
        fields = _extract_job_fields(LIVE_MARKDOWN, JOB_URL)
        self.assertEqual(fields["title"], "Python Developer")  # markdown path used

    def test_looks_server_rendered(self):
        self.assertFalse(_looks_server_rendered("<html>shell</html>"))
        self.assertTrue(_looks_server_rendered("x" * 60_000))
        self.assertTrue(_looks_server_rendered('<script id="__NEXT_DATA__">{}'))
        self.assertTrue(_looks_server_rendered('<script type="application/ld+json">{}'))


class TestFetchJobPage(unittest.TestCase):
    """Direct-HTML → Jina-render fallback ordering in _fetch_job_page."""

    def _resp(self, status=200, text=""):
        resp = mock.Mock()
        resp.status_code = status
        resp.text = text
        return resp

    def test_server_rendered_direct_hit_wins(self):
        rendered = '<script type="application/ld+json">{}</script>' + "x" * 60_000
        with mock.patch(
            "matcha.sources.naukri.resilient_get", return_value=self._resp(text=rendered)
        ) as get:
            out = _fetch_job_page(JOB_URL, 12)
        self.assertEqual(out, rendered)
        self.assertEqual(get.call_count, 1)  # Jina never needed
        self.assertEqual(get.call_args.args[0], JOB_URL)

    def test_shell_falls_back_to_jina(self):
        shell = "<html>" + "x" * 20_000 + "</html>"
        jina_text = LIVE_MARKDOWN
        with mock.patch(
            "matcha.sources.naukri.resilient_get",
            side_effect=[self._resp(text=shell), self._resp(text=jina_text)],
        ) as get:
            out = _fetch_job_page(JOB_URL, 12)
        self.assertEqual(out, jina_text)
        self.assertEqual(get.call_count, 2)
        self.assertEqual(get.call_args_list[0].args[0], JOB_URL)
        self.assertEqual(get.call_args_list[1].args[0], "https://r.jina.ai/" + JOB_URL)

    def test_direct_timeout_bounded(self):
        with mock.patch(
            "matcha.sources.naukri.resilient_get",
            side_effect=[self._resp(text="shell"), self._resp(text=LIVE_MARKDOWN)],
        ) as get:
            _fetch_job_page(JOB_URL, 12)
        direct_kwargs = get.call_args_list[0].kwargs
        self.assertEqual(direct_kwargs["timeout"], _DIRECT_FETCH_TIMEOUT)  # never starves Jina

    def test_both_fail_returns_none(self):
        with mock.patch(
            "matcha.sources.naukri.resilient_get",
            side_effect=[self._resp(status=403), self._resp(status=500)],
        ) as get:
            out = _fetch_job_page(JOB_URL, 12)
        self.assertIsNone(out)
        self.assertEqual(get.call_count, 2)

    def test_direct_exception_falls_back(self):
        with mock.patch(
            "matcha.sources.naukri.resilient_get",
            side_effect=[OSError("boom"), self._resp(text=LIVE_MARKDOWN)],
        ):
            out = _fetch_job_page(JOB_URL, 12)
        self.assertEqual(out, LIVE_MARKDOWN)


class TestJobPageDispatch(unittest.TestCase):
    def setUp(self):
        self.acquire = mock.patch("matcha.sources.naukri.limiter.acquire")
        self.acquire.start()
        self.addCleanup(self.acquire.stop)

    def test_job_page_backend_enriches(self):
        ddgs, _ = _patch_ddgs(_search_ok())
        self.addCleanup(ddgs.stop)
        with mock.patch(
            "matcha.sources.naukri._fetch_job_page", return_value=LIVE_MARKDOWN
        ) as fetch:
            result = search_naukri_jobs("python developer")
        self.assertEqual(len(result.jobs), 1)
        job = result.jobs[0]
        self.assertEqual(job["title"], "Python Developer")
        self.assertEqual(job["company"], "Varite")
        self.assertEqual(job["salary"], "₹8-13 LPA")
        self.assertIn("strong Django", job["description"])
        self.assertEqual(job["data_quality"], "full")
        self.assertEqual(job["enrich_source"], "job-page")
        self.assertEqual(result.backend, "job-page")
        self.assertEqual(result.data_quality, "full")
        fetch.assert_called_once()
        self.assertIn(JOB_URL, fetch.call_args.args[0])

    def test_fetch_failure_keeps_snippet(self):
        ddgs, _ = _patch_ddgs(_search_ok())
        self.addCleanup(ddgs.stop)
        with mock.patch("matcha.sources.naukri._fetch_job_page", return_value=None):
            result = search_naukri_jobs("python developer")
        job = result.jobs[0]
        self.assertIn("enrich_error", job)
        self.assertEqual(job.get("data_quality"), "snippet")
        self.assertEqual(result.data_quality, "snippet")
        self.assertEqual(result.backend, "ddgs")  # no page data served → honest

    def test_all_fetches_fail_backend_stays_ddgs(self):
        urls = [
            {
                "href": JOB_URL.replace("100326009734", f"100326000{i:03d}"),
                "title": f"Python Developer {i}",
                "body": "Python Developer",
            }
            for i in range(3)
        ]
        ddgs, _ = _patch_ddgs(urls)
        self.addCleanup(ddgs.stop)
        with mock.patch("matcha.sources.naukri._fetch_job_page", return_value=None):
            result = search_naukri_jobs("python")
        self.assertEqual(result.backend, "ddgs")
        self.assertEqual(result.data_quality, "snippet")

    def test_ddgs_backend_skips_fetch(self):
        ddgs, _ = _patch_ddgs(_search_ok())
        self.addCleanup(ddgs.stop)
        with mock.patch("matcha.sources.naukri._fetch_job_page") as fetch:
            result = search_naukri_jobs("python developer", backend="ddgs")
        self.assertEqual(len(result.jobs), 1)
        fetch.assert_not_called()
        self.assertEqual(result.backend, "ddgs")
        self.assertEqual(result.data_quality, "snippet")

    def test_aggregate_urls_dropped_at_discovery(self):
        # Session 19: Naukri search/careers/homepage URLs are aggregates, never
        # postings — dropped outright (previously kept as misleading snippets).
        urls = [
            {
                "href": "https://www.naukri.com/it-jobs?src=gnbjobs",
                "title": "IT jobs",
                "body": "",
            },
            {
                "href": "https://www.naukri.com/?lnch=1",
                "title": "?Lnch=1",
                "body": "",
            },
            {
                "href": "https://www.naukri.com/cloud-support-engineer-jobs",
                "title": "Cloud Support Engineer",
                "body": "",
            },
        ]
        ddgs, _ = _patch_ddgs(urls)
        self.addCleanup(ddgs.stop)
        with mock.patch("matcha.sources.naukri._fetch_job_page") as fetch:
            result = search_naukri_jobs("python")
        self.assertEqual(len(result.jobs), 0)
        fetch.assert_not_called()
        self.assertEqual(result.backend, "ddgs")

    def test_expired_posting_dropped_from_results(self):
        ddgs, _ = _patch_ddgs(_search_ok())
        self.addCleanup(ddgs.stop)
        with mock.patch("matcha.sources.naukri._fetch_job_page", return_value=EXPIRED_MARKDOWN):
            result = search_naukri_jobs("python developer")
        self.assertEqual(len(result.jobs), 0)  # dead posting removed, not kept

    def test_mixed_expired_and_live_only_live_kept(self):
        urls = [
            {
                "href": JOB_URL.replace("100326009734", f"100326000{i:03d}"),
                "title": f"Python Developer {i}",
                "body": "Python Developer",
            }
            for i in range(3)
        ]
        ddgs, _ = _patch_ddgs(urls)
        self.addCleanup(ddgs.stop)

        def fetch(url, timeout=12):
            if url.endswith("001"):
                return EXPIRED_MARKDOWN  # dead posting
            return LIVE_MARKDOWN

        with mock.patch("matcha.sources.naukri._fetch_job_page", side_effect=fetch):
            result = search_naukri_jobs("python")
        self.assertEqual(len(result.jobs), 2)  # expired one gone
        self.assertTrue(all(j.get("data_quality") == "full" for j in result.jobs))
        self.assertEqual(result.backend, "job-page")
        self.assertEqual(result.data_quality, "full")

    def test_search_listing_urls_dropped_at_discovery(self):
        # Session 19: DDGS frequently returns Naukri SEARCH/careers listing
        # pages (aggregates, never postings) — they must be dropped, not
        # surfaced as jobs. Only real ``/job-listings-*`` URLs survive.
        urls = [
            {
                "href": "https://www.naukri.com/aws-devops-engineer-jobs-in-india?expJD=true",
                "title": "Aws Devops Engineer",
                "body": "AWS DevOps Engineer",
            },
            {
                "href": "https://www.naukri.com/aws-jobs-in-hyderabad-secunderabad",
                "title": "Aws",
                "body": "AWS jobs",
            },
            {
                "href": "https://www.naukri.com/techblocks-jobs-careers-2864034",
                "title": "Techblocks Careers",
                "body": "Techblocks careers",
            },
            {
                "href": "https://www.naukri.com/tata-consultancy-services-jobs-careers-in-hyderabad-gid-223346",
                "title": "Tata Consultancy Services",
                "body": "TCS careers",
            },
            {
                "href": "https://www.naukri.com/walkin-drives-jobs-in-bangalore",
                "title": "Walkin Drives",
                "body": "Walkin drives",
            },
        ] + _search_ok()  # a real posting must survive
        ddgs, _ = _patch_ddgs(urls)
        self.addCleanup(ddgs.stop)
        with mock.patch(
            "matcha.sources.naukri._fetch_job_page", return_value=LIVE_MARKDOWN
        ) as fetch:
            result = search_naukri_jobs("aws devops engineer")
        self.assertEqual(len(result.jobs), 1)
        self.assertEqual(result.jobs[0]["url"], JOB_URL)
        fetch.assert_called_once()

    def test_beyond_cap_rows_stay_honest_snippet(self):
        # Session 19: rows beyond the page-fetch cap are NOT enriched — their
        # per-row provenance must stay snippet (never inherit the batch's
        # result-level "full" which inflated their rank + AI eligibility).
        urls = [
            {
                "href": JOB_URL.replace("100326009734", f"100326000{i:03d}"),
                "title": f"Python Developer {i}",
                "body": "Python Developer",
            }
            for i in range(_JOB_PAGE_MAX + 2)
        ]
        ddgs, _ = _patch_ddgs(urls)
        self.addCleanup(ddgs.stop)
        with mock.patch(
            "matcha.sources.naukri._fetch_job_page", return_value=LIVE_MARKDOWN
        ) as fetch:
            result = search_naukri_jobs("python")
        enriched = [j for j in result.jobs if j.get("data_quality") == "full"]
        self.assertEqual(len(enriched), _JOB_PAGE_MAX)
        self.assertEqual(fetch.call_count, _JOB_PAGE_MAX)
        beyond = result.jobs[_JOB_PAGE_MAX:]
        self.assertEqual(len(beyond), 2)
        self.assertTrue(all(j.get("data_quality") == "snippet" for j in beyond))
        self.assertTrue(all(j.get("backend") == "ddgs" for j in beyond))

    def test_fetch_cap_respected(self):
        urls = [
            {
                "href": JOB_URL.replace("100326009734", f"100326000{i:03d}"),
                "title": f"Python Developer {i}",
                "body": "Python Developer",
            }
            for i in range(_JOB_PAGE_MAX + 4)
        ]
        ddgs, _ = _patch_ddgs(urls)
        self.addCleanup(ddgs.stop)
        with mock.patch(
            "matcha.sources.naukri._fetch_job_page", return_value=LIVE_MARKDOWN
        ) as fetch:
            result = search_naukri_jobs("python")
        self.assertEqual(fetch.call_count, _JOB_PAGE_MAX)
        self.assertEqual(len(result.jobs), _JOB_PAGE_MAX + 4)  # rest stay snippet

    def test_single_failure_does_not_take_down_batch(self):
        urls = [
            {
                "href": JOB_URL.replace("100326009734", f"100326000{i:03d}"),
                "title": f"Python Developer {i}",
                "body": "Python Developer",
            }
            for i in range(4)
        ]
        ddgs, _ = _patch_ddgs(urls)
        self.addCleanup(ddgs.stop)

        def flaky(url, timeout=12):
            if url.endswith("001"):
                return None
            return LIVE_MARKDOWN

        with mock.patch("matcha.sources.naukri._fetch_job_page", side_effect=flaky):
            result = search_naukri_jobs("python")
        enriched = [j for j in result.jobs if j.get("data_quality") == "full"]
        self.assertEqual(len(enriched), 3)
        failed = next(j for j in result.jobs if j["url"].endswith("001"))
        self.assertIn("enrich_error", failed)
        self.assertEqual(result.data_quality, "full")


class TestNaukriSourceContract(unittest.TestCase):
    def test_backends_ordered(self):
        self.assertEqual(NaukriSource().backends, ["job-page", "ddgs"])

    def test_check_sets_active_backend(self):
        src = NaukriSource()
        status, message = src.check(None)
        self.assertEqual(status, "ok")
        self.assertTrue(message)
        self.assertEqual(src.active_backend, "job-page")

    def test_search_passes_backend(self):
        src = NaukriSource()
        src.check(None)
        with mock.patch("matcha.sources.naukri.search_naukri_jobs", return_value=None) as search:
            src.search("python", "pune")
        self.assertEqual(search.call_args[1]["backend"], "job-page")


if __name__ == "__main__":
    unittest.main()
