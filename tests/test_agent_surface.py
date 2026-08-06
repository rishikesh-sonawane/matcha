"""Hermetic tests for the Phase 6 agent + automation surface (strategy §13).

Covers the shared headless pipeline (``run_search``), the JSON document
shape (``build_search_payload``), ``watch`` new-vs-seen wiring, headless
command guards, and the optional MCP server's graceful guard. No network —
scrapers are replaced via ``SCRAPER_DEFS``, settings are minimal, and the
seen-URLs DB points at a temp file.
"""

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


def _settings(enrichment=True) -> dict:
    return {
        "ai": {"enabled": False, "top_n": 30, "timeout": 60, "max_calls": 60},
        "search": {"max_pages": 1},
        "scrapers": {"indeed_domain": "in.indeed.com"},
        "filters": {},
        "ranking": {"normalize_scores": False},
        "enrichment": {
            "enabled": enrichment,
            "top_n": 30,
            "max_workers": 1,
            "timeout": 10,
        },
    }


def _profile() -> dict:
    return {
        "title": "Platform Engineer",
        "headline": "DevOps Engineer",
        "skills": ["aws", "kubernetes", "terraform"],
        "experience": "4",
        "location": "Pune",
    }


def _fake_scraper_factory():
    def _scraper(query, location, days=None, max_pages=1, **kwargs):
        from matcha.models import ScraperResult

        return ScraperResult(
            jobs=[
                {
                    "title": "Platform Engineer",
                    "company": "Acme",
                    "location": "Pune",
                    "description": "aws kubernetes terraform linux",
                    "url": "https://jobs.acme.example/1",
                    "source": "Fake",
                },
                {
                    "title": "DevOps Engineer",
                    "company": "Globex",
                    "location": "Pune",
                    "description": "docker kubernetes ci/cd",
                    "url": "https://jobs.globex.example/2",
                    "source": "Fake",
                },
            ],
            source="Fake",
            backend="fake",
            data_quality="partial",
        )

    return _scraper


class TestPayload(unittest.TestCase):
    def test_job_json_adds_score_and_reasons(self):
        from matcha.main import _job_json

        out = _job_json(86.25, {"title": "T", "url": "u"}, ["reason one"])
        self.assertEqual(out["match_score"], 86.2)
        self.assertEqual(out["reasons"], ["reason one"])
        self.assertEqual(out["title"], "T")
        json.dumps(out)  # serializable

    def test_build_search_payload_shape(self):
        from matcha.main import build_search_payload

        run_result = {
            "ranked": [
                (86.2, {"title": "T", "url": "u", "data_quality": "full"}, ["r"]),
                (40.0, {"title": "S", "url": "v", "data_quality": "snippet"}, []),
            ],
            "source_counts": {"Fake": 2},
            "source_errors": {},
            "filter_summary": "age −1",
            "found_count": 3,
            "ai_used": True,
            "ai_budget_used": 2,
            "enriched_count": 1,
        }
        doc = build_search_payload("platform", "Pune", 7, run_result)
        self.assertEqual(doc["command"], "search")
        self.assertEqual(doc["query"], "platform")
        self.assertEqual(doc["days"], 7)
        self.assertEqual(doc["source_counts"], {"Fake": 2})
        self.assertEqual(doc["filter_summary"], "age −1")
        self.assertEqual(doc["found_count"], 3)
        self.assertEqual(doc["ai_budget_used"], 2)
        self.assertEqual(len(doc["jobs"]), 2)
        self.assertEqual(doc["jobs"][0]["match_score"], 86.2)
        self.assertEqual(doc["jobs"][0]["data_quality"], "full")
        json.dumps(doc)  # fully serializable


class TestRunSearch(unittest.TestCase):
    def test_quiet_pipeline_with_fake_scraper(self):
        from matcha.main import SCRAPER_DEFS, run_search

        with mock.patch.dict(SCRAPER_DEFS, {"Fake": _fake_scraper_factory()}, clear=True):
            result = run_search(
                _profile(),
                "platform",
                "Pune",
                7,
                _settings(enrichment=False),
                {},
                ai_enabled=False,
                quiet=True,
            )
        self.assertEqual(result["found_count"], 2)
        self.assertEqual(len(result["ranked"]), 2)  # no filters configured → all kept
        self.assertEqual(result["source_counts"], {"Fake": 2})
        self.assertEqual(result["enriched_count"], 0)
        self.assertEqual(result["ai_budget_used"], 0)
        self.assertIsInstance(result["filter_summary"], str)
        score, job, reasons = result["ranked"][0]
        self.assertIsInstance(score, float)
        self.assertIsInstance(job, dict)
        self.assertIsInstance(reasons, list)

    def test_enrich_runs_when_enabled(self):
        from matcha.main import SCRAPER_DEFS, run_search

        with (
            mock.patch.dict(SCRAPER_DEFS, {"Fake": _fake_scraper_factory()}, clear=True),
            mock.patch("matcha.sources.enrichment.enrich_top_n", return_value=(2, [])) as enrich,
        ):
            result = run_search(
                _profile(),
                "platform",
                "Pune",
                7,
                _settings(enrichment=True),
                {},
                ai_enabled=False,
                quiet=True,
                enrich=True,
            )
            enrich.assert_called_once()
            self.assertEqual(result["enriched_count"], 2)

    def test_enrich_skipped_when_disabled(self):
        from matcha.main import SCRAPER_DEFS, run_search

        with (
            mock.patch.dict(SCRAPER_DEFS, {"Fake": _fake_scraper_factory()}, clear=True),
            mock.patch("matcha.sources.enrichment.enrich_top_n", return_value=(2, [])) as enrich,
        ):
            result = run_search(
                _profile(),
                "platform",
                "Pune",
                7,
                _settings(enrichment=True),
                {},
                ai_enabled=False,
                quiet=True,
                enrich=False,
            )
            enrich.assert_not_called()
            self.assertEqual(result["enriched_count"], 0)


