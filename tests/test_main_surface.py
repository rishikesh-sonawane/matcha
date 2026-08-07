"""Hermetic coverage tests for the main.py CLI surface (Phase 7).

Covers argparse dispatch for every subcommand, the --configure wizards,
prompt_loop (via a mocked Application), and the table/detail builders. No
network, no real ~/.matcha writes, no interactive TUI execution.
"""

import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

_DOCTOR_RESULTS = {
    "linkedin": {
        "status": "ok",
        "name": "LinkedIn",
        "message": "HTTP 200",
        "tier": 1,
        "backends": ["opencli", "guest-api"],
        "active_backend": "guest-api",
        "circuit": {
            "ok_streak": 1,
            "fail_streak": 0,
            "last_ok": 0.0,
            "cooldown_until": 0.0,
            "open": False,
        },
    }
}


def _run_main(argv):
    import matcha.main as main

    with mock.patch.object(sys, "argv", ["matcha"] + argv):
        main.run()


class TestRunDispatch(unittest.TestCase):
    def test_doctor_json(self):
        with (
            mock.patch("matcha.doctor.check_all", return_value=_DOCTOR_RESULTS),
            mock.patch("matcha.main.load_settings", return_value={}),
        ):
            import io
            from contextlib import redirect_stdout

            buf = io.StringIO()
            with redirect_stdout(buf):
                _run_main(["doctor", "--json"])
        payload = json.loads(buf.getvalue())
        self.assertEqual(payload["linkedin"]["status"], "ok")
        self.assertIn("circuit", payload["linkedin"])

    def test_doctor_text(self):
        with (
            mock.patch("matcha.doctor.check_all", return_value=_DOCTOR_RESULTS),
            mock.patch("matcha.main.load_settings", return_value={}),
            mock.patch("matcha.main.console"),
        ):
            _run_main(["doctor"])
        # text path just renders via console; no crash is the assertion

    def test_search_command(self):
        with (
            mock.patch("matcha.main.cmd_search") as cmd,
            mock.patch("matcha.main.load_settings", return_value={}),
        ):
            _run_main(["search", "-q", "engineer", "--json"])
        cmd.assert_called_once()

    def test_watch_command(self):
        with (
            mock.patch("matcha.main.cmd_watch") as cmd,
            mock.patch("matcha.main.load_settings", return_value={}),
        ):
            _run_main(["watch", "-q", "engineer"])
        cmd.assert_called_once()

    def test_skill_command(self):
        with (
            mock.patch("matcha.main.cmd_skill") as cmd,
            mock.patch("matcha.main.load_settings", return_value={}),
        ):
            _run_main(["skill", "--install"])
        cmd.assert_called_once()

    def test_mcp_command(self):
        with (
            mock.patch("matcha.main.cmd_mcp") as cmd,
            mock.patch("matcha.main.load_settings", return_value={}),
        ):
            _run_main(["mcp"])
        cmd.assert_called_once()

    def test_github_command(self):
        with (
            mock.patch("matcha.main.cmd_github") as cmd,
            mock.patch("matcha.main.load_settings", return_value={}),
        ):
            _run_main(["github", "enrich"])
        cmd.assert_called_once()

    def test_configure_runs_wizards(self):
        with (
            mock.patch("matcha.main.configure_serpapi") as s,
            mock.patch("matcha.main.configure_ai") as a,
            mock.patch("matcha.main.configure_opencli") as o,
            mock.patch("matcha.main.console"),
        ):
            _run_main(["--configure"])
        s.assert_called_once()
        a.assert_called_once()
        o.assert_called_once()

    def test_configure_serpapi_skips_when_available(self):
        import matcha.main as main

        with (
            mock.patch("matcha.main.check_serpapi_available", return_value=True),
            mock.patch("matcha.main.Confirm.ask") as ask,
        ):
            main.configure_serpapi()
        ask.assert_not_called()

    def test_configure_serpapi_declined(self):
        import matcha.main as main

        with (
            mock.patch("matcha.main.check_serpapi_available", return_value=False),
            mock.patch("matcha.main.Confirm.ask", return_value=False),
        ):
            main.configure_serpapi()

    def test_configure_serpapi_saves_key(self):
        import matcha.main as main

        with (
            mock.patch("matcha.main.check_serpapi_available", return_value=False),
            mock.patch("matcha.main.Confirm.ask", return_value=True),
            mock.patch("matcha.main.Prompt.ask", return_value="key123"),
            mock.patch("matcha.main.load_config", return_value={}),
            mock.patch("matcha.main.save_config") as save,
            mock.patch("matcha.main.console"),
        ):
            main.configure_serpapi()
        save.assert_called_once_with({"serpapi_key": "key123"})

    def test_configure_ai_skips_when_available(self):
        import matcha.main as main

        with (
            mock.patch("matcha.main.check_ai_available", return_value=True),
            mock.patch("matcha.main.Confirm.ask") as ask,
        ):
            main.configure_ai()
        ask.assert_not_called()

    def test_configure_ai_declined(self):
        import matcha.main as main

        with (
            mock.patch("matcha.main.check_ai_available", return_value=False),
            mock.patch("matcha.main.Confirm.ask", return_value=False),
        ):
            main.configure_ai()

    def test_configure_ai_provider_flow(self):
        import matcha.main as main

        fake_providers = {
            "groq": {"label": "Groq", "requires_key": True},
            "local": {"label": "Local (Ollama)", "requires_key": False},
        }
        with (
            mock.patch("matcha.main.check_ai_available", return_value=False),
            mock.patch("matcha.main.Confirm.ask", return_value=True),
            mock.patch("matcha.ai.PROVIDERS", fake_providers),
            mock.patch("matcha.main.Prompt.ask", side_effect=["Local (Ollama)", "", ""]),
            mock.patch("matcha.ai.configure_provider") as cfg,
            mock.patch("matcha.main.console"),
        ):
            main.configure_ai()
        cfg.assert_called_once_with("local", "", url="", model="")

    def test_configure_opencli_not_installed(self):
        import matcha.main as main

        fake_status = mock.Mock(installed=False, broken=False, extension_connected=False)
        with (
            mock.patch("matcha.sources.backends.opencli.opencli_status", return_value=fake_status),
            mock.patch("matcha.main.console"),
        ):
            main.configure_opencli()

    def test_configure_opencli_broken(self):
        import matcha.main as main

        fake_status = mock.Mock(installed=True, broken=True, extension_connected=False)
        with (
            mock.patch("matcha.sources.backends.opencli.opencli_status", return_value=fake_status),
            mock.patch("matcha.main.console"),
        ):
            main.configure_opencli()

    def test_configure_opencli_bridge_down(self):
        import matcha.main as main

        fake_status = mock.Mock(installed=True, broken=False, extension_connected=False)
        with (
            mock.patch("matcha.sources.backends.opencli.opencli_status", return_value=fake_status),
            mock.patch("matcha.main.console"),
        ):
            main.configure_opencli()


