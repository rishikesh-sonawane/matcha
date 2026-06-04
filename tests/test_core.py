import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import unittest
from profile import suggest_title

from ai import _extract_json
from main import _normalize, deduplicate
from matcher import compute_relevance, tokenize
from scrapers.indeed import resolve_indeed_url


class TestNormalize(unittest.TestCase):
    def test_lowercase(self):
        self.assertEqual(_normalize("Platform Engineer"), "platform engineer")

    def test_strip_roman_numerals(self):
        self.assertEqual(_normalize("Engineer II"), "engineer")
        self.assertEqual(_normalize("Engineer III"), "engineer")
        self.assertEqual(_normalize("Engineer IV"), "engineer")

    def test_strip_seniority_abbrev(self):
        self.assertEqual(_normalize("Sr Engineer"), "engineer")
        self.assertEqual(_normalize("Jr Engineer"), "engineer")

    def test_remove_punctuation(self):
        self.assertEqual(_normalize("Full-Stack, Senior!"), "fullstack senior")

    def test_collapse_whitespace(self):
        self.assertEqual(_normalize("  Platform   Engineer  "), "platform engineer")

    def test_empty_string(self):
        self.assertEqual(_normalize(""), "")


class TestDeduplicate(unittest.TestCase):
    def test_exact_duplicate(self):
        jobs = [
            {"title": "Platform Engineer", "company": "Barclays"},
            {"title": "Platform Engineer", "company": "Barclays"},
        ]
        self.assertEqual(len(deduplicate(jobs)), 1)

    def test_roman_vs_digit(self):
        jobs = [
            {"title": "Platform Engineer II", "company": "Barclays"},
            {"title": "Platform Engineer 2", "company": "Barclays"},
        ]
        self.assertEqual(len(deduplicate(jobs)), 1)

    def test_word_reordering(self):
        jobs = [
            {"title": "Senior Platform Engineer", "company": "Mastercard"},
            {"title": "Platform Engineer, Senior", "company": "Mastercard"},
        ]
        self.assertEqual(len(deduplicate(jobs)), 1)

    def test_different_jobs(self):
        jobs = [
            {"title": "Platform Engineer", "company": "Barclays"},
            {"title": "Backend Developer", "company": "Google"},
        ]
        self.assertEqual(len(deduplicate(jobs)), 2)

    def test_same_company_diff_role(self):
        jobs = [
            {"title": "DevOps Engineer", "company": "Amazon"},
            {"title": "SDE - AWS Platform", "company": "Amazon"},
        ]
        self.assertEqual(len(deduplicate(jobs)), 2)

    def test_company_variant(self):
        jobs = [
            {"title": "Platform Engineer", "company": "Mastercard"},
            {"title": "Platform Engineer", "company": "Mastercard Inc."},
        ]
        self.assertEqual(len(deduplicate(jobs)), 1)

    def test_sr_vs_senior(self):
        jobs = [
            {"title": "Sr Platform Engineer", "company": "Google"},
            {"title": "Senior Platform Engineer", "company": "Google"},
        ]
        self.assertEqual(len(deduplicate(jobs)), 1)

    def test_empty_fields(self):
        jobs = [
            {"title": "", "company": ""},
            {"title": "", "company": ""},
        ]
        self.assertEqual(len(deduplicate(jobs)), 1)

    def test_no_duplicates(self):
        jobs = [
            {"title": "Platform Engineer", "company": "A"},
            {"title": "DevOps Engineer", "company": "B"},
            {"title": "Cloud Engineer", "company": "C"},
        ]
        self.assertEqual(len(deduplicate(jobs)), 3)


