"""Tests for the Exa semantic-search backend via mcporter (strategy §6.2).

Covers the read-only mcporter config inspection (credential boundary), the
side-effect-free status probe, the dual-syntax command runner, result
extraction, and the web-search dispatcher (exa when configured, graceful
DDGS fallback).
"""

import json
import os
import subprocess
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from matcha.models import ScraperResult
from matcha.sources.backends.exa import (
    EXA_INCLUDE_DOMAINS,
    exa_configured,
    exa_search,
    exa_status,
    run_mcporter_call,
)
from matcha.sources.backends.mcporter import (
    McporterConfigError,
    McporterConfigInspection,
    inspect_mcporter_config,
)
from matcha.sources.web_search import _iso_older_than_days, _search_web_exa, search_web_for_jobs

_EXA_ENVELOPE = {
    "requestId": "x",
    "results": [
        {
            "title": "Python Developer | Acme",
            "url": "https://boards.greenhouse.io/acme/jobs/1",
            "publishedDate": "2026-08-01T10:00:00.000Z",
            "author": "Acme",
            "text": "We are hiring a Python developer in Pune.",
            "score": 0.9,
        }
    ],
}


class TestMcporterInspection(unittest.TestCase):
    def _config(self, payload, name="mcporter.json"):
        import tempfile

        d = tempfile.mkdtemp()
        p = os.path.join(d, name)
        with open(p, "w") as f:
            f.write(json.dumps(payload))
        return d, p

    def test_explicit_config_with_exa(self):
        d, p = self._config(
            {"mcpServers": {"exa": {"url": "https://mcp.exa.ai/mcp"}}, "imports": []}
        )
        with mock.patch.dict(os.environ, {"MCPORTER_CONFIG": p}):
            inspection = inspect_mcporter_config()
        self.assertIn("exa", inspection.server_names)
        self.assertEqual(inspection.source, "explicit")
        self.assertFalse(inspection.imports_unchecked)

    def test_no_config_returns_empty(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            inspection = inspect_mcporter_config(root_dir="/nonexistent-dir-xyz")
        self.assertEqual(inspection.server_names, frozenset())

    def test_malformed_json_raises(self):
        import tempfile

        d = tempfile.mkdtemp()
        p = os.path.join(d, "mcporter.json")
        with open(p, "w") as f:
            f.write("{not json")
        with mock.patch.dict(os.environ, {"MCPORTER_CONFIG": p}):
            with self.assertRaises(McporterConfigError):
                inspect_mcporter_config()

    def test_missing_mcp_servers_raises(self):
        d, p = self._config({"other": 1})
        with mock.patch.dict(os.environ, {"MCPORTER_CONFIG": p}):
            with self.assertRaises(McporterConfigError):
                inspect_mcporter_config()

    def test_imports_missing_flagged_unchecked(self):
        d, p = self._config({"mcpServers": {"github": {"url": "u"}}})
        with mock.patch.dict(os.environ, {"MCPORTER_CONFIG": p}):
            inspection = inspect_mcporter_config()
        self.assertTrue(inspection.imports_unchecked)

    def test_empty_imports_not_unchecked(self):
        d, p = self._config({"mcpServers": {"github": {"url": "u"}}, "imports": []})
        with mock.patch.dict(os.environ, {"MCPORTER_CONFIG": p}):
            inspection = inspect_mcporter_config()
        self.assertFalse(inspection.imports_unchecked)


class TestExaStatus(unittest.TestCase):
    @mock.patch("matcha.sources.backends.exa.shutil.which", return_value=None)
    def test_mcporter_missing_off_with_hint(self, which):
        status, msg = exa_status()
        self.assertEqual(status, "off")
        self.assertIn("npm install -g mcporter", msg)
        self.assertIn("config add exa", msg)

    @mock.patch("matcha.sources.backends.exa.inspect_mcporter_config")
    @mock.patch("matcha.sources.backends.exa.shutil.which", return_value="/bin/mcporter")
    def test_configured_is_warn_not_ok(self, which, inspect):
        inspect.return_value = McporterConfigInspection(frozenset({"exa"}), "home")
        status, msg = exa_status()
        self.assertEqual(status, "warn")  # configured but not live-verified
        self.assertIn("does not start", msg)

    @mock.patch("matcha.sources.backends.exa.inspect_mcporter_config")
    @mock.patch("matcha.sources.backends.exa.shutil.which", return_value="/bin/mcporter")
    def test_not_configured_off_with_hint(self, which, inspect):
        inspect.return_value = McporterConfigInspection(frozenset(), "home")
        status, msg = exa_status()
        self.assertEqual(status, "off")
        self.assertIn("config add exa", msg)

    @mock.patch("matcha.sources.backends.exa.inspect_mcporter_config")
    @mock.patch("matcha.sources.backends.exa.shutil.which", return_value="/bin/mcporter")
    def test_config_error_is_error(self, which, inspect):
        inspect.side_effect = McporterConfigError("bad")
        status, _ = exa_status()
        self.assertEqual(status, "error")


class TestExaConfigured(unittest.TestCase):
    @mock.patch("matcha.sources.backends.exa.inspect_mcporter_config")
    def test_configured_true(self, inspect):
        inspect.return_value = McporterConfigInspection(frozenset({"exa"}), "home")
        self.assertTrue(exa_configured())

    @mock.patch("matcha.sources.backends.exa.inspect_mcporter_config")
    def test_config_error_is_false(self, inspect):
        inspect.side_effect = McporterConfigError("bad")
        self.assertFalse(exa_configured())


class TestRunMcporterCall(unittest.TestCase):
    def _proc(self, returncode=0, stdout=""):
        p = mock.Mock()
        p.returncode = returncode
        p.stdout = stdout
        p.stderr = ""
        return p

    @mock.patch("matcha.sources.backends.exa.subprocess.run")
    @mock.patch("matcha.sources.backends.exa.shutil.which", return_value="/bin/mcporter")
    def test_new_syntax_success(self, which, run):
        run.return_value = self._proc(stdout=json.dumps(_EXA_ENVELOPE))
        result = run_mcporter_call("exa", "web_search_exa", {"query": "python", "numResults": 5})
        self.assertTrue(result["ok"])
        self.assertEqual(result["rows"][0]["title"], "Python Developer | Acme")
        first = run.call_args_list[0].args[0]
        self.assertEqual(first[0], "/bin/mcporter")
        self.assertEqual(first[1], "call")
        self.assertEqual(first[2], "exa.web_search_exa")
        self.assertIn('query="python"', first)
        self.assertIn("numResults=5", first)
        self.assertEqual(len(run.call_args_list), 1)  # no retry on success

    @mock.patch("matcha.sources.backends.exa.subprocess.run")
    @mock.patch("matcha.sources.backends.exa.shutil.which", return_value="/bin/mcporter")
    def test_legacy_dsl_retried_on_failure(self, which, run):
        # first (new syntax) fails with exit 69; second (legacy DSL) succeeds
        run.side_effect = [
            self._proc(returncode=69, stdout="Error: bad syntax"),
            self._proc(stdout=json.dumps(_EXA_ENVELOPE)),
        ]
        result = run_mcporter_call("exa", "web_search_exa", {"query": "python", "numResults": 5})
        self.assertTrue(result["ok"])
        self.assertEqual(len(run.call_args_list), 2)
        second = run.call_args_list[1].args[0]
        self.assertIn("web_search_exa(query: ", second[2])

    @mock.patch("matcha.sources.backends.exa.subprocess.run")
    @mock.patch("matcha.sources.backends.exa.shutil.which", return_value="/bin/mcporter")
    def test_both_syntaxes_fail(self, which, run):
        run.side_effect = [
            self._proc(returncode=1, stdout="boom"),
            self._proc(returncode=1, stdout="boom"),
        ]
        result = run_mcporter_call("exa", "web_search_exa", {"query": "python"})
        self.assertFalse(result["ok"])
        self.assertEqual(len(run.call_args_list), 2)

    @mock.patch(
        "matcha.sources.backends.exa.subprocess.run",
        side_effect=subprocess.TimeoutExpired("mcporter", 30),
    )
    @mock.patch("matcha.sources.backends.exa.shutil.which", return_value="/bin/mcporter")
    def test_timeout(self, which, run):
        result = run_mcporter_call("exa", "web_search_exa", {"query": "python"})
        self.assertFalse(result["ok"])
        self.assertIn("timed out", result["error"])

    @mock.patch("matcha.sources.backends.exa.shutil.which", return_value=None)
    def test_mcporter_not_installed(self, which):
        result = run_mcporter_call("exa", "web_search_exa", {"query": "python"})
        self.assertFalse(result["ok"])
        self.assertIn("not installed", result["error"])

    @mock.patch("matcha.sources.backends.exa.subprocess.run")
    @mock.patch("matcha.sources.backends.exa.shutil.which", return_value="/bin/mcporter")
    def test_nested_wrapper_payload(self, which, run):
        wrapped = {"content": [{"type": "text", "text": json.dumps(_EXA_ENVELOPE)}]}
        run.return_value = self._proc(stdout=json.dumps(wrapped))
        result = run_mcporter_call("exa", "web_search_exa", {"query": "python"})
        self.assertTrue(result["ok"])
        self.assertEqual(result["rows"][0]["url"], _EXA_ENVELOPE["results"][0]["url"])


class TestExaSearch(unittest.TestCase):
    @mock.patch("matcha.sources.backends.exa.run_mcporter_call")
    def test_maps_days_to_start_published_date(self, call):
        call.return_value = {"ok": True, "rows": _EXA_ENVELOPE["results"], "error": ""}
        exa_search("python", days=7)
        params = call.call_args.args[2]
        self.assertIn("startPublishedDate", params)
        self.assertIn("includeDomains", params)
        self.assertEqual(params["includeDomains"], EXA_INCLUDE_DOMAINS)
        self.assertEqual(params["numResults"], 5)

    @mock.patch("matcha.sources.backends.exa.run_mcporter_call")
    def test_failure_returns_none(self, call):
        call.return_value = {"ok": False, "rows": [], "error": "boom"}
        self.assertIsNone(exa_search("python"))

    @mock.patch("matcha.sources.backends.exa.run_mcporter_call")
    def test_retries_without_include_domains(self, call):
        # Array literals may not parse in either mcporter syntax — the
        # backend must retry without includeDomains rather than give up.
        call.side_effect = [
            {"ok": False, "rows": [], "error": "array parse failed"},
            {"ok": True, "rows": _EXA_ENVELOPE["results"], "error": ""},
        ]
        rows = exa_search("python")
        self.assertEqual(len(call.call_args_list), 2)
        self.assertEqual(len(rows), 1)
        second_params = call.call_args_list[1].args[2]
        self.assertNotIn("includeDomains", second_params)
        self.assertEqual(second_params["query"], "python")

    @mock.patch("matcha.sources.backends.exa.run_mcporter_call")
    def test_no_retry_when_both_fail(self, call):
        call.side_effect = [
            {"ok": False, "rows": [], "error": "a"},
            {"ok": False, "rows": [], "error": "b"},
        ]
        self.assertIsNone(exa_search("python"))
        self.assertEqual(len(call.call_args_list), 2)

    @mock.patch("matcha.sources.backends.exa.run_mcporter_call")
    def test_no_retry_on_empty_results(self, call):
        # A clean 0-result envelope is NOT a failure — no includeDomains retry.
        call.return_value = {"ok": True, "rows": [], "error": ""}
        self.assertEqual(exa_search("python"), [])
        self.assertEqual(len(call.call_args_list), 1)


class TestErrorEnvelopes(unittest.TestCase):
    @mock.patch("matcha.sources.backends.exa.subprocess.run")
    @mock.patch("matcha.sources.backends.exa.shutil.which", return_value="/bin/mcporter")
    def test_success_false_envelope_is_failure(self, which, run):
        run.return_value = self._proc(
            stdout=json.dumps({"success": False, "error": "rate limited"})
        )
        result = run_mcporter_call("exa", "web_search_exa", {"query": "python"})
        self.assertFalse(result["ok"])
        self.assertIn("rate limited", result["error"])

    @mock.patch("matcha.sources.backends.exa.subprocess.run")
    @mock.patch("matcha.sources.backends.exa.shutil.which", return_value="/bin/mcporter")
    def test_error_key_without_success_is_failure(self, which, run):
        run.return_value = self._proc(stdout=json.dumps({"error": "bad api key"}))
        result = run_mcporter_call("exa", "web_search_exa", {"query": "python"})
        self.assertFalse(result["ok"])
        self.assertIn("bad api key", result["error"])

    @mock.patch("matcha.sources.backends.exa.subprocess.run")
    @mock.patch("matcha.sources.backends.exa.shutil.which", return_value="/bin/mcporter")
    def test_empty_results_envelope_is_success(self, which, run):
        run.return_value = self._proc(stdout=json.dumps({"requestId": "x", "results": []}))
        result = run_mcporter_call("exa", "web_search_exa", {"query": "python"})
        self.assertTrue(result["ok"])
        self.assertEqual(result["rows"], [])

    @mock.patch("matcha.sources.backends.exa.subprocess.run")
    @mock.patch("matcha.sources.backends.exa.shutil.which", return_value="/bin/mcporter")
    def test_json_error_extraction_on_nonzero_exit(self, which, run):
        run.return_value = self._proc(
            returncode=1,
            stdout=json.dumps({"error": {"message": "server not found"}}),
        )
        result = run_mcporter_call("exa", "web_search_exa", {"query": "python"})
        self.assertFalse(result["ok"])
        self.assertIn("server not found", result["error"])
        self.assertNotIn("{", result["error"].split(":", 2)[-1])  # no raw dump

    @mock.patch("matcha.sources.backends.exa.subprocess.run")
    @mock.patch("matcha.sources.backends.exa.shutil.which", return_value="/bin/mcporter")
    def test_nested_json_string_error_extraction(self, which, run):
        run.return_value = self._proc(
            returncode=1,
            stdout=json.dumps(
                {"content": [{"type": "text", "text": json.dumps({"error": "quota exceeded"})}]}
            ),
        )
        result = run_mcporter_call("exa", "web_search_exa", {"query": "python"})
        self.assertFalse(result["ok"])
        self.assertIn("quota exceeded", result["error"])

    def _proc(self, returncode=0, stdout=""):
        p = mock.Mock()
        p.returncode = returncode
        p.stdout = stdout
        p.stderr = ""
        return p


class TestWebSearchDispatch(unittest.TestCase):
    def setUp(self):
        self.patch_should = mock.patch("matcha.sources.web_search._exa_should_run")
        self.mock_should = self.patch_should.start()
        self.addCleanup(self.patch_should.stop)

    @mock.patch("matcha.sources.web_search._search_web_exa")
    def test_exa_configured_uses_exa(self, exa_path):
        self.mock_should.return_value = True
        exa_path.return_value = ScraperResult(source="Web Search", backend="exa")
        result = search_web_for_jobs("python", "pune")
        self.assertEqual(result.backend, "exa")

    @mock.patch("matcha.sources.web_search._search_web_exa")
    def test_exa_failure_falls_back_to_ddgs(self, exa_path):
        self.mock_should.return_value = True
        exa_path.return_value = None
        with mock.patch("matcha.sources.web_search._search_web_ddgs") as ddgs:
            ddgs.return_value = ScraperResult(source="Web Search", backend="ddgs")
            result = search_web_for_jobs("python", "pune")
        self.assertEqual(result.backend, "ddgs")

    @mock.patch("matcha.sources.web_search._search_web_exa")
    def test_not_configured_uses_ddgs(self, exa_path):
        self.mock_should.return_value = False
        with mock.patch("matcha.sources.web_search._search_web_ddgs") as ddgs:
            ddgs.return_value = ScraperResult(source="Web Search", backend="ddgs")
            result = search_web_for_jobs("python", "pune")
        self.assertEqual(result.backend, "ddgs")
        exa_path.assert_not_called()


class TestExaMapping(unittest.TestCase):
    @mock.patch("matcha.sources.backends.exa.exa_search")
    def test_rows_mapped_to_job_dicts(self, search):
        search.return_value = [
            {
                "title": "Python Developer | Acme",
                "url": "https://boards.greenhouse.io/acme/jobs/1",
                "publishedDate": "2026-08-01T10:00:00.000Z",
                "author": "Acme",
                "text": "Hiring a Python developer.",
                "score": 0.9,
            }
        ]
        result = _search_web_exa("python", days=30)
        self.assertEqual(result.backend, "exa")
        self.assertEqual(result.data_quality, "partial")
        job = result.jobs[0]
        self.assertEqual(job["title"], "Python Developer")
        self.assertEqual(job["company"], "Acme")
        self.assertEqual(job["listed"], "2026-08-01")
        self.assertEqual(job["score"], 0.9)
        self.assertIn("https://boards.greenhouse.io", job["url"])

    @mock.patch("matcha.sources.backends.exa.exa_search")
    def test_failure_returns_none(self, search):
        search.return_value = None
        self.assertIsNone(_search_web_exa("python"))

    def test_iso_older_than_days(self):
        self.assertFalse(_iso_older_than_days("", 7))
        self.assertFalse(_iso_older_than_days("not-a-date", 7))
        self.assertTrue(_iso_older_than_days("2020-01-01T00:00:00.000Z", 7))
        self.assertFalse(_iso_older_than_days("2999-01-01T00:00:00.000Z", 7))


class TestWebSearchSourceCheck(unittest.TestCase):
    @mock.patch("matcha.sources.backends.exa.exa_status")
    def test_exa_configured_preferred(self, status):
        status.return_value = ("warn", "Exa configured but unverified")
        from matcha.sources import get_source

        src = get_source("web_search")
        result = src.check(None)
        self.assertEqual(result[0], "warn")
        self.assertEqual(src.active_backend, "exa")

    @mock.patch("matcha.sources.backends.exa.exa_status")
    def test_exa_off_falls_to_ddgs(self, status):
        status.return_value = ("off", "mcporter not installed")
        from matcha.sources import get_source

        src = get_source("web_search")
        result = src.check(None)
        self.assertEqual(result[0], "ok")
        self.assertEqual(src.active_backend, "ddgs")


if __name__ == "__main__":
    unittest.main()