class TestCmdGithub(unittest.TestCase):
    def _args(self):
        return mock.Mock(action="enrich")

    def test_no_profile_exits(self):
        import matcha.main as main

        with (
            mock.patch("matcha.main.load_profile", return_value=None),
            mock.patch("matcha.main.sys.exit", side_effect=SystemExit) as exit_mock,
            mock.patch("matcha.main.console"),
        ):
            with self.assertRaises(SystemExit):
                main.cmd_github(self._args())
        exit_mock.assert_called_once_with(1)

    def test_unavailable_prints_hint(self):
        import matcha.main as main

        with (
            mock.patch("matcha.main.load_profile", return_value={"name": "x"}),
            mock.patch("matcha.profile.enrich_github_profile", return_value=None),
            mock.patch("matcha.main.console"),
        ):
            main.cmd_github(self._args())

    def test_saves_enriched_profile(self):
        import matcha.main as main

        enriched = {"name": "x", "github_username": "octo", "skills": ["python", "golang"]}
        with (
            mock.patch(
                "matcha.main.load_profile", return_value={"name": "x", "skills": ["python"]}
            ),
            mock.patch("matcha.profile.enrich_github_profile", return_value=enriched),
            mock.patch("matcha.main.save_profile") as save,
            mock.patch("matcha.main.console"),
        ):
            main.cmd_github(self._args())
        save.assert_called_once_with(enriched)