class TestTokenize(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(tokenize("Platform Engineer"), {"platform", "engineer"})

    def test_lowercase(self):
        self.assertEqual(tokenize("DevOps"), {"devops"})

    def test_numbers(self):
        self.assertEqual(tokenize("C++"), {"c++"})
        # Note: + is not in [a-z0-9+#.]

    def test_empty(self):
        self.assertEqual(tokenize(""), set())

    def test_special_chars(self):
        self.assertEqual(tokenize("ci/cd python3"), {"ci", "cd", "python3"})


class TestComputeRelevance(unittest.TestCase):
    def setUp(self):
        self.profile = {
            "title": "Platform Engineer",
            "headline": "DevOps Engineer",
            "skills": ["aws", "docker", "kubernetes", "terraform", "ci/cd", "linux"],
            "experience": "4",
            "summary": "Platform and infrastructure engineer with cloud experience",
            "location": "Pune",
        }

    def test_perfect_match(self):
        job = {
            "title": "Platform Engineer",
            "company": "Barclays",
            "description": "aws docker kubernetes terraform ci/cd linux python",
            "location": "Pune, India",
        }
        result = compute_relevance(job, self.profile)
        self.assertGreaterEqual(result["score"], 70)
        self.assertTrue(len(result["reasons"]) > 0)

    def test_no_match(self):
        job = {
            "title": "Barista",
            "company": "Starbucks",
            "description": "making coffee serving customers",
            "location": "Mumbai",
        }
        result = compute_relevance(job, self.profile)
        self.assertLess(result["score"], 30)

    def test_partial_skill_match(self):
        job = {
            "title": "Cloud Engineer",
            "company": "Startup",
            "description": "aws terraform linux",
            "location": "Remote",
        }
        result = compute_relevance(job, self.profile)
        self.assertLess(result["score"], 70)
        self.assertGreater(result["score"], 10)

    def test_include_reasons(self):
        job = {
            "title": "Platform Engineer",
            "company": "TestCo",
            "description": "aws terraform ci/cd",
            "location": "Pune, India",
        }
        result = compute_relevance(job, self.profile)
        self.assertTrue(len(result["reasons"]) > 0)
        self.assertTrue(
            any("title" in r.lower() for r in result["reasons"])
            or any("skill" in r.lower() for r in result["reasons"])
        )

    def test_score_bounds(self):
        job = {
            "title": "x" * 100,
            "company": "y",
            "description": "z",
            "location": "antarctica",
        }
        result = compute_relevance(job, self.profile)
        self.assertGreaterEqual(result["score"], 0)
        self.assertLessEqual(result["score"], 100)


class TestResolveIndeedURL(unittest.TestCase):
    def test_rc_clk_resolution(self):
        url = "https://in.indeed.com/rc/clk?jk=abc123def&from=serp"
        resolved = resolve_indeed_url(url)
        self.assertEqual(resolved, "https://in.indeed.com/viewjob?jk=abc123def")

    def test_clean_url_unchanged(self):
        url = "https://in.indeed.com/viewjob?jk=abc123def"
        resolved = resolve_indeed_url(url)
        self.assertEqual(resolved, url)

    def test_non_indeed_url(self):
        url = "https://www.google.com"
        resolved = resolve_indeed_url(url)
        self.assertEqual(resolved, url)

    def test_pagead_clk_with_jk(self):
        url = "https://in.indeed.com/pagead/clk?jk=xyz789"
        resolved = resolve_indeed_url(url)
        self.assertEqual(resolved, "https://in.indeed.com/viewjob?jk=xyz789")

    def test_no_jk_param(self):
        url = "https://in.indeed.com/rc/clk?some=thing"
        resolved = resolve_indeed_url(url)
        self.assertEqual(resolved, url)

    def test_empty_url(self):
        self.assertEqual(resolve_indeed_url(""), "")


class TestSuggestTitle(unittest.TestCase):
    def test_devops_skills(self):
        skills = ["aws", "docker", "kubernetes", "terraform", "ansible", "ci/cd", "linux"]
        title = suggest_title(skills)
        self.assertEqual(title, "DevOps Engineer")

    def test_backend_skills(self):
        skills = ["python", "django", "flask", "postgresql", "sql"]
        title = suggest_title(skills)
        self.assertEqual(title, "Backend Developer")

    def test_frontend_skills(self):
        skills = ["javascript", "react", "html", "css", "frontend"]
        title = suggest_title(skills)
        self.assertEqual(title, "Frontend Developer")

    def test_empty_skills(self):
        self.assertIsNone(suggest_title([]))

    def test_unrecognized_skills(self):
        skills = ["cobol", "fortran", "punchcard"]
        self.assertIsNone(suggest_title(skills))


class TestExtractJSON(unittest.TestCase):
    def test_plain_json(self):
        text = '{"score": 85, "reasons": ["good match"]}'
        result = _extract_json(text)
        self.assertEqual(result["score"], 85)
        self.assertEqual(result["reasons"], ["good match"])

    def test_codeblock_wrapped(self):
        text = '```json\n{"score": 72}\n```'
        result = _extract_json(text)
        self.assertEqual(result["score"], 72)

    def test_codeblock_no_lang(self):
        text = '```\n{"score": 50}\n```'
        result = _extract_json(text)
        self.assertEqual(result["score"], 50)

    def test_embedded_json(self):
        text = 'Here is the result: {"score": 90} and that\'s it'
        result = _extract_json(text)
        self.assertEqual(result["score"], 90)

    def test_invalid_json(self):
        self.assertIsNone(_extract_json("not json at all"))

    def test_empty_string(self):
        self.assertIsNone(_extract_json(""))


if __name__ == "__main__":
    unittest.main()
