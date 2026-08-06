"""Tests for the OpenCLI browser-bridge backend (strategy §6.3).

Covers the side-effect-free probe contract (never ``opencli doctor``), the
consent gate, tolerant JSON row parsing, the command runner, and the
LinkedIn/Indeed search dispatch (opencli when consented+healthy, graceful
fallback otherwise).
"""

import json
import os
import subprocess
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from matcha.models import ScraperResult
from matcha.probe import ProbeResult
from matcha.sources.backends import opencli as oc
from matcha.sources.backends.opencli import (
    OpenCLIStatus,
    _extract_error,
    _extract_rows,
    consent_granted,
    opencli_status,
    run_opencli,
)
from matcha.sources.indeed import (
    _fromage_flag as indeed_fromage,
)
from matcha.sources.indeed import (
    _parse_indeed_rows,
    _search_indeed_opencli,
    search_indeed_jobs,
)
from matcha.sources.linkedin import (
    _date_posted_flag,
    _parse_linkedin_rows,
    _search_linkedin_opencli,
    search_linkedin_jobs,
)


class TestOpenCLIStatus(unittest.TestCase):
    def test_ready_requires_installed_not_broken_extension(self):
        self.assertFalse(OpenCLIStatus().ready)
        self.assertFalse(OpenCLIStatus(installed=True).ready)
        self.assertFalse(OpenCLIStatus(installed=True, broken=True, extension_connected=True).ready)
        self.assertFalse(OpenCLIStatus(installed=True, extension_connected=False).ready)
        self.assertTrue(OpenCLIStatus(installed=True, extension_connected=True).ready)


class TestOpenCLIProbe(unittest.TestCase):
    """opencli_status() must never run `opencli doctor` (auto-starts daemon)."""

    @mock.patch("matcha.sources.backends.opencli.probe_command")
    def test_missing_returns_not_installed(self, probe):
        probe.return_value = ProbeResult("missing")
        st = opencli_status()
        self.assertFalse(st.installed)
        self.assertFalse(st.ready)
        self.assertIn("npm install", st.hint)
        probe.assert_called_once()
        args = probe.call_args.args
        self.assertEqual(args[0], "opencli")
        self.assertEqual(args[1], ["--version"])

    @mock.patch("matcha.sources.backends.opencli.probe_command")
    def test_broken_returns_broken(self, probe):
        probe.return_value = ProbeResult("broken", hint="stale venv")
        st = opencli_status()
        self.assertTrue(st.installed)
        self.assertTrue(st.broken)
        self.assertFalse(st.ready)

    @mock.patch("matcha.sources.backends.opencli._fetch_daemon_status")
    @mock.patch("matcha.sources.backends.opencli.probe_command")
    def test_ok_but_daemon_down_not_ready(self, probe, daemon):
        probe.return_value = ProbeResult("ok", output="1.8.4")
        daemon.return_value = None
        st = opencli_status()
        self.assertTrue(st.installed)
        self.assertEqual(st.version, "1.8.4")
        self.assertFalse(st.daemon_running)
        self.assertFalse(st.ready)

    @mock.patch("matcha.sources.backends.opencli._fetch_daemon_status")
    @mock.patch("matcha.sources.backends.opencli.probe_command")
    def test_extension_connected_is_ready(self, probe, daemon):
        probe.return_value = ProbeResult("ok", output="1.8.4")
        daemon.return_value = {"ok": True, "extensionConnected": True}
        st = opencli_status()
        self.assertTrue(st.daemon_running)
        self.assertTrue(st.extension_connected)
        self.assertTrue(st.ready)

    @mock.patch("matcha.sources.backends.opencli._fetch_daemon_status")
    @mock.patch("matcha.sources.backends.opencli.probe_command")
    def test_daemon_running_but_no_extension_not_ready(self, probe, daemon):
        probe.return_value = ProbeResult("ok", output="1.8.4")
        daemon.return_value = {"ok": True, "extensionConnected": False}
        st = opencli_status()
        self.assertTrue(st.daemon_running)
        self.assertFalse(st.extension_connected)
        self.assertFalse(st.ready)
        self.assertIn("browser extension", st.hint.lower())


class TestDaemonStatus(unittest.TestCase):
    @mock.patch("urllib.request.build_opener")
    def test_fetch_daemon_status_ok(self, opener):
        resp = mock.MagicMock()
        resp.read.return_value = json.dumps({"ok": True, "extensionConnected": True}).encode()
        resp.__enter__.return_value = resp
        opener.return_value.open.return_value = resp
        payload = oc._fetch_daemon_status()
        self.assertIsNotNone(payload)
        self.assertTrue(payload["extensionConnected"])

    @mock.patch("urllib.request.build_opener")
    def test_fetch_daemon_status_failure_returns_none(self, opener):
        opener.return_value.open.side_effect = OSError("refused")
        self.assertIsNone(oc._fetch_daemon_status())


