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
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from matcha.models import ScraperResult
from matcha.sources.backends.exa import (
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
        # Isolate from a real ~/.mcporter (e.g. after ``mcporter config add
        # exa --scope home``) by pointing HOME at an empty temp dir.
        with tempfile.TemporaryDirectory() as home:
            with mock.patch.dict(os.environ, {"HOME": home, "MCPORTER_CONFIG": ""}, clear=False):
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
        # mcporter 0.13+ defaults to human-readable text — JSON output must
        # be requested explicitly.
        self.assertIn("--output", first)
        self.assertIn("json", first)
        self.assertEqual(len(run.call_args_list), 1)  # no retry on success

    @mock.patch("matcha.sources.backends.exa.subprocess.run")
    @mock.patch("matcha.sources.backends.exa.shutil.which", return_value="/bin/mcporter")
    def test_legacy_dsl_retried_on_failure(self, which, run):
        # new syntax fails on both --output json and plain forms; legacy DSL
        # succeeds on the fourth attempt (0.7.x wshobson generation).
        run.side_effect = [
            self._proc(returncode=69, stdout="Error: bad syntax"),
            self._proc(returncode=69, stdout="Error: bad syntax"),
            self._proc(returncode=69, stdout="Error: bad syntax"),
            self._proc(stdout=json.dumps(_EXA_ENVELOPE)),
        ]
        result = run_mcporter_call("exa", "web_search_exa", {"query": "python", "numResults": 5})
        self.assertTrue(result["ok"])
        self.assertEqual(len(run.call_args_list), 4)
        fourth = run.call_args_list[3].args[0]
        self.assertIn("web_search_exa(query: ", fourth[2])
        self.assertNotIn("--output", fourth)

    @mock.patch("matcha.sources.backends.exa.subprocess.run")
    @mock.patch("matcha.sources.backends.exa.shutil.which", return_value="/bin/mcporter")
    def test_both_syntaxes_fail(self, which, run):
        run.side_effect = [
            self._proc(returncode=1, stdout="boom"),
            self._proc(returncode=1, stdout="boom"),
            self._proc(returncode=1, stdout="boom"),
            self._proc(returncode=1, stdout="boom"),
        ]
        result = run_mcporter_call("exa", "web_search_exa", {"query": "python"})
        self.assertFalse(result["ok"])
        self.assertEqual(len(run.call_args_list), 4)

    @mock.patch(
        "matcha.sources.backends.exa.subprocess.run",
        side_effect=subprocess.TimeoutExpired("mcporter", 30),
    )
    @mock.patch("matcha.sources.backends.exa.shutil.which", return_value="/bin/mcporter")
    def test_timeout(self, which, run):
        result = run_mcporter_call("exa", "web_search_exa", {"query": "python"})
        self.assertFalse(result["ok"])
        self.assertIn("timed out", result["error"])

    @mock.patch("matcha.sources.backends.exa.subprocess.run")
    @mock.patch("matcha.sources.backends.exa.shutil.which", return_value="/bin/mcporter")
    def test_total_budget_caps_all_attempts(self, which, run):
        # Session 28 (reviewer-caught): the 4-attempt runner must respect ONE
        # overall budget — a hung Exa must not chain 4×timeout and starve the
        # DDGS fallback (the scraper batch abandons futures after
        # settings ``search.batch_timeout``, default 120s).
        run.side_effect = [
            self._proc(returncode=1, stdout="a"),
            self._proc(returncode=1, stdout="b"),
        ]
        with mock.patch(
            "matcha.sources.backends.exa.time.monotonic",
            side_effect=[100.0, 100.0, 131.0, 131.0],
        ):
            result = run_mcporter_call("exa", "web_search_exa", {"query": "python"}, timeout=30)
        self.assertFalse(result["ok"])
        # Attempt 1 fails; by attempt 2 the 30s budget is exhausted, so the
        # runner breaks BEFORE the subprocess call — only 1 call, never 4×30s.
        self.assertEqual(len(run.call_args_list), 1)

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

    @mock.patch("matcha.sources.backends.exa.subprocess.run")
    @mock.patch("matcha.sources.backends.exa.shutil.which", return_value="/bin/mcporter")
    def test_rendered_text_blocks_payload(self, which, run):
        # mcporter 0.13+ renders Exa results as Title:/URL:/... text blocks
        # inside content[].text — the runner must parse them into rows.
        rendered = "\n".join(
            [
                "Title: AWS DevOps Engineer | Acme",
                "URL: https://jobs.acme.com/123",
                "Published: N/A",
                "Author: Acme",
                "Highlights:",
                "We are hiring an AWS DevOps Engineer in Pune.",
                "",
                "---",
                "",
                "Title: DevOps Engineer | Globex",
                "URL: https://boards.greenhouse.io/globex/1",
                "Published: 2026-07-28T00:00:00.000Z",
                "Author: N/A",
                "Highlights:",
                "Second posting.",
            ]
        )
        wrapped = {"content": [{"type": "text", "text": rendered}]}
        run.return_value = self._proc(stdout=json.dumps(wrapped))
        result = run_mcporter_call("exa", "web_search_exa", {"query": "python"})
        self.assertTrue(result["ok"])
        rows = result["rows"]
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["title"], "AWS DevOps Engineer | Acme")
        self.assertEqual(rows[0]["url"], "https://jobs.acme.com/123")
        self.assertEqual(rows[0]["author"], "Acme")
        self.assertNotIn("publishedDate", rows[0])  # N/A omitted
        self.assertEqual(rows[1]["publishedDate"], "2026-07-28T00:00:00.000Z")
        self.assertNotIn("author", rows[1])  # N/A omitted
        self.assertIn("hiring an AWS DevOps Engineer", rows[0]["text"])

    @mock.patch("matcha.sources.backends.exa.subprocess.run")
    @mock.patch("matcha.sources.backends.exa.shutil.which", return_value="/bin/mcporter")
    def test_text_block_missing_secondary_fields_still_parsed(self, which, run):
        # Session 28 (reviewer-caught): Exa may omit Author:/Published: — a
        # real posting must never be dropped because a secondary field is
        # missing, so the parser falls back to Title+URL.
        rendered = "\n".join(
            [
                "Title: Backend Engineer | Acme",
                "URL: https://jobs.acme.com/42",
                "Highlights:",
                "Hiring.",
            ]
        )
        wrapped = {"content": [{"type": "text", "text": rendered}]}
        run.return_value = self._proc(stdout=json.dumps(wrapped))
        result = run_mcporter_call("exa", "web_search_exa", {"query": "python"})
        self.assertTrue(result["ok"])
        rows = result["rows"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["title"], "Backend Engineer | Acme")
        self.assertEqual(rows[0]["url"], "https://jobs.acme.com/42")
        self.assertNotIn("publishedDate", rows[0])
        self.assertNotIn("author", rows[0])


