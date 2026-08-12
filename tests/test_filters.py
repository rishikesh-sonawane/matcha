"""Tests for the central filter pipeline (strategy §7, Phase 2).

Covers each stage (quality → age → must-skills → location → salary), the
fixed order + counts in apply_filters, build_filter_summary rendering, the
unknown-age / unknown-salary tagging ([age?] / [salary?]), and the failproof
per-stage isolation. Hermetic — no network, no config.
"""

import os
import sys
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from matcha.filters import (
    FilterReport,
    apply_filters,
    build_filter_summary,
    filter_notes,
    provenance_tags,
)
from matcha.normalization import normalize_jobs


def _job(**overrides):
    job = {
        "title": "Platform Engineer",
        "company": "Acme",
        "location": "Pune",
        "salary": "₹28-35 LPA",
        "listed": "2 days ago",
        "description": "aws docker kubernetes terraform",
        "url": "https://example.com/jobs/1",
        "source": "Indeed",
    }
    job.update(overrides)
    return job


def _normalized(**overrides):
    return normalize_jobs([_job(**overrides)])[0]


class TestQualityFilter(unittest.TestCase):
    def test_empty_title_dropped(self):
        kept, report = apply_filters([_job(title=""), _job()], {})
        self.assertEqual(len(kept), 1)
        self.assertEqual(report[0].dropped, 1)

    def test_title_and_company_placeholder_dropped(self):
        job = _job(title="naukri.com", company="Naukri", url="https://www.naukri.com/x")
        kept, _ = apply_filters([job], {})
        self.assertEqual(len(kept), 0)

    def test_placeholder_company_alone_tagged_partial(self):
        job = _job(company="Naukri")
        kept, _ = apply_filters([job], {})
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0].get("data_quality"), "partial")

    def test_placeholder_title_with_real_company_kept_f12(self):
        # F-12: only title AND company BOTH placeholder are dropped (never
        # over-drop). A placeholder title with a real company must survive.
        for title in ("Unknown", "N/A", "TBD"):
            kept, _ = apply_filters([_job(title=title)], {})
            self.assertEqual(len(kept), 1, f"placeholder title {title!r} + real company kept")

    def test_tracking_url_without_job_key_dropped(self):
        job = _job(url="https://in.indeed.com/rc/clk?jk=abc")
        kept, _ = apply_filters([job], {})
        self.assertEqual(len(kept), 0)

    def test_tracking_url_with_job_key_kept(self):
        job = _job(url="https://in.indeed.com/rc/clk?jk=abc", job_key="abc")
        kept, _ = apply_filters([job], {})
        self.assertEqual(len(kept), 1)

    def test_missing_url_dropped(self):
        kept, _ = apply_filters([_job(url="")], {})
        self.assertEqual(len(kept), 0)

    def test_junk_nav_titles_dropped(self):
        # Listing-page/navigation noise leaked by snippet fallbacks — never
        # real postings (user-reported: "Link to naukri.com", "It Jobs", …).
        for title in (
            "Link to naukri.com",
            "It Jobs",
            "It",
            "Developer Tcs Jobs",
            "DevOps - Jobs",
            "Jobs in Pune",
            "Apply Now",
            "Careers",
            "Top companies hiring for aws devops engineer",
            "Companies hiring for devops engineers",
            # Session 19: Naukri aggregate listing pages surfaced as jobs
            "Techblocks Careers",
            "Acme Careers",
            "Walkin Drives",
            "Walk-in Drive",
            "Walk In Interview",
            # Session 21: Naukri masked/placeholder postings + RemoteOK
            # placeholder titles leaked into results (user-reported)
            "Job Listings 040826031923",
            "Job Listings",
            "Join Our Team",
            "Join Our Team at Acme",
        ):
            kept, reports = apply_filters([_job(title=title)], {})
            self.assertEqual(len(kept), 0, f"junk title {title!r} should be dropped")
            self.assertEqual(reports[0].dropped, 1)

    def test_legit_titles_not_dropped(self):
        for title in (
            "AWS DevOps Engineer",
            "Staff DevOps Engineer",
            "Platform Engineer",
            "IT Support Engineer",
            "Acme Hiring for DevOps Engineer",  # real employer-posted title
        ):
            kept, _ = apply_filters([_job(title=title)], {})
            self.assertEqual(len(kept), 1, f"legit title {title!r} should be kept")

    def test_url_as_title_dropped(self):
        # Session 26: workday/intranet listing pages leaked as titles.
        for title in (
            "ptc.wd1.myworkdayjobs.com/PTC/job/Pune",
            "intel.wd1.myworkdayjobs.com/en",
            "www.example.com/jobs/123",
        ):
            kept, _ = apply_filters([_job(title=title)], {})
            self.assertEqual(len(kept), 0, f"URL-as-title {title!r} should be dropped")

    def test_skill_list_fragment_title_dropped(self):
        # Session 26: scraped description fragments leaked as titles — a
        # 3+-comma skill list with no role word is never a real posting.
        for title in (
            "AWS Cloud, EKS, Terraform, Gitlab CI/CD, Scripting, Python",
            "GO, RESTful API, AWS, Terraform, Docker, PostgreSQL",
        ):
            kept, _ = apply_filters([_job(title=title)], {})
            self.assertEqual(len(kept), 0, f"fragment title {title!r} should be dropped")

    def test_role_comma_titles_not_dropped(self):
        # Legit long titles with commas/parens name the ROLE (reviewer-caught
        # Session 26: role words past char 60 must not false-positive).
        for title in (
            "Software Engineer (Devops - Jenkins, Terraform, Kubernetes, AWS (EC2), CI/CD )",
            "Senior Engineer, Site Reliability [T500-28287]",
            "Cloud & DevOps Engineer",
            "Remote Senior — AWS, Terraform, Kubernetes, Docker, CI/CD Engineer",
            "Senior DevOps Engineer in Bengaluru, Karnataka, India",
        ):
            kept, _ = apply_filters([_job(title=title)], {})
            self.assertEqual(len(kept), 1, f"role title {title!r} should be kept")

    def test_single_word_title_equal_to_company_dropped(self):
        # Session 27: a single-word title that IS the company name is a
        # page-title artifact ("COMPLY" / "Lever" from careers pages rendered
        # as jobs), never a posting — the title must name a role.
        for company in ("COMPLY", "Lever"):
            kept, reports = apply_filters([_job(title=company, company=company)], {})
            self.assertEqual(len(kept), 0, f"company-name title {company!r} should be dropped")
            self.assertEqual(reports[0].dropped, 1)

    def test_multiword_title_equal_to_company_kept(self):
        # "Nagarro Digital" as a company page is still multiword — a real
        # posting titled like a division must not be over-dropped (only the
        # single-word page-title artifact is dropped).
        kept, _ = apply_filters([_job(title="COMPLY Software", company="COMPLY Software")], {})
        self.assertEqual(len(kept), 1)
        kept, _ = apply_filters([_job(title="AWS DevOps Engineer", company="AWS DevOps Engineer")], {})
        self.assertEqual(len(kept), 1)