class TestConsent(unittest.TestCase):
    def test_unknown_source_never_consented(self):
        self.assertFalse(consent_granted({}, "serpapi"))

    def test_flat_config_key(self):
        self.assertTrue(consent_granted({"linkedin_consent": True}, "linkedin"))

    def test_scrapers_subsection_key(self):
        cfg = {"scrapers": {"indeed_consent": True}}
        self.assertTrue(consent_granted(cfg, "indeed"))

    def test_absent_consults_disk_config(self):
        with mock.patch(
            "matcha.sources.backends.opencli.load_config", return_value={"linkedin_consent": True}
        ):
            self.assertTrue(consent_granted(None, "linkedin"))
        with mock.patch("matcha.sources.backends.opencli.load_config", return_value={}):
            self.assertFalse(consent_granted(None, "linkedin"))

    def test_absent_everywhere_is_false(self):
        with mock.patch("matcha.sources.backends.opencli.load_config", return_value={}):
            self.assertFalse(consent_granted({"scrapers": {}}, "linkedin"))


class TestJSONParsing(unittest.TestCase):
    def test_parse_clean_array(self):
        self.assertEqual(oc._parse_json_output('[{"a": 1}]'), [{"a": 1}])

    def test_parse_clean_object(self):
        self.assertEqual(oc._parse_json_output('{"ok": true}'), {"ok": True})

    def test_parse_envelope_with_nested_array(self):
        # an envelope dict containing an array must win over its inner array
        self.assertEqual(oc._parse_json_output('{"rows": [{"a": 1}]}'), {"rows": [{"a": 1}]})

    def test_parse_with_noise_prefix_and_ansi(self):
        text = '\x1b[32mdebug\x1b[0m\nINFO progress\n[{"title": "x"}]'
        self.assertEqual(oc._parse_json_output(text), [{"title": "x"}])

    def test_parse_non_json(self):
        self.assertIsNone(oc._parse_json_output("ok: false\nmessage: boom"))

    def test_extract_rows_array(self):
        self.assertEqual(_extract_rows([{"a": 1}]), [{"a": 1}])

    def test_extract_rows_wrapped(self):
        for key in ("rows", "data", "results", "items"):
            self.assertEqual(_extract_rows({key: [{"a": 1}]}), [{"a": 1}])

    def test_extract_rows_filters_non_dicts(self):
        self.assertEqual(_extract_rows([{"a": 1}, "x", 3]), [{"a": 1}])

    def test_extract_error_yaml_message(self):
        raw = (
            "ok: false\nerror:\n  code: BROWSER_CONNECT\n"
            "  message: Browser profile is not connected\n"
        )
        self.assertIn("Browser profile is not connected", _extract_error(raw, 69))

    def test_extract_error_yaml_message_indented(self):
        raw = "ok: false\nerror:\n  code: BROWSER_CONNECT\n  message: Profile X is not connected\n"
        self.assertIn("Profile X is not connected", _extract_error(raw, 69))

    def test_extract_error_fallback(self):
        self.assertIn("boom", _extract_error("boom", 1))


class TestRunOpenCLI(unittest.TestCase):
    def _mock_run(self, returncode=0, stdout="", stderr=""):
        proc = mock.Mock()
        proc.returncode = returncode
        proc.stdout = stdout
        proc.stderr = stderr
        return proc

    @mock.patch("matcha.sources.backends.opencli.subprocess.run")
    @mock.patch("matcha.sources.backends.opencli.shutil.which", return_value="/bin/opencli")
    def test_success_parses_rows(self, which, run):
        run.return_value = self._mock_run(stdout='[{"title": "Engineer"}]')
        result = run_opencli(["linkedin", "search", "python"])
        self.assertTrue(result["ok"])
        self.assertEqual(result["rows"], [{"title": "Engineer"}])
        cmd = run.call_args.args[0]
        self.assertEqual(cmd[-2:], ["-f", "json"])
        # stale daemon-port env var must never reach the child
        env = run.call_args.kwargs["env"]
        self.assertNotIn("OPENCLI_DAEMON_PORT", env)

    @mock.patch("matcha.sources.backends.opencli.subprocess.run")
    @mock.patch("matcha.sources.backends.opencli.shutil.which", return_value="/bin/opencli")
    def test_nonzero_exit_reports_error(self, which, run):
        run.return_value = self._mock_run(returncode=69, stdout="ok: false\nmessage: no browser\n")
        result = run_opencli(["linkedin", "search", "python"])
        self.assertFalse(result["ok"])
        self.assertIn("no browser", result["error"])

    @mock.patch(
        "matcha.sources.backends.opencli.subprocess.run",
        side_effect=subprocess.TimeoutExpired("opencli", 3),
    )
    @mock.patch("matcha.sources.backends.opencli.shutil.which", return_value="/bin/opencli")
    def test_timeout(self, which, run):
        result = run_opencli(["x"], timeout=3)
        self.assertFalse(result["ok"])
        self.assertIn("timed out", result["error"])

    @mock.patch("matcha.sources.backends.opencli.shutil.which", return_value=None)
    def test_not_installed(self, which):
        result = run_opencli(["x"])
        self.assertFalse(result["ok"])
        self.assertIn("not installed", result["error"])


