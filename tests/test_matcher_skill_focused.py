import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import unittest

from matcha.matcher import compute_relevance


class TestSkillFocusedMatcher(unittest.TestCase):
    def setUp(self):
        self.profile = {
            "title": "Platform Engineer",
            "headline": "DevOps Engineer",
            "skills": [
                "aws",
                "docker",
                "kubernetes",
                "terraform",
                "ci/cd",
                "linux",
                "python",
                "ansible",
                "prometheus",
                "grafana",
            ],
            "experience": "4",
            "summary": "Platform and infrastructure engineer with cloud experience",
            "location": "Pune",
        }

    def test_sde_with_platform_skills_scores_high(self):
        """SDE job with matching infras skills should score well despite 'SDE' title."""
        job = {
            "title": "Software Development Engineer - AWS Platform",
            "company": "Amazon",
            "description": (
                "We are looking for an SDE to build our internal platform. "
                "Required skills: aws, kubernetes, docker, terraform, ci/cd, "
                "python, linux. You will work on prometheus monitoring and "
                "grafana dashboards for our infrastructure."
            ),
            "location": "Pune, India",
        }
        result = compute_relevance(job, self.profile)
        self.assertGreaterEqual(
            result["score"],
            50,
            f"SDE with platform skills should score >= 50, got {result['score']}",
        )

    def test_platform_engineer_with_matching_skills_scores_high(self):
        """Classic Platform Engineer title with matching skills."""
        job = {
            "title": "Platform Engineer",
            "company": "Barclays",
            "description": (
                "aws docker kubernetes terraform ci/cd linux python ansible prometheus grafana"
            ),
            "location": "Pune, India",
        }
        result = compute_relevance(job, self.profile)
        # 7+ of 10 skills match → 70 * 0.7 = 49+, plus title/location/seniority
        self.assertGreaterEqual(result["score"], 60)

    def test_irrelevant_sde_no_platform_skills_scores_low(self):
        """SDE job with frontend/backend tech, no infra skills, should score low."""
        job = {
            "title": "Software Development Engineer",
            "company": "Some Startup",
            "description": (
                "Building web applications with react, node.js, typescript, "
                "css, html, javascript, mongodb, express. No infrastructure or "
                "cloud platform work involved."
            ),
            "location": "Bangalore",
        }
        result = compute_relevance(job, self.profile)
        self.assertLessEqual(
            result["score"],
            30,
            f"SDE with irrelevant skills should score <= 30, got {result['score']}",
        )

    def test_no_hardcoded_role_words(self):
        """Verify no hardcoded role word lists exist in matcher module."""
        import matcha.matcher

        with open(matcha.matcher.__file__) as f:
            source = f.read()
        forbidden = [
            "GENERIC_TITLE_WORDS",
            "SOFTWARE_ROLE_WORDS",
            "PLATFORM_ROLE_WORDS",
            "_role_type",
            '"software"',
            "penalty",
        ]
        for token in forbidden:
            self.assertNotIn(
                token,
                source,
                f"Hardcoded token '{token}' should not appear in matcher.py",
            )

    def test_skills_dominate_score(self):
        """A job with many matching skills but a poor title should still score well."""
        job = {
            "title": "Random Title That Means Nothing",
            "company": "TestCo",
            "description": (
                "aws docker kubernetes terraform ci/cd linux python "
                "ansible prometheus grafana all of these are in the text"
            ),
            "location": "Pune, India",
        }
        result = compute_relevance(job, self.profile)
        # Skills = 70 * (10/10) = 70, title overlap = low, location + seniority push it higher
        self.assertGreaterEqual(result["score"], 50)

    def test_low_skill_match_scores_low(self):
        """A job with almost no matching skills should score low."""
        job = {
            "title": "Senior Platform Engineer",
            "company": "TestCo",
            "description": (
                "Managing spreadsheets and writing documentation. No technical skills required."
            ),
            "location": "Pune, India",
        }
        result = compute_relevance(job, self.profile)
        # Skills = 70 * (0/10) = 0, title = 10 * 100% = 10, location = 10, seniority = 10 → 30
        self.assertLessEqual(result["score"], 40)


class TestNaukriTitleFilter(unittest.TestCase):
    def test_page_n_titles_filtered(self):
        import re

        from matcha.sources.naukri import NON_JOB_TITLE_PATTERNS

        bad_titles = ["Page 8", "page 9", "Page 12", "Search", "Sign In", "Log In"]
        for t in bad_titles:
            self.assertTrue(
                any(re.search(p, t) for p in NON_JOB_TITLE_PATTERNS),
                f"'{t}' should match NON_JOB_TITLE_PATTERNS",
            )

    def test_job_titles_not_filtered(self):
        import re

        from matcha.sources.naukri import NON_JOB_TITLE_PATTERNS

        good_titles = ["Platform Engineer", "DevOps Engineer", "Cloud Engineer at Google"]
        for t in good_titles:
            self.assertFalse(
                any(re.search(p, t) for p in NON_JOB_TITLE_PATTERNS),
                f"'{t}' should NOT match NON_JOB_TITLE_PATTERNS",
            )


if __name__ == "__main__":
    unittest.main()