class TestAgeFilter(unittest.TestCase):
    def test_old_job_dropped(self):
        jobs = [_normalized(listed="2 days ago"), _normalized(listed="60 days ago")]
        kept, reports = apply_filters(jobs, {}, {"days": 7})
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0]["title"], "Platform Engineer")
        self.assertEqual(reports[1].dropped, 1)

    def test_unknown_age_tagged_and_kept(self):
        job = _normalized(listed="")
        kept, reports = apply_filters([job], {}, {"days": 7})
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0].get("age"), "unknown")
        self.assertEqual(reports[1].unknown, 1)

    def test_strict_age_drops_unknown(self):
        job = _normalized(listed="")
        kept, reports = apply_filters([job], {}, {"days": 7, "strict_age": True})
        self.assertEqual(len(kept), 0)
        self.assertEqual(reports[1].dropped, 1)

    def test_days_zero_today_only(self):
        job = _normalized(listed_epoch=int(time.time()) + 120, listed="just now")
        kept, _ = apply_filters([job], {}, {"days": 0})
        self.assertEqual(len(kept), 1)

    def test_days_zero_keeps_text_today(self):
        # "today" parses a few seconds before now — days=0 must still keep it
        # (one-day window, not cutoff=now), else today's listings get dropped.
        job = _normalized(listed="today")
        kept, _ = apply_filters([job], {}, {"days": 0})
        self.assertEqual(len(kept), 1)

    def test_days_zero_drops_older(self):
        job = _normalized(listed="2 days ago")
        kept, _ = apply_filters([job], {}, {"days": 0})
        self.assertEqual(len(kept), 0)


