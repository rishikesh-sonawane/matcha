"""Tests for canonical job normalization (strategy §7/§14, Phase 2).

Covers listed_epoch parsing (relative, ISO-8601, epoch int, unknown),
salary_int LPA parsing (ranges, lacs, crores, Indian amounts, monthly, K,
experience-not-salary), city/region synonym normalization, remote_ok
detection, and the in-place normalize_job wiring. Hermetic — pure functions.
"""

import os
import sys
import time
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from matcha.normalization import (
    find_city_in_text,
    is_remote,
    normalize_city,
    normalize_job,
    normalize_jobs,
    normalize_listed_epoch,
    normalize_region,
    normalize_salary_int,
    search_location,
)


class TestListedEpoch(unittest.TestCase):
    def test_relative_days_ago(self):
        epoch = normalize_listed_epoch({"listed": "5 days ago"})
        self.assertIsInstance(epoch, int)
        self.assertLess(abs(epoch - (time.time() - 5 * 86400)), 600)

    def test_relative_week_ago(self):
        epoch = normalize_listed_epoch({"listed": "2 weeks ago"})
        self.assertLess(abs(epoch - (time.time() - 14 * 86400)), 600)

    def test_relative_month_ago(self):
        epoch = normalize_listed_epoch({"listed": "1 month ago"})
        self.assertLess(abs(epoch - (time.time() - 30 * 86400)), 600)

    def test_just_now_and_today(self):
        just_now = normalize_listed_epoch({"listed": "Posted just now"})
        self.assertLess(abs(just_now - time.time()), 120)
        today = normalize_listed_epoch({"listed": "Today"})
        self.assertLess(abs(today - time.time()), 3600 * 2)

    def test_iso_date(self):
        dt = datetime(2026, 8, 1, tzinfo=timezone.utc)
        epoch = normalize_listed_epoch({"listed": "2026-08-01"})
        self.assertEqual(epoch, int(dt.timestamp()))

    def test_iso_datetime_with_z(self):
        dt = datetime(2026, 8, 1, 12, 30, tzinfo=timezone.utc)
        epoch = normalize_listed_epoch({"listed": "2026-08-01T12:30:00Z"})
        self.assertEqual(epoch, int(dt.timestamp()))

    def test_month_name_date(self):
        past = datetime.now() - timedelta(days=5)
        epoch = normalize_listed_epoch({"listed": f"Posted: {past.strftime('%B %d, %Y')}"})
        self.assertLess(abs(epoch - past.timestamp()), 86400 * 2)

    def test_epoch_int_passthrough(self):
        self.assertEqual(normalize_listed_epoch({"epoch": 1750000000}), 1750000000)

    def test_listed_epoch_key_wins(self):
        self.assertEqual(normalize_listed_epoch({"listed": "5 days ago", "listed_epoch": 123}), 123)

    def test_unknown_returns_none(self):
        self.assertIsNone(normalize_listed_epoch({}))
        self.assertIsNone(normalize_listed_epoch({"listed": "N/A"}))
        self.assertIsNone(normalize_listed_epoch({"listed": "some random text"}))


class TestSalaryInt(unittest.TestCase):
    def test_lpa_range(self):
        self.assertEqual(normalize_salary_int("₹28-35 LPA"), 35)
        self.assertEqual(normalize_salary_int("8-13 LPA"), 13)

    def test_lacs(self):
        self.assertEqual(normalize_salary_int("₹7-12 Lacs"), 12)
        self.assertEqual(normalize_salary_int("5-8 lakhs"), 8)

    def test_crore(self):
        self.assertEqual(normalize_salary_int("₹1.2 Cr"), 120)
        self.assertEqual(normalize_salary_int("₹0.5-1 Cr"), 100)

    def test_annual_indian_amounts(self):
        self.assertEqual(normalize_salary_int("₹8,00,000 - ₹12,00,000"), 12)

    def test_monthly_amount(self):
        self.assertEqual(normalize_salary_int("₹1,00,000 - ₹1,50,000 a month"), 18)
        self.assertEqual(normalize_salary_int("₹1,00,000 - ₹1,50,000 per month"), 18)

    def test_monthly_thousands(self):
        self.assertEqual(normalize_salary_int("₹30-40K per month"), 5)
        self.assertEqual(normalize_salary_int("₹50K - ₹60K per month"), 6)

    def test_single_lpa(self):
        self.assertEqual(normalize_salary_int("₹10 LPA"), 10)
        self.assertEqual(normalize_salary_int("₹10L"), 10)

    def test_experience_is_not_salary(self):
        self.assertIsNone(normalize_salary_int("8 to 13 Years"))
        self.assertIsNone(normalize_salary_int("3-6 Years"))

    def test_unknown(self):
        self.assertIsNone(normalize_salary_int("Not Disclosed"))
        self.assertIsNone(normalize_salary_int(""))
        self.assertIsNone(normalize_salary_int(None))


