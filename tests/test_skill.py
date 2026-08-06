"""Hermetic tests for the SKILL.md installer (strategy §13, Phase 6)."""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


class TestSkill(unittest.TestCase):
    def test_source_skill_bundled(self):
        from matcha.skill import source_skill_path

        path = source_skill_path()
        self.assertTrue(path.exists())
        content = path.read_text(encoding="utf-8")
        self.assertIn("name: matcha", content)
        self.assertIn("matcha search", content)
        self.assertIn("matcha watch", content)

    def test_default_destinations(self):
        from matcha.skill import default_destinations

        home = Path.home()
        self.assertEqual(
            default_destinations(),
            [
                home / ".agents" / "skills" / "matcha",
                home / ".claude" / "skills" / "matcha",
            ],
        )

    def test_install_creates_skill_file(self):
        from matcha.skill import install_skill

        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "matcha"
            out = install_skill(dest)
            self.assertEqual(out, dest / "SKILL.md")
            self.assertTrue(out.exists())
            self.assertIn("name: matcha", out.read_text(encoding="utf-8"))

    def test_uninstall_removes_directory(self):
        from matcha.skill import install_skill, uninstall_skill

        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "matcha"
            install_skill(dest)
            self.assertTrue(uninstall_skill(dest))
            self.assertFalse(dest.exists())
            # second removal reports False
            self.assertFalse(uninstall_skill(dest))

    def test_install_missing_source_raises(self):
        from unittest import mock

        from matcha.skill import install_skill

        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch(
                "matcha.skill.source_skill_path",
                return_value=Path(tmp) / "missing.md",
            ):
                with self.assertRaises(FileNotFoundError):
                    install_skill(Path(tmp) / "dest")


if __name__ == "__main__":
    unittest.main()