class TestMustSkillsFilter(unittest.TestCase):
    PROFILE = {"must_have_skills": ["kubernetes"]}

    def test_matching_skill_kept(self):
        kept, reports = apply_filters([_job()], self.PROFILE, {})
        self.assertEqual(len(kept), 1)
        self.assertEqual(reports[2].dropped, 0)

    def test_missing_skill_dropped(self):
        job = _job(description="nothing relevant here")
        kept, reports = apply_filters([job], self.PROFILE, {})
        self.assertEqual(len(kept), 0)
        self.assertEqual(reports[2].dropped, 1)

    def test_synonym_k8s(self):
        job = _job(description="running k8s clusters")
        kept, _ = apply_filters([job], self.PROFILE, {})
        self.assertEqual(len(kept), 1)

    def test_synonym_aws_amazon_web_services(self):
        job = _job(description="Amazon Web Services certified")
        kept, _ = apply_filters([job], {"must_have_skills": ["aws"]}, {})
        self.assertEqual(len(kept), 1)

    def test_min_must_matches(self):
        profile = {"must_have_skills": ["kubernetes", "terraform"]}
        job = _job(description="kubernetes only, no IaC tools")
        kept, _ = apply_filters([job], profile, {"min_must_matches": 2})
        self.assertEqual(len(kept), 0)

    def test_soft_mode_flags_instead_of_drop(self):
        job = _job(description="nothing relevant here")
        kept, _ = apply_filters([job], self.PROFILE, {"soft_must_skills": True})
        self.assertEqual(len(kept), 1)
        self.assertTrue(kept[0].get("must_skills_soft"))

    def test_no_must_skills_keeps_everything(self):
        kept, reports = apply_filters([_job(), _job()], {}, {})
        self.assertEqual(len(kept), 2)
        self.assertEqual(reports[2].dropped, 0)


