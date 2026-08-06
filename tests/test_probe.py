import os
import stat
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from matcha.probe import probe_command, reinstall_hint
from matcha.utils import scrub_url_credentials, utf8_subprocess_env


class TestProbeCommand(unittest.TestCase):
    def test_missing_command(self):
        result = probe_command("matcha-no-such-command-xyz")
        self.assertEqual(result.status, "missing")
        self.assertFalse(result.ok)
        self.assertEqual(result.hint, "")

    def test_ok_version(self):
        result = probe_command(sys.executable, ("--version",))
        self.assertEqual(result.status, "ok")
        self.assertTrue(result.ok)
        self.assertIn("Python", result.output)

    def test_error_exit_code(self):
        result = probe_command(sys.executable, ("-c", "import sys; sys.exit(3)"))
        self.assertEqual(result.status, "error")
        self.assertFalse(result.ok)

    def test_timeout(self):
        result = probe_command(sys.executable, ("-c", "import time; time.sleep(30)"), timeout=1)
        self.assertEqual(result.status, "timeout")
        self.assertFalse(result.ok)

    def test_broken_shebang(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = os.path.join(tmp, "broken-tool")
            with open(script, "w") as f:
                f.write("#!/nonexistent/interpreter-does-not-exist\n")
            os.chmod(script, os.stat(script).st_mode | stat.S_IXUSR)
            with mock.patch.dict(os.environ, {"PATH": f"{tmp}:{os.environ.get('PATH', '')}"}):
                result = probe_command("broken-tool")
        self.assertEqual(result.status, "broken")
        self.assertIn("uv tool install --force broken-tool", result.hint)

    def test_reinstall_hint(self):
        hint = reinstall_hint("my-tool")
        self.assertIn("uv tool install --force my-tool", hint)
        self.assertIn("pipx reinstall my-tool", hint)


class TestScrubUrlCredentials(unittest.TestCase):
    def test_url_userinfo(self):
        self.assertEqual(
            scrub_url_credentials("https://user:pass@example.com/x"),
            "https://***@example.com/x",
        )

    def test_bare_userinfo(self):
        self.assertEqual(scrub_url_credentials("call me user:pw@host now"), "call me ***@host now")

    def test_query_secret(self):
        self.assertEqual(
            scrub_url_credentials("https://x.com/p?token=abc123"),
            "https://x.com/p?token=***",
        )

    def test_plain_text_unchanged(self):
        self.assertEqual(scrub_url_credentials("no secrets here"), "no secrets here")


class TestUtf8Env(unittest.TestCase):
    def test_utf8_env(self):
        env = utf8_subprocess_env({"FOO": "bar"})
        self.assertEqual(env["FOO"], "bar")
        self.assertEqual(env["PYTHONUTF8"], "1")
        self.assertEqual(env["PYTHONIOENCODING"], "utf-8")


if __name__ == "__main__":
    unittest.main()