class TestLinkedInDispatch(unittest.TestCase):
    """search_linkedin_jobs routes to opencli only when consented + healthy."""

    def setUp(self):
        self.patch_should = mock.patch("matcha.sources.linkedin._opencli_should_run")
        self.mock_should = self.patch_should.start()
        self.addCleanup(self.patch_should.stop)

    @mock.patch("matcha.sources.linkedin._search_linkedin_opencli")
    def test_not_consented_uses_guest_api(self, opencli_search):
        self.mock_should.return_value = False
        with mock.patch("matcha.sources.linkedin._search_linkedin_guest_api") as guest:
            guest.return_value = ScraperResult(source="LinkedIn", backend="guest-api")
            result = search_linkedin_jobs("engineer", "pune")
        self.assertEqual(result.backend, "guest-api")
        opencli_search.assert_not_called()

    @mock.patch("matcha.sources.linkedin._search_linkedin_opencli")
    def test_consented_uses_opencli(self, opencli_search):
        self.mock_should.return_value = True
        opencli_search.return_value = ScraperResult(source="LinkedIn", backend="opencli")
        result = search_linkedin_jobs("engineer", "pune")
        self.assertEqual(result.backend, "opencli")

    @mock.patch("matcha.sources.linkedin._search_linkedin_opencli")
    def test_opencli_failure_falls_back_to_guest_api(self, opencli_search):
        self.mock_should.return_value = True
        opencli_search.return_value = None
        with mock.patch("matcha.sources.linkedin._search_linkedin_guest_api") as guest:
            guest.return_value = ScraperResult(source="LinkedIn", backend="guest-api")
            result = search_linkedin_jobs("engineer", "pune")
        self.assertEqual(result.backend, "guest-api")

    def test_explicit_backend_override(self):
        with mock.patch("matcha.sources.linkedin._search_linkedin_guest_api") as guest:
            guest.return_value = ScraperResult(source="LinkedIn", backend="guest-api")
            search_linkedin_jobs("engineer", "pune", backend="guest-api")
        self.mock_should.assert_not_called()


class TestLinkedInOpenCLISearch(unittest.TestCase):
    @mock.patch("matcha.sources.linkedin.run_opencli")
    def test_builds_args_and_maps_rows(self, run):
        run.return_value = {
            "ok": True,
            "rows": [
                {
                    "title": "Python Dev",
                    "company": "Acme",
                    "location": "Pune",
                    "listed": "2026-08-01",
                    "salary": "₹25L",
                    "url": "https://www.linkedin.com/jobs/view/123",
                }
            ],
        }
        result = _search_linkedin_opencli("python", "Pune", days=3)
        self.assertEqual(result.backend, "opencli")
        self.assertEqual(result.data_quality, "partial")
        job = result.jobs[0]
        self.assertEqual(job["title"], "Python Dev")
        self.assertEqual(job["salary"], "₹25L")
        self.assertEqual(job["source"], "LinkedIn")
        args = run.call_args.args[0]
        self.assertEqual(args[:4], ["linkedin", "search", "python", "--location"])
        self.assertIn("--date-posted", args)
        self.assertIn("week", args)

    @mock.patch("matcha.sources.linkedin.run_opencli")
    def test_failure_returns_none(self, run):
        run.return_value = {"ok": False, "rows": [], "error": "no browser"}
        self.assertIsNone(_search_linkedin_opencli("python"))

    @mock.patch("matcha.sources.linkedin.run_opencli")
    def test_details_flag_and_quality(self, run):
        run.return_value = {"ok": True, "rows": []}
        _search_linkedin_opencli("python", details=True)
        args = run.call_args.args[0]
        self.assertIn("--details", args)