class TestWatch(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self._db = Path(self._tmp.name) / "jobs.db"
        patcher_db = mock.patch("matcha.track.DB_PATH", self._db)
        patcher_dir = mock.patch("matcha.track.CONFIG_DIR", Path(self._tmp.name))
        patcher_db.start()
        patcher_dir.start()
        self.addCleanup(patcher_db.stop)
        self.addCleanup(patcher_dir.stop)

    def _args(self, **overrides):
        base = dict(
            query="platform",
            location="Pune",
            days=7,
            json=True,
            output=None,
            top=10,
            no_ai_queries=True,
            no_enrich=True,
            no_mark_seen=False,
        )
        base.update(overrides)
        return mock.Mock(**base)

    def test_watch_surfaces_only_new_jobs(self):
        from matcha.main import SCRAPER_DEFS, cmd_watch

        # Pre-seed one of the two fake jobs as already seen.
        from matcha.track import mark_seen

        mark_seen([{"url": "https://jobs.acme.example/1", "title": "Platform Engineer"}])

        args = self._args()
        buf = io.StringIO()
        with (
            mock.patch.dict(SCRAPER_DEFS, {"Fake": _fake_scraper_factory()}, clear=True),
            mock.patch("matcha.main.load_profile", return_value=_profile()),
            mock.patch("matcha.main.load_config", return_value={}),
            mock.patch("matcha.main.check_ai_available", return_value=False),
            mock.patch("matcha.main.console"),
            redirect_stdout(buf),
        ):
            cmd_watch(args, _settings(enrichment=False))

        doc = json.loads(buf.getvalue())
        self.assertEqual(doc["command"], "watch")
        self.assertEqual(doc["new_count"], 1)
        self.assertEqual(doc["seen_count"], 1)
        self.assertEqual(len(doc["jobs"]), 2)
        self.assertEqual(len(doc["new_jobs"]), 1)
        self.assertEqual(doc["new_jobs"][0]["url"], "https://jobs.globex.example/2")
        self.assertEqual(doc["seen_urls_total"], 2)  # both now recorded
        self.assertEqual(doc["marked_seen"], 1)

    def test_watch_no_mark_seen_keeps_table_unchanged(self):
        from matcha.main import SCRAPER_DEFS, cmd_watch
        from matcha.track import stats

        args = self._args(no_mark_seen=True)
        buf = io.StringIO()
        with (
            mock.patch.dict(SCRAPER_DEFS, {"Fake": _fake_scraper_factory()}, clear=True),
            mock.patch("matcha.main.load_profile", return_value=_profile()),
            mock.patch("matcha.main.load_config", return_value={}),
            mock.patch("matcha.main.check_ai_available", return_value=False),
            mock.patch("matcha.main.console"),
            redirect_stdout(buf),
        ):
            cmd_watch(args, _settings(enrichment=False))
        self.assertEqual(stats()["seen_urls_total"], 0)


class TestHeadlessCredentials(unittest.TestCase):
    def _args(self, **overrides):
        base = dict(query="platform", location="Pune", days=7)
        base.update(overrides)
        return mock.Mock(**base)

    def test_no_profile_exits(self):
        from matcha.main import _headless_credentials

        with (
            mock.patch("matcha.main.load_profile", return_value=None),
            mock.patch("matcha.main.sys.exit") as exit_mock,
            mock.patch("matcha.main.console"),
        ):
            _headless_credentials(self._args(), _settings())
        exit_mock.assert_called_once_with(1)

    def test_missing_query_exits(self):
        from matcha.main import _headless_credentials

        with (
            mock.patch("matcha.main.load_profile", return_value=_profile()),
            mock.patch("matcha.main.load_config", return_value={}),
            mock.patch("matcha.main.sys.exit") as exit_mock,
            mock.patch("matcha.main.console"),
        ):
            _headless_credentials(self._args(query=None), {"search": {}})
        exit_mock.assert_called_once_with(1)

    def test_defaults_resolve(self):
        from matcha.main import _headless_credentials

        with (
            mock.patch("matcha.main.load_profile", return_value=_profile()),
            mock.patch(
                "matcha.main.load_config",
                return_value={"last_query": "sre", "last_location": "Bengaluru"},
            ),
            mock.patch("matcha.main.check_ai_available", return_value=True),
        ):
            profile, config, query, location, days, ai = _headless_credentials(
                self._args(query=None, location=None, days=None),
                {"search": {"days": 3}, "ai": {"enabled": True}},
            )
        self.assertEqual(query, "sre")
        self.assertEqual(location, "Bengaluru")
        self.assertEqual(days, 3)
        self.assertTrue(ai)


class TestCmdSearch(unittest.TestCase):
    def test_cmd_search_json_roundtrip(self):
        from matcha.main import SCRAPER_DEFS, cmd_search

        args = mock.Mock(
            query="platform",
            location="Pune",
            days=7,
            json=True,
            output=None,
            top=10,
            no_ai_queries=True,
            no_enrich=True,
        )
        buf = io.StringIO()
        with (
            mock.patch.dict(SCRAPER_DEFS, {"Fake": _fake_scraper_factory()}, clear=True),
            mock.patch("matcha.main.load_profile", return_value=_profile()),
            mock.patch("matcha.main.load_config", return_value={}),
            mock.patch("matcha.main.check_ai_available", return_value=False),
            mock.patch("matcha.main.console"),
            redirect_stdout(buf),
        ):
            cmd_search(args, _settings(enrichment=False))
        doc = json.loads(buf.getvalue())
        self.assertEqual(doc["command"], "search")
        self.assertEqual(len(doc["jobs"]), 2)
        self.assertIn("match_score", doc["jobs"][0])

    def test_cmd_search_json_with_output_keeps_stdout_pure(self):
        """Regression: `--json --output x.json` must keep stdout a pure JSON
        stream — the "Wrote …" note goes to stderr (reviewer-caught)."""
        from matcha.main import SCRAPER_DEFS, cmd_search

        with tempfile.TemporaryDirectory() as tmp:
            out_file = Path(tmp) / "search.json"
            args = mock.Mock(
                query="platform",
                location="Pune",
                days=7,
                json=True,
                output=str(out_file),
                top=10,
                no_ai_queries=True,
                no_enrich=True,
            )
            buf = io.StringIO()
            with (
                mock.patch.dict(SCRAPER_DEFS, {"Fake": _fake_scraper_factory()}, clear=True),
                mock.patch("matcha.main.load_profile", return_value=_profile()),
                mock.patch("matcha.main.load_config", return_value={}),
                mock.patch("matcha.main.check_ai_available", return_value=False),
                mock.patch("matcha.main.console") as stdout_console,
                mock.patch("matcha.main._err_console") as err_console,
                redirect_stdout(buf),
            ):
                cmd_search(args, _settings(enrichment=False))
            doc = json.loads(buf.getvalue())  # pure JSON — no "Wrote" line
            self.assertEqual(doc["command"], "search")
            self.assertTrue(out_file.exists())
            self.assertEqual(json.loads(out_file.read_text(encoding="utf-8")), doc)
            err_console.print.assert_called_once()
            self.assertIn("Wrote", err_console.print.call_args.args[0])
            for call in stdout_console.print.call_args_list:
                self.assertNotIn("Wrote", call.args[0])


class TestMcpServer(unittest.TestCase):
    def test_run_exits_with_hint_when_mcp_missing(self):
        import matcha.mcp_server as mcp_server

        err = io.StringIO()
        with (
            mock.patch.object(mcp_server, "HAS_MCP", False),
            mock.patch("sys.stderr", err),
            self.assertRaises(SystemExit) as ctx,
        ):
            mcp_server.run()
        self.assertEqual(ctx.exception.code, 1)
        self.assertIn("pip install", err.getvalue())

    def test_create_server_exits_when_mcp_missing(self):
        import matcha.mcp_server as mcp_server

        with (
            mock.patch.object(mcp_server, "HAS_MCP", False),
            self.assertRaises(SystemExit),
        ):
            mcp_server.create_server()

    def test_create_server_registers_tools(self):
        import matcha.mcp_server as mcp_server

        fastmcp_cls = mock.MagicMock()
        with (
            mock.patch.object(mcp_server, "HAS_MCP", True),
            mock.patch.object(mcp_server, "FastMCP", fastmcp_cls, create=True),
        ):
            server = mcp_server.create_server()
        self.assertIs(server, fastmcp_cls.return_value)
        self.assertTrue(fastmcp_cls.return_value.tool.called)


if __name__ == "__main__":
    unittest.main()
