"""Tests for the ``agent_reach_io`` thin adapter (strategy §6.5).

Covers the side-effect-free availability probe, the ``agent-reach doctor
--json`` snapshot (parse + TTL cache), snapshot-first health signals with
own-probe fallback (F-14), the exa delegation, the read-only gh profile, and
the groq key seeding. Fully hermetic — no real subprocesses, config files, or
network.
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import matcha.agent_reach_io as ar


def _snapshot_payload():
    return {
        "github": {
            "status": "warn",
            "name": "GitHub",
            "message": "gh CLI installed",
            "tier": 0,
            "backends": ["gh CLI"],
            "active_backend": None,
        },
        "linkedin": {
            "status": "warn",
            "name": "LinkedIn",
            "message": "OpenCLI bridge connected",
            "tier": 1,
            "backends": ["OpenCLI"],
            "active_backend": "OpenCLI",
        },
    }


class TestAgentReachAvailable(unittest.TestCase):
    @mock.patch("matcha.agent_reach_io.probe_command")
    def test_available_when_ok(self, probe):
        probe.return_value.ok = True
        self.assertTrue(ar.agent_reach_available())

    @mock.patch("matcha.agent_reach_io.probe_command")
    def test_unavailable_when_missing(self, probe):
        probe.return_value.ok = False
        self.assertFalse(ar.agent_reach_available())


class TestDoctorSnapshot(unittest.TestCase):
    def setUp(self):
        ar._snapshot_ts = 0.0
        ar._snapshot_value = None
        ar._hint_logged = False

    def _proc(self, returncode=0, stdout=""):
        p = mock.Mock()
        p.returncode = returncode
        p.stdout = stdout
        p.stderr = ""
        return p

    @mock.patch("matcha.agent_reach_io.subprocess.run")
    @mock.patch("matcha.agent_reach_io.agent_reach_available", return_value=True)
    def test_parses_snapshot(self, available, run):
        run.return_value = self._proc(stdout=json.dumps(_snapshot_payload()))
        snapshot = ar.doctor_snapshot()
        self.assertIsNotNone(snapshot)
        self.assertIn("linkedin", snapshot)
        self.assertEqual(snapshot["linkedin"]["status"], "warn")

    @mock.patch("matcha.agent_reach_io.agent_reach_available", return_value=True)
    def test_nonzero_exit_returns_none(self, available):
        with mock.patch("matcha.agent_reach_io.subprocess.run") as run:
            run.return_value = self._proc(returncode=1, stdout="boom")
            self.assertIsNone(ar.doctor_snapshot())

    @mock.patch("matcha.agent_reach_io.agent_reach_available", return_value=True)
    def test_non_json_output_returns_none(self, available):
        with mock.patch("matcha.agent_reach_io.subprocess.run") as run:
            run.return_value = self._proc(stdout="not json at all")
            self.assertIsNone(ar.doctor_snapshot())

    @mock.patch("matcha.agent_reach_io.agent_reach_available", return_value=False)
    def test_missing_agent_reach_returns_none_and_hints_once(self, available):
        ar._hint_logged = False
        with self.assertLogs("matcha.agent_reach_io", level="INFO") as logs:
            self.assertIsNone(ar.doctor_snapshot())
            self.assertIsNone(ar.doctor_snapshot())  # cached None, hint still once
        hints = [line for line in logs.output if "agent-reach not installed" in line]
        self.assertEqual(len(hints), 1)

    @mock.patch("matcha.agent_reach_io.subprocess.run")
    @mock.patch("matcha.agent_reach_io.agent_reach_available", return_value=True)
    def test_ttl_cache_avoids_resubprocess(self, available, run):
        run.return_value = self._proc(stdout=json.dumps(_snapshot_payload()))
        ar.doctor_snapshot()
        ar.doctor_snapshot()
        self.assertEqual(run.call_count, 1)

    @mock.patch("matcha.agent_reach_io.subprocess.run")
    @mock.patch("matcha.agent_reach_io.agent_reach_available", return_value=True)
    def test_snapshot_scrubs_credentials(self, available, run):
        payload = {
            "github": {
                "status": "warn",
                "name": "GitHub",
                "message": "proxy http://user:pass@example.com",
                "tier": 0,
                "backends": [],
                "active_backend": None,
            }
        }
        run.return_value = self._proc(stdout=json.dumps(payload))
        snapshot = ar.doctor_snapshot()
        self.assertNotIn("user:pass", snapshot["github"]["message"])
        self.assertIn("***@", snapshot["github"]["message"])


class TestOpencliReady(unittest.TestCase):
    def setUp(self):
        ar._snapshot_ts = 0.0
        ar._snapshot_value = None
        ar._hint_logged = False

    def test_snapshot_opencli_warn_is_ready(self):
        with mock.patch("matcha.agent_reach_io.doctor_snapshot") as snap:
            snap.return_value = _snapshot_payload()
            self.assertTrue(ar.opencli_ready())

    def test_snapshot_opencli_off_is_not_ready(self):
        payload = _snapshot_payload()
        payload["linkedin"]["status"] = "off"
        with mock.patch("matcha.agent_reach_io.doctor_snapshot") as snap:
            snap.return_value = payload
            self.assertFalse(ar.opencli_ready())

    def test_no_opencli_channel_falls_back_to_own_probe(self):
        payload = {"github": _snapshot_payload()["github"]}
        with mock.patch("matcha.agent_reach_io.doctor_snapshot") as snap:
            snap.return_value = payload
            with mock.patch("matcha.sources.backends.opencli.opencli_status") as status:
                status.return_value.ready = True
                self.assertTrue(ar.opencli_ready())
                status.return_value.ready = False
                self.assertFalse(ar.opencli_ready())

    def test_no_snapshot_falls_back_to_own_probe(self):
        with mock.patch("matcha.agent_reach_io.doctor_snapshot", return_value=None):
            with mock.patch("matcha.sources.backends.opencli.opencli_status") as status:
                status.return_value.ready = True
                self.assertTrue(ar.opencli_ready())


class TestExaSearch(unittest.TestCase):
    @mock.patch("matcha.sources.backends.exa.exa_search")
    def test_delegates_to_backend(self, backend):
        backend.return_value = [{"title": "T", "url": "u"}]
        self.assertEqual(ar.exa_search("python", num=7), [{"title": "T", "url": "u"}])
        backend.assert_called_once_with("python", num=7)


class TestGhCredentialsPresent(unittest.TestCase):
    @mock.patch("matcha.agent_reach_io._gh_hosts_configured", return_value=False)
    def test_env_token_counts_as_authenticated(self, hosts):
        with mock.patch.dict(os.environ, {"GH_TOKEN": "gho_xxx"}, clear=False):
            self.assertTrue(ar._gh_credentials_present())
        hosts.assert_not_called()

    @mock.patch("matcha.agent_reach_io._gh_hosts_configured", return_value=True)
    def test_hosts_yml_counts_without_env(self, hosts):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertTrue(ar._gh_credentials_present())

    @mock.patch("matcha.agent_reach_io._gh_hosts_configured", return_value=False)
    def test_neither_is_unauthenticated(self, hosts):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertFalse(ar._gh_credentials_present())

    @mock.patch("matcha.agent_reach_io.probe_command")
    def test_gh_missing_returns_none(self, probe):
        probe.return_value.ok = False
        self.assertIsNone(ar.gh_profile())

    @mock.patch("matcha.agent_reach_io._gh_hosts_configured", return_value=False)
    @mock.patch("matcha.agent_reach_io.probe_command")
    def test_unauthenticated_returns_none(self, probe, hosts):
        probe.return_value.ok = True
        self.assertIsNone(ar.gh_profile())

    @mock.patch("matcha.agent_reach_io.subprocess.run")
    @mock.patch("matcha.agent_reach_io._gh_hosts_configured", return_value=True)
    @mock.patch("matcha.agent_reach_io.probe_command")
    def test_profile_from_api(self, probe, hosts, run):
        probe.return_value.ok = True
        p = mock.Mock()
        p.returncode = 0
        p.stdout = json.dumps({"login": "octocat", "name": "Mona", "email": "m@x.io"})
        p.stderr = ""
        run.return_value = p
        profile = ar.gh_profile()
        self.assertEqual(profile, {"login": "octocat", "name": "Mona", "email": "m@x.io"})
        # read-only env must be applied to the child
        env = run.call_args.kwargs["env"]
        self.assertEqual(env["GH_TELEMETRY"], "false")

    @mock.patch("matcha.agent_reach_io.subprocess.run")
    @mock.patch("matcha.agent_reach_io._gh_hosts_configured", return_value=True)
    @mock.patch("matcha.agent_reach_io.probe_command")
    def test_api_failure_returns_none(self, probe, hosts, run):
        probe.return_value.ok = True
        p = mock.Mock()
        p.returncode = 1
        p.stdout = ""
        p.stderr = "not authenticated"
        run.return_value = p
        self.assertIsNone(ar.gh_profile())


class TestGhHostsConfigured(unittest.TestCase):
    def test_hosts_yml_with_token(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "hosts.yml")
        with open(path, "w") as f:
            f.write("github.com:\n  oauth_token: gho_xxx\n  user: octocat\n")
        with mock.patch("matcha.agent_reach_io._gh_hosts_path", return_value=Path(path)):
            self.assertTrue(ar._gh_hosts_configured())

    def test_hosts_yml_without_github(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "hosts.yml")
        with open(path, "w") as f:
            f.write("gitlab.com:\n  user: x\n")
        with mock.patch("matcha.agent_reach_io._gh_hosts_path", return_value=Path(path)):
            self.assertFalse(ar._gh_hosts_configured())

    def test_hosts_yml_missing(self):
        with mock.patch(
            "matcha.agent_reach_io._gh_hosts_path",
            return_value=Path("/nonexistent/hosts.yml"),
        ):
            self.assertFalse(ar._gh_hosts_configured())


class TestSeedAiConfig(unittest.TestCase):
    def _write(self, content):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "config.yaml")
        with open(path, "w") as f:
            f.write(content)
        return path

    def test_borrows_groq_key(self):
        path = self._write("groq_api_key: gsk_abc123\nother: 1\n")
        seeded = ar.seed_ai_config(path)
        self.assertEqual(seeded["ai_key"], "gsk_abc123")
        self.assertEqual(seeded["ai_url"], ar.GROQ_BASE_URL)
        self.assertEqual(seeded["ai_model"], ar.GROQ_MODEL)

    def test_no_key_returns_none(self):
        path = self._write("other: 1\n")
        self.assertIsNone(ar.seed_ai_config(path))

    def test_missing_file_returns_none(self):
        self.assertIsNone(ar.seed_ai_config("/nonexistent/config.yaml"))

    def test_symlink_rejected(self):
        d = tempfile.mkdtemp()
        target = os.path.join(d, "target.yaml")
        link = os.path.join(d, "link.yaml")
        with open(target, "w") as f:
            f.write("groq_api_key: gsk_x\n")
        os.symlink(target, link)
        self.assertIsNone(ar.seed_ai_config(link))

    def test_malformed_yaml_returns_none(self):
        path = self._write("{not: [valid")
        self.assertIsNone(ar.seed_ai_config(path))


class TestParseJsonOutput(unittest.TestCase):
    def test_strips_ansi_and_noise(self):
        text = '\x1b[32mprefix {"a": 1}\x1b[0m'
        self.assertEqual(ar._parse_json_output(text), {"a": 1})

    def test_earliest_brace_wins(self):
        text = '{"results": [{"title": "T"}]}'
        self.assertEqual(ar._parse_json_output(text), {"results": [{"title": "T"}]})

    def test_garbage_returns_none(self):
        self.assertIsNone(ar._parse_json_output("not json"))


if __name__ == "__main__":
    unittest.main()
