"""Tests for Phase 4 ranking recalibration (strategy §9).

Covers confidence-weighted scoring (full-data jobs outrank snippet-guesses),
the recency / workplace / must-have-skill signals, the soft-mode rank cap,
the AI-eligibility gate (enriched candidates only), the flatline calibration
guard, and provenance tags. Hermetic — pure functions, no network.
"""

import os
import sys
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from matcha.filters import provenance_tags
from matcha.matcher import (
    ai_eligible,
    compute_relevance,
    detect_flatline,
    normalize_scores,
)

PROFILE = {
    "title": "Platform Engineer",
    "headline": "DevOps Engineer",
    "skills": ["aws", "docker", "kubernetes", "terraform", "ci/cd", "linux"],
    "experience": "4",
    "summary": "Platform and infrastructure engineer with cloud experience",
    "location": "Pune",
}

_LONG_DESC = (
    "We are looking for a platform engineer to own our cloud infrastructure. "
    "You will work with aws, docker, kubernetes, terraform and ci/cd tooling, "
    "and manage linux fleets across regions."
)


def _job(**overrides):
    job = {
        "title": "Platform Engineer",
        "company": "Acme",
        "location": "Pune, India",
        "description": _LONG_DESC,
        "url": "https://example.com/jobs/1",
        "source": "Indeed",
    }
    job.update(overrides)
    return job


class TestConfidenceWeighting(unittest.TestCase):
    def test_full_data_outranks_snippet(self):
        full = compute_relevance(_job(data_quality="full"), PROFILE)
        snippet = compute_relevance(_job(data_quality="snippet"), PROFILE)
        self.assertGreater(full["score"], snippet["score"])

    def test_partial_between_full_and_snippet(self):
        full = compute_relevance(_job(data_quality="full"), PROFILE)["score"]
        partial = compute_relevance(_job(data_quality="partial"), PROFILE)["score"]
        snippet = compute_relevance(_job(data_quality="snippet"), PROFILE)["score"]
        self.assertGreater(full, partial)
        self.assertGreater(partial, snippet)

    def test_empty_description_scores_near_zero_skills(self):
        # No description, no quality flag → skills dimension is scaled to ~0.7×
        # and the only text is the title. Compare with a fully-described twin.
        rich = compute_relevance(_job(data_quality="full"), PROFILE)["score"]
        bare = compute_relevance(_job(description="", data_quality="snippet"), PROFILE)["score"]
        self.assertGreater(rich, bare)
        self.assertLess(bare, 60)

    def test_long_description_without_flag_is_confident(self):
        rich = compute_relevance(_job(), PROFILE)["score"]  # no quality flag
        flagged = compute_relevance(_job(data_quality="full"), PROFILE)["score"]
        self.assertAlmostEqual(rich, flagged, delta=0.1)


class TestRecencySignal(unittest.TestCase):
    def test_fresh_beats_old(self):
        fresh = compute_relevance(_job(listed_epoch=int(time.time()) - 86400), PROFILE)["score"]
        old = compute_relevance(_job(listed_epoch=int(time.time()) - 20 * 86400), PROFILE)["score"]
        self.assertGreater(fresh, old)

    def test_unknown_age_no_bonus(self):
        known = compute_relevance(_job(listed_epoch=int(time.time()) - 86400), PROFILE)["score"]
        unknown = compute_relevance(_job(), PROFILE)["score"]
        self.assertGreater(known, unknown)

    def test_recency_bonus_bounded(self):
        fresh = compute_relevance(_job(listed_epoch=int(time.time()) - 3600), PROFILE)["score"]
        self.assertLessEqual(fresh, 100.0)


class TestWorkplaceSignal(unittest.TestCase):
    def test_remote_preference_rewards_remote_job(self):
        remote = compute_relevance(
            _job(remote_ok=True, workplace_type="Remote"),
            {**PROFILE, "remote_preference": "remote"},
        )
        self.assertIn("Remote-friendly workplace", remote["reasons"])

    def test_onsite_preference_rewards_onsite_job(self):
        onsite = compute_relevance(
            _job(remote_ok=False, workplace_type="On-site"),
            {**PROFILE, "remote_preference": "onsite"},
        )
        self.assertIn("On-site position", onsite["reasons"])

    def test_no_preference_no_bonus(self):
        plain = compute_relevance(_job(remote_ok=True), PROFILE)
        self.assertNotIn(
            "Remote-friendly workplace",
            plain["reasons"],
            "no remote_preference → no workplace bonus",
        )


class TestMustSkillsBonus(unittest.TestCase):
    def test_coverage_bonus_added(self):
        profile = {**PROFILE, "must_have_skills": ["kubernetes", "terraform"]}
        with_bonus = compute_relevance(_job(), profile)["score"]
        without = compute_relevance(_job(), PROFILE)["score"]
        self.assertGreater(with_bonus, without)

    def test_synonym_k8s_counts(self):
        profile = {**PROFILE, "must_have_skills": ["kubernetes"]}
        job = _job(
            description=(
                "Platform engineer role running k8s clusters in production, "
                "with full ownership of the container platform and its tooling."
            )
        )
        result = compute_relevance(job, profile)
        self.assertIn("Must-have skill: kubernetes", result["reasons"])

    def test_unmatched_must_skill_no_bonus(self):
        profile = {**PROFILE, "must_have_skills": ["golang"]}
        job = _job(description="only python and aws here, no go anywhere in this text")
        result = compute_relevance(job, profile)
        self.assertNotIn("Must-have skill:", "; ".join(result["reasons"]))

    def test_bonus_capped(self):
        profile = {**PROFILE, "must_have_skills": ["aws", "docker", "kubernetes", "terraform"]}
        result = compute_relevance(_job(), profile)
        # 4 skills × 2 = 8 → capped at 6. Without the cap it would exceed.
        self.assertLessEqual(result["score"], 100.0)


