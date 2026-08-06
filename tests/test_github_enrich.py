"""Hermetic tests for GitHub profile enrichment (strategy §11, Phase 7).

gh_profile/gh_repos are mocked — no subprocesses, hosts.yml or network.
"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


def _repos():
    return [
        {
            "full_name": "octo/infra",
            "language": "Python",
            "topics": ["kubernetes", "aws"],
            "stargazers_count": 42,
            "description": "infra",
        },
        {
            "full_name": "octo/cli",
            "language": "Go",
            "topics": [],
            "stargazers_count": 7,
            "description": "cli",
        },
        {
            "full_name": "octo/notes",
            "language": "Python",
            "topics": ["docker"],
            "stargazers_count": 1,
            "description": "notes",
        },
    ]


class TestEnrichGithubProfile(unittest.TestCase):
    def test_merges_username_and_skills(self):
        from matcha.profile import enrich_github_profile

        profile = {"name": "Mona", "skills": ["python"], "title": "Eng"}
        with (
            mock.patch("matcha.agent_reach_io.gh_profile", return_value={"login": "octo"}),
            mock.patch("matcha.agent_reach_io.gh_repos", return_value=_repos()),
        ):
            updated = enrich_github_profile(profile)
        self.assertEqual(updated["github_username"], "octo")
        # python already present -> not duplicated; golang/kubernetes/aws/docker added
        self.assertIn("golang", updated["skills"])
        self.assertIn("kubernetes", updated["skills"])
        self.assertIn("aws", updated["skills"])
        self.assertIn("docker", updated["skills"])
        self.assertEqual(updated["skills"].count("python"), 1)
        # original profile untouched (returns a copy)
        self.assertNotIn("github_username", profile)

    def test_caps_suggestions(self):
        from matcha.profile import enrich_github_profile

        many = [
            {"full_name": f"o/r{i}", "language": lang, "topics": [], "stargazers_count": i}
            for i, lang in enumerate(["Python", "Go", "Rust", "Java", "C++", "Ruby", "PHP"])
        ]
        with (
            mock.patch("matcha.agent_reach_io.gh_profile", return_value={"login": "octo"}),
            mock.patch("matcha.agent_reach_io.gh_repos", return_value=many),
        ):
            updated = enrich_github_profile({})
        # 8 suggestions cap -> at most 8 new skills
        self.assertLessEqual(len(updated["skills"]), 8)

    def test_no_gh_returns_none(self):
        from matcha.profile import enrich_github_profile

        with mock.patch("matcha.agent_reach_io.gh_profile", return_value=None):
            self.assertIsNone(enrich_github_profile({}))

    def test_no_repos_still_sets_username(self):
        from matcha.profile import enrich_github_profile

        with (
            mock.patch("matcha.agent_reach_io.gh_profile", return_value={"login": "octo"}),
            mock.patch("matcha.agent_reach_io.gh_repos", return_value=None),
        ):
            updated = enrich_github_profile({})
        self.assertEqual(updated["github_username"], "octo")
        self.assertEqual(updated.get("skills", []), [])


class TestGhRepos(unittest.TestCase):
    def test_parses_and_sorts_repos(self):
        import matcha.agent_reach_io as ar

        proc = mock.Mock()
        proc.returncode = 0
        proc.stdout = (
            '[{"full_name": "a/low", "language": "Rust", "stargazers_count": 1, "topics": []},'
            '{"full_name": "b/high", "language": "Python", "stargazers_count": 99, "topics": ["aws"]}]'
        )
        proc.stderr = ""
        with (
            mock.patch("matcha.agent_reach_io.probe_command") as probe,
            mock.patch("matcha.agent_reach_io._gh_credentials_present", return_value=True),
            mock.patch("matcha.agent_reach_io.subprocess.run", return_value=proc),
        ):
            probe.return_value.ok = True
            repos = ar.gh_repos()
        self.assertEqual(repos[0]["full_name"], "b/high")  # sorted by stars desc
        self.assertEqual(repos[0]["language"], "Python")
        self.assertEqual(repos[0]["topics"], ["aws"])

    def test_returns_none_on_probe_failure(self):
        import matcha.agent_reach_io as ar

        with mock.patch("matcha.agent_reach_io.probe_command") as probe:
            probe.return_value.ok = False
            self.assertIsNone(ar.gh_repos())

    def test_returns_none_without_credentials(self):
        import matcha.agent_reach_io as ar

        with (
            mock.patch("matcha.agent_reach_io.probe_command") as probe,
            mock.patch("matcha.agent_reach_io._gh_credentials_present", return_value=False),
        ):
            probe.return_value.ok = True
            self.assertIsNone(ar.gh_repos())

    def test_returns_none_on_bad_payload(self):
        import matcha.agent_reach_io as ar

        proc = mock.Mock()
        proc.returncode = 1
        proc.stdout = ""
        proc.stderr = "nope"
        with (
            mock.patch("matcha.agent_reach_io.probe_command") as probe,
            mock.patch("matcha.agent_reach_io._gh_credentials_present", return_value=True),
            mock.patch("matcha.agent_reach_io.subprocess.run", return_value=proc),
        ):
            probe.return_value.ok = True
            self.assertIsNone(ar.gh_repos())


if __name__ == "__main__":
    unittest.main()
