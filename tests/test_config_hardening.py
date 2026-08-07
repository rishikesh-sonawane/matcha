"""Hermetic tests for Phase 7 config hardening (strategy §17).

All paths are redirected into a temp dir; keyring is disabled so the fernet
fallback is exercised deterministically. Tests cover atomic owner-only writes,
component-wise symlink rejection, reads that never create files, and size caps.
"""

import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import matcha.config as config


class _RedirectedConfig(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.patchers = [
            mock.patch.object(config, "CONFIG_DIR", self.tmp),
            mock.patch.object(config, "CONFIG_FILE", self.tmp / "config.json"),
            mock.patch.object(config, "PROFILE_FILE", self.tmp / "profile.json"),
            mock.patch.object(config, "FERNET_KEY_FILE", self.tmp / "fernet.key"),
            mock.patch.object(config, "_KEYRING_AVAILABLE", False),
        ]
        for p in self.patchers:
            p.start()
            self.addCleanup(p.stop)


class TestAtomicWrites(_RedirectedConfig):
    def test_save_config_writes_atomic_0600(self):
        config.save_config({"last_query": "x", "last_days": 3})
        raw = config.CONFIG_FILE.read_text(encoding="utf-8")
        self.assertEqual(json.loads(raw)["last_query"], "x")
        mode = stat.S_IMODE(config.CONFIG_FILE.stat().st_mode)
        self.assertEqual(mode, 0o600)

    def test_save_config_no_plaintext_secrets(self):
        config.save_config({"serpapi_key": "secret123", "last_query": "x"})
        raw = config.CONFIG_FILE.read_text(encoding="utf-8")
        self.assertNotIn("secret123", raw)

    def test_load_profile_roundtrip(self):
        config.save_profile({"name": "Mona", "skills": ["python"]})
        loaded = config.load_profile()
        self.assertEqual(loaded["name"], "Mona")
        self.assertEqual(loaded["skills"], ["python"])
        mode = stat.S_IMODE(config.PROFILE_FILE.stat().st_mode)
        self.assertEqual(mode, 0o600)

    def test_reads_never_create_files_or_dir(self):
        config.CONFIG_FILE.unlink(missing_ok=True)
        config.PROFILE_FILE.unlink(missing_ok=True)
        # reads must return defaults / None and create nothing
        self.assertEqual(config._load_config_raw(), {})
        self.assertIsNone(config.load_profile())
        self.assertFalse(config.CONFIG_FILE.exists())
        self.assertFalse(config.PROFILE_FILE.exists())

    def test_symlink_config_file_rejected_on_write(self):
        target = self.tmp / "elsewhere.json"
        target.write_text("{}", encoding="utf-8")
        os.symlink(target, config.CONFIG_FILE)
        config.save_config({"last_query": "y"})
        # the symlink must NOT be replaced with a real file pointing elsewhere;
        # the target file must be untouched and no write-through happened
        self.assertTrue(config.CONFIG_FILE.is_symlink())
        self.assertEqual(target.read_text(encoding="utf-8"), "{}")

    def test_symlink_config_dir_rejected(self):
        # put a symlinked "config.json" and symlinked dir under tmp
        real_dir = self.tmp / "real"
        real_dir.mkdir()
        link_dir = self.tmp / "linked"
        os.symlink(real_dir, link_dir)
        with mock.patch.object(config, "CONFIG_DIR", link_dir):
            config.save_profile({"name": "n"})
        # nothing was written into the real dir through the link
        self.assertEqual(list(real_dir.iterdir()), [])

    def test_oversized_config_read_rejected(self):
        config.CONFIG_FILE.write_text("x" * (config._MAX_CONFIG_BYTES + 1), encoding="utf-8")
        self.assertEqual(config._load_config_raw(), {})

    def test_corrupt_config_degrades(self):
        config.CONFIG_FILE.write_text("{not json", encoding="utf-8")
        # corrupt file -> raw {} -> load_config returns schema defaults, no crash
        self.assertEqual(config._load_config_raw(), {})
        self.assertEqual(config.load_config()["last_query"], "")
        # and a subsequent save repairs the file
        config.save_config({"last_query": "ok"})
        self.assertEqual(config.load_config()["last_query"], "ok")

    def test_fernet_secret_roundtrip(self):
        config.save_config({"ai_key": "sk-abc"})
        loaded = config.load_config()
        self.assertEqual(loaded["ai_key"], "sk-abc")
        self.assertTrue(config.FERNET_KEY_FILE.exists())
        mode = stat.S_IMODE(config.FERNET_KEY_FILE.stat().st_mode)
        self.assertEqual(mode, 0o600)


class TestConfigEdgePaths(_RedirectedConfig):
    def test_ensure_config_dir_0700(self):
        config.CONFIG_DIR.rmdir() if config.CONFIG_DIR.exists() and not list(
            config.CONFIG_DIR.iterdir()
        ) else None
        config.ensure_config_dir()
        self.assertTrue(config.CONFIG_DIR.is_dir())
        mode = stat.S_IMODE(config.CONFIG_DIR.stat().st_mode)
        self.assertEqual(mode, 0o700)

    def test_read_encrypted_missing_key_returns_empty(self):
        self.assertEqual(config._read_encrypted("ai_key"), "")

    def test_read_encrypted_bad_data_degrades(self):
        config.save_config({"ai_key": "sk-abc"})
        enc_path = config.CONFIG_DIR / ".ai_key.enc"
        enc_path.write_text("garbage-not-encrypted", encoding="utf-8")
        self.assertEqual(config._read_encrypted("ai_key"), "")

    def test_write_encrypted_creates_file(self):
        config._write_encrypted("ai_key", "v")
        enc_path = config.CONFIG_DIR / ".ai_key.enc"
        self.assertTrue(enc_path.exists())
        self.assertEqual(config._read_encrypted("ai_key"), "v")

    def test_delete_encrypted(self):
        config._write_encrypted("ai_key", "v")
        config._delete_encrypted("ai_key")
        self.assertFalse((config.CONFIG_DIR / ".ai_key.enc").exists())

    def test_secret_write_without_backend_warns(self):
        with (
            mock.patch.object(config, "_KEYRING_AVAILABLE", False),
            mock.patch.object(config, "_FERNET_AVAILABLE", False),
        ):
            config._write_secret("ai_key", "plain")

    def test_secret_read_without_backend_empty(self):
        with (
            mock.patch.object(config, "_KEYRING_AVAILABLE", False),
            mock.patch.object(config, "_FERNET_AVAILABLE", False),
        ):
            self.assertEqual(config._read_secret("ai_key"), "")

    def test_load_config_reads_other_secrets(self):
        # ai_url is in _KEYRING_KEYS but not a secret-config key: stored via
        # fernet and merged back when absent from config.json
        config._write_encrypted("ai_url", "https://x")
        raw = config._load_config_raw()
        raw.pop("ai_url", None)
        loaded = config.load_config()
        self.assertEqual(loaded["ai_url"], "https://x")

    def test_save_config_unknown_key_preserved(self):
        config.save_config({"last_query": "x", "custom_field": 42})
        loaded = config.load_config()
        self.assertEqual(loaded["custom_field"], 42)

    def test_partial_save_preserves_other_keys(self):
        # Session 19 regression: the TUI persists only last_query/last_days —
        # save_config must MERGE over the file, not replace it, or ai_provider
        # + the OpenCLI consents get wiped to schema defaults on every run
        # (which silently disabled AI and the browser backends).
        config.save_config(
            {"ai_provider": "kilo", "linkedin_consent": True, "indeed_consent": True}
        )
        config.save_config({"last_query": "new", "last_days": 3})
        loaded = config.load_config()
        self.assertEqual(loaded["ai_provider"], "kilo")
        self.assertTrue(loaded["linkedin_consent"])
        self.assertTrue(loaded["indeed_consent"])
        self.assertEqual(loaded["last_query"], "new")
        self.assertEqual(loaded["last_days"], 3)
        # The merge is persisted, not just in-memory.
        raw = config._load_config_raw()
        self.assertEqual(raw["ai_provider"], "kilo")
        self.assertTrue(raw["linkedin_consent"])

    def test_partial_save_does_not_delete_other_secret(self):
        # A partial save (no ai_key passed) must not delete the stored AI key.
        config.save_config({"ai_key": "sk-keep"})
        config.save_config({"last_query": "x"})
        self.assertEqual(config.load_config()["ai_key"], "sk-keep")

    def test_save_profile_oserror_logged(self):
        with mock.patch.object(config, "atomic_write_text", side_effect=OSError("disk full")):
            config.save_profile({"name": "n"})

    def test_save_config_refused_symlink_logs(self):
        target = self.tmp / "elsewhere.json"
        target.write_text("{}", encoding="utf-8")
        os.symlink(target, config.CONFIG_FILE)
        config.save_config({"last_query": "z"})  # must not raise
        self.assertTrue(config.CONFIG_FILE.is_symlink())

    def test_fernet_key_read_refused_symlink(self):
        target = self.tmp / "real.key"
        target.write_text("x" * 44, encoding="utf-8")
        os.symlink(target, config.FERNET_KEY_FILE)
        self.assertIsNone(config._get_fernet())

    def test_load_profile_corrupt(self):
        config.PROFILE_FILE.write_text("not json", encoding="utf-8")
        self.assertIsNone(config.load_profile())

    def test_load_profile_non_dict(self):
        config.PROFILE_FILE.write_text("[1,2]", encoding="utf-8")
        self.assertIsNone(config.load_profile())

    def test_load_profile_symlink_refused(self):
        target = self.tmp / "real.json"
        target.write_text('{"name": "x"}', encoding="utf-8")
        os.symlink(target, config.PROFILE_FILE)
        self.assertIsNone(config.load_profile())


class TestPathHelpers(unittest.TestCase):
    def test_atomic_write_text_creates_parents(self):
        from matcha.utils import atomic_write_text

        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / "a" / "b" / "f.txt"
            atomic_write_text(target, "hi")
            self.assertEqual(target.read_text(encoding="utf-8"), "hi")
            self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)

    def test_ensure_no_symlink_path_rejects(self):
        from matcha.errors import ConfigSecurityError
        from matcha.utils import ensure_no_symlink_path

        with tempfile.TemporaryDirectory() as d:
            real = Path(d) / "real"
            real.mkdir()
            link = Path(d) / "link"
            os.symlink(real, link)
            with self.assertRaises(ConfigSecurityError):
                ensure_no_symlink_path(link / "config.json")
            # a plain path with a missing tail is fine
            ensure_no_symlink_path(Path(d) / "ok" / "new.json")

    def test_read_small_text_no_follow_bounds(self):
        from matcha.errors import ConfigSecurityError
        from matcha.utils import read_small_text_no_follow

        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "f.txt"
            p.write_text("hello", encoding="utf-8")
            self.assertEqual(read_small_text_no_follow(p, max_bytes=10), "hello")
            with self.assertRaises(ConfigSecurityError):
                read_small_text_no_follow(p, max_bytes=4)
            self.assertIsNone(read_small_text_no_follow(Path(d) / "missing", max_bytes=10))
            # symlinked file rejected
            link = Path(d) / "link.txt"
            os.symlink(p, link)
            with self.assertRaises(ConfigSecurityError):
                read_small_text_no_follow(link, max_bytes=10)


if __name__ == "__main__":
    unittest.main()