class TestExaSearch(unittest.TestCase):
    @mock.patch("matcha.sources.backends.exa.run_mcporter_call")
    def test_sends_only_supported_params(self, call):
        call.return_value = {"ok": True, "rows": _EXA_ENVELOPE["results"], "error": ""}
        exa_search("python", "pune", days=7)
        params = call.call_args.args[2]
        self.assertEqual(params["query"], "python job posting pune")
        self.assertEqual(params["numResults"], 5)
        # The current Exa MCP server ignores includeDomains/startPublishedDate —
        # sending them would be dead weight at best.
        self.assertNotIn("includeDomains", params)
        self.assertNotIn("startPublishedDate", params)

    @mock.patch("matcha.sources.backends.exa.run_mcporter_call")
    def test_failure_returns_none(self, call):
        call.return_value = {"ok": False, "rows": [], "error": "boom"}
        self.assertIsNone(exa_search("python"))

    @mock.patch("matcha.sources.backends.exa.run_mcporter_call")
    def test_no_retry_on_failure(self, call):
        # The includeDomains retry guard is gone — a failed call returns None
        # so the caller can fall back to DDGS immediately.
        call.return_value = {"ok": False, "rows": [], "error": "a"}
        self.assertIsNone(exa_search("python"))
        self.assertEqual(len(call.call_args_list), 1)

    @mock.patch("matcha.sources.backends.exa.run_mcporter_call")
    def test_no_retry_on_empty_results(self, call):
        # A clean 0-result envelope is NOT a failure — return [] directly.
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
    @mock.patch("matcha.sources.web_search._url_is_live")
    @mock.patch("matcha.sources.backends.exa.exa_search")
    def test_rows_mapped_to_job_dicts(self, search, live):
        live.return_value = True
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