class TestLocationFilter(unittest.TestCase):
    def test_city_match_kept(self):
        kept, _ = apply_filters([_normalized(location="Pune")], {"location": "Pune"}, {})
        self.assertEqual(len(kept), 1)

    def test_city_synonym_match(self):
        kept, _ = apply_filters([_normalized(location="Bangalore")], {"location": "Bengaluru"}, {})
        self.assertEqual(len(kept), 1)

    def test_region_fallback(self):
        kept, _ = apply_filters(
            [_normalized(location="Nashik, Maharashtra")], {"location": "Pune"}, {}
        )
        self.assertEqual(len(kept), 1)

    def test_other_city_dropped(self):
        kept, _ = apply_filters([_normalized(location="Chennai")], {"location": "Pune"}, {})
        self.assertEqual(len(kept), 0)

    def test_no_profile_location_keeps_all(self):
        kept, _ = apply_filters([_normalized(location="Chennai")], {"location": ""}, {})
        self.assertEqual(len(kept), 1)

    def test_remote_kept_when_acceptable(self):
        kept, _ = apply_filters(
            [_normalized(location="Remote")],
            {"location": "Pune", "remote_preference": "remote"},
            {},
        )
        self.assertEqual(len(kept), 1)

    def test_remote_dropped_for_onsite_user(self):
        kept, _ = apply_filters(
            [_normalized(location="Remote")],
            {"location": "Pune", "remote_preference": "onsite"},
            {},
        )
        self.assertEqual(len(kept), 0)

    def test_force_remote_only(self):
        jobs = [_normalized(location="Remote"), _normalized(location="Pune")]
        kept, _ = apply_filters(jobs, {"location": "Pune"}, {"remote": True})
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0]["location"], "Remote")

    def test_remote_drop_reports_actionable_hint(self):
        kept, reports = apply_filters([_normalized(location="Remote")], {"location": "Pune"}, {})
        self.assertEqual(len(kept), 0)
        notes = filter_notes(reports)
        self.assertTrue(notes)
        self.assertIn("remote", notes[0].lower())
        self.assertIn("remote_preference", notes[0])

    def test_remote_kept_no_hint(self):
        kept, reports = apply_filters(
            [_normalized(location="Remote")],
            {"location": "Pune", "remote_preference": "remote"},
            {},
        )
        self.assertEqual(len(kept), 1)
        self.assertEqual(filter_notes(reports), [])

    def test_unknown_location_kept(self):
        kept, _ = apply_filters([_normalized(location="")], {"location": "Pune"}, {})
        self.assertEqual(len(kept), 1)

    def test_unknown_location_tagged_loca(self):
        # Session 25: unknown-location rows must be HONEST — tagged [loc?]
        # (they were silently kept before, which is how location-less junk
        # like "LMI Government Consulting" looked like a legit match).
        kept, _ = apply_filters([_normalized(location="")], {"location": "Pune"}, {})
        self.assertEqual(kept[0].get("loc_tag"), "unknown")
        self.assertIn("loc?", provenance_tags(kept[0]))

    def test_strict_location_drops_unknown(self):
        kept, reports = apply_filters(
            [_normalized(location="")], {"location": "Pune"}, {"strict_location": True}
        )
        self.assertEqual(len(kept), 0)
        notes = filter_notes(reports)
        self.assertTrue(notes)
        self.assertIn("strict_location", notes[0])

    def test_multi_city_profile_keeps_each_city(self):
        # Session 25 (user-reported): a multi-city preference "Hyderabad, Pune,
        # Bengaluru" was reduced to ONE arbitrary city by normalize_city, so
        # the user's other cities were silently dropped. Every city must match.
        jobs = normalize_jobs(
            [
                _job(title="H", location="Hyderabad, Telangana, India"),
                _job(title="P", location="Pune, Maharashtra, India"),
                _job(title="B", location="Bengaluru, Karnataka, India"),
            ]
        )
        kept, _ = apply_filters(jobs, {"location": "Hyderabad, Pune, Bengaluru"}, {})
        self.assertEqual(sorted(j["title"] for j in kept), ["B", "H", "P"])

    def test_multi_city_profile_still_drops_other_cities(self):
        jobs = normalize_jobs([_job(location="Chennai, Tamil Nadu, India")])
        kept, _ = apply_filters(jobs, {"location": "Hyderabad, Pune, Bengaluru"}, {})
        self.assertEqual(len(kept), 0)

    def test_country_suffix_does_not_shadow_city(self):
        # Session 25: normalize_city("Pune, Maharashtra, India") must be Pune,
        # not India — the generic country key was winning by length.
        kept, _ = apply_filters(
            [_normalized(location="Pune, Maharashtra, India")], {"location": "Pune"}, {}
        )
        self.assertEqual(len(kept), 1)

    def test_remote_location_accepts_remote_jobs(self):
        kept, _ = apply_filters([_normalized(location="Remote")], {"location": "Remote"}, {})
        self.assertEqual(len(kept), 1)

    def test_country_level_preference_accepts_any_known_city(self):
        # Session 25 (reviewer-caught regression): a country-level preference
        # ("India") used to match every Indian-city job because the old
        # normalize_city returned "India" for all of them; the city-aware
        # rewrite must keep that behavior.
        for city in ("Pune, Maharashtra, India", "Hyderabad, Telangana, India", "Chennai"):
            kept, _ = apply_filters([_normalized(location=city)], {"location": "India"}, {})
            self.assertEqual(len(kept), 1, f"{city!r} should match country-level India")

    def test_country_level_preference_unknown_city_tagged(self):
        # Unknown city under "India": kept but honestly tagged [loc?] (default
        # strict_location=False) — only strict mode drops it.
        kept, _ = apply_filters([_normalized(location="")], {"location": "India"}, {})
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0].get("loc_tag"), "unknown")
        self.assertIn("loc?", provenance_tags(kept[0]))
        kept, _ = apply_filters(
            [_normalized(location="")], {"location": "India"}, {"strict_location": True}
        )
        self.assertEqual(len(kept), 0)

    def test_strict_location_and_remote_notes_combine(self):
        jobs = [_normalized(location="Remote"), _normalized(location="")]
        kept, reports = apply_filters(jobs, {"location": "Pune"}, {"strict_location": True})
        self.assertEqual(len(kept), 0)
        notes = filter_notes(reports)
        self.assertTrue(notes)
        self.assertIn("remote", notes[0].lower())
        self.assertIn("strict_location", notes[0])