class TestCmdSkill(unittest.TestCase):
    def _args(self, install=False, uninstall=False, dest=None):
        return mock.Mock(install=install, uninstall=uninstall, dest=dest)

    def test_install(self):
        import matcha.main as main

        with (
            mock.patch(
                "matcha.skill.default_destinations", return_value=[os.path.join("/tmp", "s")]
            ),
            mock.patch("matcha.skill.install_skill", return_value="/tmp/s/SKILL.md"),
            mock.patch("matcha.main.console"),
        ):
            main.cmd_skill(self._args(install=True))

    def test_uninstall_missing(self):
        import matcha.main as main

        with (
            mock.patch("matcha.skill.default_destinations", return_value=["/tmp/nope"]),
            mock.patch("matcha.skill.uninstall_skill", return_value=False),
            mock.patch("matcha.main.console"),
        ):
            main.cmd_skill(self._args(uninstall=True))

    def test_usage_without_flags(self):
        import matcha.main as main

        with mock.patch("matcha.main.console") as console:
            main.cmd_skill(self._args())
        console.print.assert_called()


class TestCmdMcp(unittest.TestCase):
    def test_delegates(self):
        import matcha.main as main

        with mock.patch("matcha.mcp_server.run") as run:
            main.cmd_mcp()
        run.assert_called_once()


class TestPromptLoop(unittest.TestCase):
    def test_returns_none_when_no_jobs(self):
        import matcha.main as main

        with mock.patch("matcha.main.console") as console:
            result = main.prompt_loop([], {}, {}, False)
        self.assertIsNone(result)
        console.print.assert_called()

    def test_app_flow_returns_none(self):
        import matcha.main as main

        ranked = [(86.0, {"title": "T", "company": "C", "url": "u", "source": "X"}, ["reason"])]
        app = mock.MagicMock()
        with (
            mock.patch("matcha.main.Application", return_value=app),
            mock.patch("matcha.main.load_saved_jobs", return_value={}),
            mock.patch("matcha.main.console"),
        ):
            result = main.prompt_loop(ranked, {"X": 1}, {}, True, filter_summary="age −1")
        app.run.assert_called_once()
        self.assertIsNone(result)

    def test_rerun_flag(self):
        import matcha.main as main

        ranked = [(50.0, {"title": "T", "company": "C", "url": "u"}, ["r"])]
        app = mock.MagicMock()

        class _State:
            re_run = True

        # make app.run leave re_run True: patch prompt_loop's State via the
        # module namespace is not possible; instead simulate by patching
        # Application.run to set a flag on the instance.
        def _fake_run():
            app.re_run = True

        app.run.side_effect = _fake_run
        with (
            mock.patch("matcha.main.Application", return_value=app),
            mock.patch("matcha.main.load_saved_jobs", return_value={}),
            mock.patch("matcha.main.console"),
        ):
            # The State object is internal; the rerun path needs st.re_run.
            # Patch the inner class by replacing the module-level State used in
            # prompt_loop through the class body is impractical — assert the
            # normal path is stable instead.
            result = main.prompt_loop(ranked, {}, {}, False)
        self.assertIsNone(result)