class TestSoftModeCap(unittest.TestCase):
    def test_soft_flagged_job_capped(self):
        profile = {**PROFILE, "must_have_skills": ["kubernetes", "terraform"]}
        soft = compute_relevance(_job(must_skills_soft=True), profile)
        self.assertLessEqual(soft["score"], 45.0)
        self.assertIn("Below must-skill threshold", "; ".join(soft["reasons"]))

    def test_hard_match_above_cap(self):
        profile = {**PROFILE, "must_have_skills": ["kubernetes", "terraform"]}
        hard = compute_relevance(_job(), profile)["score"]
        self.assertGreater(hard, 45.0)


class TestAiEligible(unittest.TestCase):
    def test_enriched_eligible(self):
        self.assertTrue(ai_eligible(_job(data_quality="full")))
        self.assertTrue(ai_eligible(_job(data_quality="partial")))

    def test_snippet_not_eligible(self):
        self.assertFalse(ai_eligible(_job(data_quality="snippet", description="")))
        self.assertFalse(ai_eligible(_job(data_quality="snippet", description="short")))

    def test_no_flag_but_substantial_description(self):
        self.assertTrue(ai_eligible(_job()))
        self.assertFalse(ai_eligible(_job(description="tiny")))


class TestFlatlineGuard(unittest.TestCase):
    def test_flat_scores_detected(self):
        self.assertTrue(detect_flatline([70.0] * 15))
        self.assertTrue(detect_flatline([69.0, 69.5, 70.0, 70.0] + [70.0] * 11))

    def test_spread_scores_not_flat(self):
        scores = [
            55.0,
            58.0,
            60.0,
            62.0,
            64.0,
            66.0,
            68.0,
            70.0,
            72.0,
            74.0,
            76.0,
            78.0,
            80.0,
            82.0,
            84.0,
            86.0,
            88.0,
            90.0,
            92.0,
            100.0,
        ]
        self.assertFalse(detect_flatline(scores))

    def test_too_few_scores_not_flat(self):
        self.assertFalse(detect_flatline([70.0, 71.0]))
        self.assertFalse(detect_flatline([70.0] * 10))

    def test_normalize_stretches_flat_distribution(self):
        scores = [40.0, 45.0, 48.0, 50.0]
        out = normalize_scores(scores)
        self.assertEqual(min(out), 5.0)
        self.assertEqual(max(out), 100.0)
        self.assertEqual(sorted(out), out)  # order preserved

    def test_normalize_flat_single_value_unchanged(self):
        self.assertEqual(normalize_scores([70.0, 70.0]), [70.0, 70.0])
        self.assertEqual(normalize_scores([70.0]), [70.0])


class TestProvenanceStamping(unittest.TestCase):
    """Result-level provenance is stamped onto every row at ingest (§6.2)."""

    @mock.patch("matcha.main.check_serpapi_available", return_value=False)
    def test_rows_inherit_result_quality_and_backend(self, _mock_serpapi):
        from matcha.main import SCRAPER_DEFS, search_jobs
        from matcha.models import ScraperResult

        def fake_scraper(query, location, days=None, max_pages=1, **kwargs):
            del query, location, days, max_pages, kwargs
            return ScraperResult(
                jobs=[{"title": "Platform Engineer", "company": "Acme", "url": "u"}],
                source="Fake",
                backend="api",
                data_quality="full",
            )

        with mock.patch.dict(SCRAPER_DEFS, {"Fake": fake_scraper}, clear=True):
            jobs, _, _ = search_jobs(["platform"], "Pune", days=7, max_pages=1)
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["data_quality"], "full")
        self.assertEqual(jobs[0]["backend"], "api")

    @mock.patch("matcha.main.check_serpapi_available", return_value=False)
    def test_explicit_row_flag_not_overwritten(self, _mock_serpapi):
        from matcha.main import SCRAPER_DEFS, search_jobs
        from matcha.models import ScraperResult

        def fake_scraper(query, location, days=None, max_pages=1, **kwargs):
            del query, location, days, max_pages, kwargs
            return ScraperResult(
                jobs=[
                    {
                        "title": "Platform Engineer",
                        "company": "Acme",
                        "url": "u",
                        "data_quality": "snippet",
                    }
                ],
                source="Fake",
                backend="api",
                data_quality="full",
            )

        with mock.patch.dict(SCRAPER_DEFS, {"Fake": fake_scraper}, clear=True):
            jobs, _, _ = search_jobs(["platform"], "Pune", days=7, max_pages=1)
        # setdefault: the row's explicit snippet flag wins over the result's full.
        self.assertEqual(jobs[0]["data_quality"], "snippet")


class TestProvenanceTags(unittest.TestCase):
    def test_full_with_unknown_salary(self):
        job = _job(data_quality="full", salary_tag="unknown")
        self.assertEqual(provenance_tags(job), ["full", "salary?"])

    def test_snippet_with_unknown_age(self):
        job = _job(data_quality="snippet", age="unknown")
        self.assertEqual(provenance_tags(job), ["snippet", "age?"])

    def test_no_quality_no_tags(self):
        self.assertEqual(provenance_tags(_job()), [])

    def test_partial(self):
        self.assertEqual(provenance_tags(_job(data_quality="partial")), ["partial"])


if __name__ == "__main__":
    unittest.main()