class TestCityRegionRemote(unittest.TestCase):
    def test_city_synonyms(self):
        self.assertEqual(normalize_city("Bengaluru, India"), "Bengaluru")
        self.assertEqual(normalize_city("Bangalore"), "Bengaluru")
        self.assertEqual(normalize_city("New Delhi, IN"), "Delhi")
        self.assertEqual(normalize_city("Gurgaon"), "Gurugram")
        self.assertEqual(normalize_city("Trivandrum"), "Thiruvananthapuram")
        self.assertEqual(normalize_city("Hyderabad, Telangana"), "Hyderabad")

    def test_country_suffix_never_shadows_city(self):
        # Session 25 (user-reported): "Pune, Maharashtra, India" must be Pune —
        # the generic "india" key was winning by raw length and every such job
        # was mis-normalized to "India", silently dropping real city matches.
        self.assertEqual(normalize_city("Pune, Maharashtra, India"), "Pune")
        self.assertEqual(normalize_city("Hyderabad, Telangana, India"), "Hyderabad")
        self.assertEqual(normalize_city("Bengaluru, Karnataka, India"), "Bengaluru")
        self.assertEqual(normalize_city("Mumbai, Maharashtra, India"), "Mumbai")
        self.assertEqual(normalize_city("Chennai, Tamil Nadu, India"), "Chennai")

    def test_city_remote(self):
        self.assertEqual(normalize_city("Remote"), "Remote")
        self.assertEqual(normalize_city("Work from home"), "Remote")

    def test_two_real_cities_earliest_wins(self):
        # Session 25 (reviewer-caught): the tie-break must be positional — the
        # city mentioned FIRST in the string wins, not dict-insertion order.
        self.assertEqual(normalize_city("Hyderabad, Bengaluru"), "Hyderabad")
        self.assertEqual(normalize_city("Pune, Mumbai"), "Pune")
        self.assertEqual(normalize_city("Bengaluru, Hyderabad"), "Bengaluru")

    def test_city_empty(self):
        self.assertEqual(normalize_city(""), "")
        self.assertEqual(normalize_city(None), "")

    def test_region(self):
        self.assertEqual(normalize_region("Pune, Maharashtra"), "Maharashtra")
        self.assertEqual(normalize_region("Gurgaon"), "Delhi NCR")
        self.assertEqual(normalize_region("Bengaluru"), "Karnataka")
        self.assertEqual(normalize_region(""), "")

    def test_is_remote(self):
        self.assertTrue(is_remote("Remote"))
        self.assertTrue(is_remote("Work from home"))
        self.assertTrue(is_remote("Pune", "Hybrid"))
        self.assertTrue(is_remote("Pune", "Remote"))
        self.assertFalse(is_remote("Pune", "On-site"))
        self.assertFalse(is_remote("Pune"))


