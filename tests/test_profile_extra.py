"""Hermetic coverage tests for profile.py (Phase 7).

parse_resume_pdf is exercised via an injected fake ``pdfplumber`` module;
network scrapes use mocked resilient_get; interactive flows use mocked
Prompt/Confirm. No real files, network or keyrings.
"""

import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


class _Resp:
    def __init__(self, text, status_code=200):
        self.text = text
        self.status_code = status_code


class TestPureHelpers(unittest.TestCase):
    def test_extract_experience(self):
        from matcha.profile import extract_experience

        self.assertEqual(extract_experience("5+ years of experience"), 5)
        self.assertEqual(extract_experience("8 years exp"), 8)
        self.assertEqual(extract_experience("Experience: 12"), 12)
        self.assertIsNone(extract_experience("no numbers here"))

    def test_extract_linkedin_username(self):
        from matcha.profile import extract_linkedin_username

        self.assertEqual(
            extract_linkedin_username("https://www.linkedin.com/in/mona-lisa"), "mona-lisa"
        )
        self.assertIsNone(extract_linkedin_username("https://example.com"))

    def test_extract_url_ddg_redirect(self):
        from matcha.profile import extract_url

        self.assertEqual(
            extract_url("//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fjob"),
            "https://example.com/job",
        )
        self.assertEqual(extract_url("https://plain.example/x"), "https://plain.example/x")


class TestParseResumePdf(unittest.TestCase):
    def _install_fake_pdfplumber(self, text):
        class FakePage:
            def extract_text(self):
                return text

        class FakePdf:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            @property
            def pages(self):
                return [FakePage()]

        mod = types.ModuleType("pdfplumber")
        mod.open = lambda path: FakePdf()
        sys.modules["pdfplumber"] = mod
        self.addCleanup(lambda: sys.modules.pop("pdfplumber", None))

    def test_ai_extraction_flow(self):
        from matcha.profile import parse_resume_pdf

        with tempfile.TemporaryDirectory() as d:
            pdf_path = os.path.join(d, "resume.pdf")
            Path(pdf_path).write_bytes(b"%PDF-1.4\nfake\n")
            self._install_fake_pdfplumber("Mona\nPython engineer with 5 years experience")
            ai_profile = {
                "name": "Mona",
                "title": "DevOps Engineer",
                "headline": "DevOps Engineer",
                "skills": ["python", "aws"],
                "experience": "",
                "summary": "s",
            }
            with (
                mock.patch("matcha.profile.check_ai_available", return_value=True),
                mock.patch("matcha.profile.ai_extract_profile", return_value=ai_profile),
                mock.patch("matcha.profile.console"),
            ):
                profile = parse_resume_pdf(pdf_path)
        self.assertEqual(profile["name"], "Mona")
        self.assertEqual(profile["experience"], "5")  # fallback from text

    def test_missing_file(self):
        from matcha.profile import parse_resume_pdf

        with mock.patch("matcha.profile.console"):
            self.assertIsNone(parse_resume_pdf("/nonexistent/file.pdf"))

    def test_no_ai_returns_none(self):
        from matcha.profile import parse_resume_pdf

        self._install_fake_pdfplumber("text")
        with (
            mock.patch("matcha.profile.check_ai_available", return_value=False),
            mock.patch("matcha.profile.console"),
        ):
            self.assertIsNone(parse_resume_pdf("/tmp/x.pdf"))

    def test_ai_failure_returns_none(self):
        from matcha.profile import parse_resume_pdf

        self._install_fake_pdfplumber("text")
        with (
            mock.patch("matcha.profile.check_ai_available", return_value=True),
            mock.patch("matcha.profile.ai_extract_profile", return_value=None),
            mock.patch("matcha.profile.console"),
        ):
            self.assertIsNone(parse_resume_pdf("/tmp/x.pdf"))


class TestScrapeLinkedinProfile(unittest.TestCase):
    HTML = (
        "<html><head><title>Mona Lisa | DevOps Engineer | LinkedIn</title></head>"
        "<body><main><section id='about'>Expert in k8s</section>"
        "<section id='skills'><ul><li>Kubernetes</li><li>Terraform</li></ul></section>"
        "</main></body></html>"
    )

    def test_direct_parse(self):
        from matcha.profile import scrape_linkedin_profile

        with (
            mock.patch("matcha.profile.resilient_get", return_value=_Resp(self.HTML)),
            mock.patch("matcha.profile.console"),
        ):
            profile = scrape_linkedin_profile("https://www.linkedin.com/in/mona-lisa")
        self.assertEqual(profile["name"], "Mona Lisa")
        self.assertIn("Kubernetes", profile["skills"])

    def test_blocked_falls_back_to_web(self):
        from matcha.profile import scrape_linkedin_profile

        with (
            mock.patch(
                "matcha.profile.resilient_get",
                side_effect=[_Resp("", status_code=403), _Resp("", status_code=403)],
            ),
            mock.patch(
                "matcha.profile.search_linkedin_profile_via_web",
                return_value={
                    "name": "Mona",
                    "headline": "Eng",
                    "skills": [],
                    "summary": "",
                    "experience": "",
                },
            ),
            mock.patch("matcha.profile.console"),
        ):
            profile = scrape_linkedin_profile("https://www.linkedin.com/in/mona-lisa")
        self.assertEqual(profile["name"], "Mona")


class TestBuildOrLoadProfile(unittest.TestCase):
    def test_uses_existing_when_confirmed(self):
        from matcha.profile import build_or_load_profile

        existing = {"name": "Mona", "title": "Eng", "skills": ["python"]}
        with (
            mock.patch("matcha.profile.load_profile", return_value=existing),
            mock.patch("matcha.profile.Confirm.ask", return_value=True),
            mock.patch("matcha.profile.console"),
        ):
            profile = build_or_load_profile(force_new=False)
        self.assertIs(profile, existing)

    def test_manual_entry_new_profile(self):
        from matcha.profile import build_or_load_profile

        manual = {
            "name": "Mona",
            "title": "Eng",
            "headline": "Eng",
            "skills": ["python"],
            "experience": "5",
            "summary": "s",
        }
        with (
            mock.patch("matcha.profile.load_profile", return_value=None),
            mock.patch("matcha.profile.check_ai_available", return_value=False),
            mock.patch("matcha.profile.Prompt.ask", return_value="1"),
            mock.patch("matcha.profile.manual_profile_entry", return_value=manual),
            mock.patch("matcha.profile.save_profile") as save,
            mock.patch("matcha.profile.console"),
        ):
            profile = build_or_load_profile(force_new=True)
        self.assertEqual(profile["name"], "Mona")
        save.assert_called_once()


if __name__ == "__main__":
    unittest.main()