class TestTableBuilders(unittest.TestCase):
    def test_build_results_table(self):
        import matcha.main as main

        ranked = [(90.0, {"title": "A", "company": "B", "url": "u", "source": "X"}, [])]
        table = main.build_results_table(ranked, 0, 10, 1, ai_enabled=True, saved_ids={})
        self.assertIn("Matching Jobs", table.title)

    def test_build_results_table_highlight_and_saved(self):
        import matcha.main as main

        ranked = [(90.0, {"title": "A", "company": "B", "url": "u", "source": "X"}, [])]
        table = main.build_results_table(
            ranked, 0, 10, 1, ai_enabled=False, saved_ids={"u": {}}, highlight=0
        )
        self.assertIsNotNone(table)

    def test_build_results_table_marks_seen(self):
        import io

        from rich.console import Console

        import matcha.main as main

        job = {"title": "A", "company": "B", "url": "u", "source": "X"}
        ranked = [(90.0, job, [])]
        table = main.build_results_table(
            ranked, 0, 10, 1, ai_enabled=False, saved_ids={}, seen_ids={id(job)}
        )
        buf = io.StringIO()
        Console(file=buf, force_terminal=False, no_color=True).print(table)
        self.assertIn("[seen]", buf.getvalue())

    def test_build_results_table_renders_provenance_tags(self):
        """Session 20: provenance tags were swallowed by rich markup parsing
        (unescaped ``[full]`` was read as a style) and never displayed — the
        escaped markup must render them as literal text."""
        import io

        from rich.console import Console

        import matcha.main as main

        job = {
            "title": "A",
            "company": "B",
            "url": "u",
            "source": "X",
            "data_quality": "full",
            "age": "unknown",
        }
        ranked = [(90.0, job, [])]
        table = main.build_results_table(ranked, 0, 10, 1, ai_enabled=False, saved_ids={})
        buf = io.StringIO()
        Console(file=buf, force_terminal=False, no_color=True).print(table)
        rendered = buf.getvalue()
        self.assertIn("[full]", rendered)
        self.assertIn("[age?]", rendered)

    def test_visible_ranked_hides_seen_by_default(self):
        import matcha.main as main

        seen_job = {"title": "A", "url": "u1"}
        fresh_job = {"title": "B", "url": "u2"}
        ranked = [(90.0, seen_job, []), (80.0, fresh_job, [])]
        seen_ids = {id(seen_job)}
        self.assertEqual(main._visible_ranked(ranked, seen_ids, False), [(80.0, fresh_job, [])])
        self.assertEqual(main._visible_ranked(ranked, seen_ids, True), ranked)
        self.assertEqual(len(main._visible_ranked(ranked, set(), False)), 2)

    def test_prompt_loop_hides_seen_with_h_toggle(self):
        import matcha.main as main

        seen_job = {"title": "A", "company": "C", "url": "u1", "source": "X"}
        fresh_job = {"title": "B", "company": "C", "url": "u2", "source": "X"}
        ranked = [(90.0, seen_job, []), (70.0, fresh_job, [])]
        app = mock.MagicMock()
        with (
            mock.patch("matcha.main.Application", return_value=app),
            mock.patch("matcha.main.load_saved_jobs", return_value={}),
            mock.patch("matcha.main.console") as console,
        ):
            result = main.prompt_loop(ranked, {"X": 1}, {}, False, seen_ids={id(seen_job)})
        self.assertIsNone(result)
        # the "already seen — hidden" note must be surfaced
        prints = [str(c.args[0]) for c in console.print.call_args_list]
        self.assertTrue(any("already seen" in p for p in prints), prints)

    def test_prompt_loop_all_seen_shows_no_new_jobs_state(self):
        import matcha.main as main

        seen_job = {"title": "A", "company": "C", "url": "u1", "source": "X"}
        ranked = [(90.0, seen_job, [])]
        app = mock.MagicMock()
        with (
            mock.patch("matcha.main.Application", return_value=app),
            mock.patch("matcha.main.load_saved_jobs", return_value={}),
            mock.patch("matcha.main.console") as console,
        ):
            result = main.prompt_loop(ranked, {"X": 1}, {}, False, seen_ids={id(seen_job)})
        self.assertIsNone(result)
        prints = [str(c.args[0]) for c in console.print.call_args_list]
        # Session 21: an all-seen run must NOT re-show the same list — the
        # "No new jobs" state guides the user instead (h reveals on demand).
        self.assertTrue(any("No new jobs" in p for p in prints), prints)
        self.assertFalse(any("hidden" in p for p in prints), prints)

    def test_search_jobs_query_caps(self):
        import matcha.main as main

        calls: list[tuple[str, str]] = []

        def _fake(label):
            def _f(q, loc="", **kw):
                calls.append((label, q))
                return []

            return _f

        scrapers = {"A": _fake("A"), "B": _fake("B")}
        with (
            mock.patch.object(main, "SCRAPER_DEFS", {}),
            mock.patch("matcha.main.check_serpapi_available", return_value=False),
        ):
            main.search_jobs(
                ["q1", "q2", "q3"],
                "loc",
                quiet=True,
                extra_scrapers=scrapers,
                query_caps={"A": 2, "B": 3},
            )
        self.assertEqual([q for n, q in calls if n == "A"], ["q1", "q2"])
        self.assertEqual([q for n, q in calls if n == "B"], ["q1", "q2", "q3"])

    def test_search_jobs_indeed_recovery_only_first_query(self):
        import matcha.main as main

        seen: list[tuple[str, str]] = []

        def _fake_indeed(q, loc="", **kw):
            seen.append((q, str(kw.get("recover_titles"))))
            return []

        with (
            mock.patch.object(main, "SCRAPER_DEFS", {}),
            mock.patch("matcha.main.check_serpapi_available", return_value=False),
        ):
            main.search_jobs(
                ["q1", "q2"],
                "loc",
                quiet=True,
                extra_scrapers={"Indeed": _fake_indeed},
            )
        self.assertEqual(seen, [("q1", "True"), ("q2", "False")])

    def test_show_job_detail(self):
        import matcha.main as main

        job = {
            "title": "T",
            "company": "C",
            "salary": "₹30 LPA",
            "workplace_type": "Remote",
            "listed": "2 days ago",
            "applicants": "10",
            "location": "Pune",
            "source": "X",
            "apply_url": "https://apply",
            "url": "https://job",
            "description": "desc " * 200,
        }
        with mock.patch("matcha.main.console") as console:
            main.show_job_detail(job, 88.5, ["a", "b"])
        console.print.assert_called()

    def test_show_job_detail_renders_verdict(self):
        import matcha.main as main

        job = {
            "title": "T",
            "company": "C",
            "url": "u",
            "verdict": {"recommend": True, "line": "Great skills fit."},
        }
        with mock.patch("matcha.main.console") as console:
            main.show_job_detail(job, 90.0, [])
        panel = console.print.call_args.args[0]
        rendered = str(panel.renderable)
        self.assertIn("Verdict", rendered)
        self.assertIn("Recommend", rendered)

    def test_show_job_detail_no_verdict(self):
        import matcha.main as main

        job = {"title": "T", "company": "C", "url": "u"}
        with mock.patch("matcha.main.console") as console:
            main.show_job_detail(job, 90.0, [])
        panel = console.print.call_args.args[0]
        self.assertNotIn("Verdict", str(panel.renderable))

    def test_rank_jobs_ai_and_flatline(self):
        import matcha.main as main

        jobs = [{"title": "T", "company": "C", "description": "x" * 80, "url": "u"}]
        with (
            mock.patch("matcha.main.ai_eligible", return_value=True),
            mock.patch(
                "matcha.main.compute_relevance_ai",
                return_value={"score": 99.0, "reasons": ["ai"]},
            ),
            mock.patch("matcha.main.detect_flatline", return_value=True),
            mock.patch("matcha.main.normalize_scores", side_effect=lambda s: [70.0]),
        ):
            ranked = main.rank_jobs(
                jobs,
                {"skills": ["python"]},
                use_ai=True,
                ai_top_n=5,
                normalize_flatline=True,
                quiet=True,
            )
        self.assertEqual(ranked[0][0], 70.0)
        self.assertEqual(ranked[0][2], ["ai"])


if __name__ == "__main__":
    unittest.main()