class TestLinkedInRowMapping(unittest.TestCase):
    def test_maps_with_default_location(self):
        rows = [{"title": "Dev", "company": "X", "location": "", "url": "u"}]
        jobs = _parse_linkedin_rows(rows, "India")
        self.assertEqual(jobs[0]["location"], "India")

    def test_skips_blank_title(self):
        self.assertEqual(_parse_linkedin_rows([{"title": "  "}], "India"), [])

    def test_keeps_extra_fields(self):
        jobs = _parse_linkedin_rows(
            [{"title": "Dev", "salary": "10", "listed": "d", "apply_url": "a"}], ""
        )
        self.assertEqual(jobs[0]["salary"], "10")
        self.assertEqual(jobs[0]["listed"], "d")
        self.assertEqual(jobs[0]["apply_url"], "a")

    def test_date_posted_flag(self):
        self.assertEqual(_date_posted_flag(7), "week")
        self.assertEqual(_date_posted_flag(30), "month")
        self.assertEqual(_date_posted_flag(90), "any")


class TestIndeedDispatch(unittest.TestCase):
    def setUp(self):
        self.patch_should = mock.patch("matcha.sources.indeed._opencli_should_run")
        self.mock_should = self.patch_should.start()
        self.addCleanup(self.patch_should.stop)

    @mock.patch("matcha.sources.indeed._search_indeed_opencli")
    def test_not_consented_uses_html(self, opencli_search):
        self.mock_should.return_value = False
        with mock.patch("matcha.sources.indeed._search_indeed_html") as html:
            html.return_value = ScraperResult(source="Indeed", backend="html")
            result = search_indeed_jobs("engineer", "pune")
        self.assertEqual(result.backend, "html")
        opencli_search.assert_not_called()

    @mock.patch("matcha.sources.indeed._search_indeed_opencli")
    def test_consented_uses_opencli(self, opencli_search):
        self.mock_should.return_value = True
        opencli_search.return_value = ScraperResult(source="Indeed", backend="opencli")
        result = search_indeed_jobs("engineer", "pune")
        self.assertEqual(result.backend, "opencli")

    @mock.patch("matcha.sources.indeed._search_indeed_opencli")
    def test_opencli_failure_falls_back_to_html(self, opencli_search):
        self.mock_should.return_value = True
        opencli_search.return_value = None
        with mock.patch("matcha.sources.indeed._search_indeed_html") as html:
            html.return_value = ScraperResult(source="Indeed", backend="html")
            result = search_indeed_jobs("engineer", "pune")
        self.assertEqual(result.backend, "html")


class TestIndeedOpenCLISearch(unittest.TestCase):
    @mock.patch("matcha.sources.indeed.run_opencli")
    def test_builds_args_and_maps_rows(self, run):
        run.return_value = {
            "ok": True,
            "rows": [
                {
                    "title": "Engineer",
                    "company": "Acme",
                    "location": "Pune",
                    "salary": "₹30L",
                    "id": "dccc07ac5a6a3683",
                    "tags": ["full-time"],
                    "url": "https://www.indeed.com/viewjob?jk=dccc07ac5a6a3683",
                }
            ],
        }
        result = _search_indeed_opencli("engineer", "Pune", days=3)
        self.assertEqual(result.backend, "opencli")
        job = result.jobs[0]
        self.assertEqual(job["job_key"], "dccc07ac5a6a3683")
        self.assertEqual(job["salary"], "₹30L")
        args = run.call_args.args[0]
        self.assertEqual(args[:4], ["indeed", "search", "engineer", "--limit"])
        self.assertIn("--fromage", args)

    @mock.patch("matcha.sources.indeed.run_opencli")
    def test_failure_returns_none(self, run):
        run.return_value = {"ok": False, "rows": [], "error": "no browser"}
        self.assertIsNone(_search_indeed_opencli("engineer"))

    def test_fromage_flag_mapping(self):
        self.assertEqual(indeed_fromage(1), 1)
        self.assertEqual(indeed_fromage(3), 3)
        self.assertEqual(indeed_fromage(7), 7)
        self.assertEqual(indeed_fromage(14), 14)
        self.assertEqual(indeed_fromage(30), 14)


class TestIndeedRowMapping(unittest.TestCase):
    def test_maps_with_default_location(self):
        rows = [{"title": "Dev", "company": "X", "location": ""}]
        jobs = _parse_indeed_rows(rows, "Pune")
        self.assertEqual(jobs[0]["location"], "Pune")

    def test_keeps_salary_and_job_key(self):
        rows = [{"title": "Dev", "salary": "50", "id": "abc", "tags": ["remote"]}]
        jobs = _parse_indeed_rows(rows, "")
        self.assertEqual(jobs[0]["salary"], "50")
        self.assertEqual(jobs[0]["job_key"], "abc")
        self.assertEqual(jobs[0]["tags"], ["remote"])


if __name__ == "__main__":
    unittest.main()