class TestSalaryFilter(unittest.TestCase):
    def test_above_floor_kept(self):
        kept, _ = apply_filters(
            [_normalized(salary="₹28-35 LPA")], {"min_salary": 20}, {"min_salary": 20}
        )
        self.assertEqual(len(kept), 1)

    def test_below_floor_dropped(self):
        kept, reports = apply_filters(
            [_normalized(salary="₹10-12 LPA")], {"min_salary": 20}, {"min_salary": 20}
        )
        self.assertEqual(len(kept), 0)
        self.assertEqual(reports[4].dropped, 1)

    def test_unknown_salary_tagged_and_kept(self):
        kept, reports = apply_filters(
            [_normalized(salary="Not Disclosed")], {"min_salary": 20}, {"min_salary": 20}
        )
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0].get("salary_tag"), "unknown")
        self.assertEqual(reports[4].unknown, 1)

    def test_drop_unknown_salary(self):
        kept, _ = apply_filters(
            [_normalized(salary="Not Disclosed")],
            {"min_salary": 20},
            {"min_salary": 20, "drop_unknown_salary": True},
        )
        self.assertEqual(len(kept), 0)

    def test_no_floor_keeps_everything(self):
        kept, reports = apply_filters([_normalized(salary="₹10-12 LPA")], {}, {})
        self.assertEqual(len(kept), 1)
        self.assertEqual(reports[4].dropped, 0)


class TestPipeline(unittest.TestCase):
    def test_fixed_order_and_counts(self):
        jobs = normalize_jobs(
            [
                _job(title="", url=""),  # quality
                _job(listed="60 days ago"),  # age
                _job(description="no skills"),  # must-skills
                _job(location="Chennai"),  # location
                _job(salary="₹4 LPA"),  # salary
                _job(),  # survives everything
            ]
        )
        profile = {
            "location": "Pune",
            "must_have_skills": ["kubernetes"],
            "min_salary": 20,
        }
        kept, reports = apply_filters(jobs, profile, {"days": 7, "min_salary": 20})
        self.assertEqual(
            [r.name for r in reports], ["quality", "age", "must-skills", "location", "salary"]
        )
        self.assertEqual([r.dropped for r in reports], [1, 1, 1, 1, 1])
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0]["title"], "Platform Engineer")

    def test_summary_renders_dropped_and_unknown(self):
        jobs = normalize_jobs([_job(listed=""), _job(listed="60 days ago")])
        _, reports = apply_filters(jobs, {"must_have_skills": []}, {"days": 7})
        summary = build_filter_summary(reports)
        self.assertIn("age −1", summary)
        self.assertIn("age ?1", summary)

    def test_summary_empty_when_nothing_cut(self):
        _, reports = apply_filters(normalize_jobs([_job()]), {}, {})
        self.assertEqual(build_filter_summary(reports), "")

    def test_stage_failure_isolated(self):
        # profile.min_salary is unhashable → salary stage explodes on int()
        jobs = [_job(), _job()]
        kept, reports = apply_filters(jobs, {"min_salary": "x"}, {})
        self.assertEqual(len(kept), 2)  # earlier stages unaffected, batch survives
        self.assertTrue(reports[-1].reason.startswith("stage failed"))

    def test_filter_report_bool(self):
        self.assertTrue(FilterReport("x", 5, 1))
        self.assertTrue(FilterReport("x", 5, 0, unknown=2))
        self.assertFalse(FilterReport("x", 5, 0))


if __name__ == "__main__":
    unittest.main()