class TestFindCityInText(unittest.TestCase):
    """Session 28: Exa/DDGS snippets contain "in Managing cloud infra"-style
    phrases that loose regex extractors misread as locations — a known-city
    scan must win over them so the location filter keeps the posting."""

    def test_known_city_in_free_text(self):
        self.assertEqual(find_city_in_text("Job Details | Pune AWS DevOps"), "Pune")
        self.assertEqual(find_city_in_text("Location: Bengaluru, India"), "Bengaluru")
        self.assertEqual(find_city_in_text("Noida, India"), "Noida")

    def test_loose_phrase_not_mistaken_for_city(self):
        # The regex-extractor trap: "in Managing cloud infrastructure" — no
        # known city means no location, NOT a bogus one.
        self.assertEqual(find_city_in_text("in Managing cloud infrastructure"), "")
        self.assertEqual(find_city_in_text("we are hiring a DevOps engineer in Pune"), "Pune")

    def test_remote_marker(self):
        self.assertEqual(find_city_in_text("Remote / Unspecified"), "Remote")
        self.assertEqual(find_city_in_text("Work from home OK"), "Remote")

    def test_specific_city_beats_generic(self):
        self.assertEqual(find_city_in_text("Pune, Maharashtra, India"), "Pune")

    def test_ambiguous_keys_excluded(self):
        # Session 28 (reviewer-caught): "ncr" matches the NCR Corp employer,
        # "virtual" matches "virtual machines" in descriptions, "salem" is a
        # common English word — none may resolve to a location in free text.
        self.assertEqual(find_city_in_text("NCR Corporation is hiring engineers"), "")
        self.assertEqual(find_city_in_text("manage virtual machines and CI/CD"), "")
        self.assertEqual(find_city_in_text("salem is a fine city to visit"), "")
        # But a REAL city still wins over them.
        self.assertEqual(find_city_in_text("NCR Corporation Pune hiring"), "Pune")

    def test_empty(self):
        self.assertEqual(find_city_in_text(""), "")
        self.assertEqual(find_city_in_text(None), "")


class TestSearchLocation(unittest.TestCase):
    """Session 27: sources accept ONE location string — a multi-city
    preference must be reduced to a broad source-level location."""

    def test_single_city_passthrough(self):
        self.assertEqual(search_location("Pune"), "Pune")
        self.assertEqual(search_location(""), "")
        self.assertEqual(search_location("Remote"), "Remote")

    def test_all_indian_cities_search_country_wide(self):
        self.assertEqual(search_location("Pune, Bengaluru, Hyderabad"), "India")
        self.assertEqual(search_location("Hyderabad, Pune & Bengaluru"), "India")
        self.assertEqual(search_location("Pune, Remote"), "India")

    def test_non_indian_part_falls_back_to_first(self):
        self.assertEqual(search_location("Pune, London"), "Pune")
        self.assertEqual(search_location("New York, Pune"), "New York")

    def test_garbage_string_falls_back_to_first(self):
        # Session 27: pasted paragraphs must never reach sources as-is — the
        # first token wins and the location filter decides the rest.
        self.assertEqual(
            search_location("Enterprise, Docker, Linux, and Datadog. Proven track"),
            "Enterprise",
        )


class TestNormalizeJob(unittest.TestCase):
    def test_normalize_job_adds_fields(self):
        job = {
            "title": "Dev",
            "company": "Co",
            "location": "Bengaluru",
            "salary": "₹28-35 LPA",
            "listed": "3 days ago",
            "workplace_type": "Hybrid",
            "url": "https://x.com",
        }
        out = normalize_job(job)
        self.assertIs(out, job)  # in place
        self.assertEqual(job["salary_int"], 35)
        self.assertEqual(job["city"], "Bengaluru")
        self.assertEqual(job["region"], "Karnataka")
        self.assertTrue(job["remote_ok"])
        self.assertEqual(job["workplace"], "Hybrid")
        self.assertIsNotNone(job["listed_epoch"])

    def test_normalize_jobs_tolerates_garbage(self):
        jobs = [{"title": "A"}, 42, None, {"title": "B", "salary": "₹10 LPA"}]
        out = normalize_jobs(jobs)
        self.assertIs(out, jobs)
        self.assertEqual(len(jobs), 4)


if __name__ == "__main__":
    unittest.main()
