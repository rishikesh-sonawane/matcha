# Active Task State — Matcha

## Current Focus

**Matcha 2.0 — planning + pre-implementation analysis complete, Phase 0 ready to start.**

The strategy (`revamp/matcha-2.0-strategy.md`, rev 4), the pre-implementation
analysis (`revamp/matcha-2.0-implementation-analysis.md`), and the Phase 0
handoff prompt (`revamp/phase-0-handoff-prompt.txt`, scope expanded) are
written. The codebase is still 1.x. **No code has been changed yet for 2.0.**
The user has not yet given the go-ahead to start Phase 0.

> 2026-08-06 session 1: full repo audit + `.ai_memory/` rewrite for Matcha.
> Session 2: studied Agent-Reach v1.5.0 in depth and folded verified patterns
> into the revamp docs (strategy §6.8, Rev 3). Session 3: pre-implementation
> analysis — verified live environment (opencli 1.8.4 + gh installed;
> agent-reach/mcporter absent), verified OpenCLI flag sets + job-detail keys
> (no salary!), wrote `revamp/matcha-2.0-implementation-analysis.md`
> (findings F-01..F-23), bumped strategy to Rev 4, expanded the Phase-0
> handoff scope. **No source code modified in any session.**

---

## Immediate Next Steps

1. **Get user's decision:** "start Phase 0" vs "review the docs first".
   Decisions already confirmed (2026-08-06): shims-first layout (F-04);
   LinkedIn empty-location default = `"India"` (F-08).
2. **If approved, run Phase 0** using `revamp/phase-0-handoff-prompt.txt` (it is the
   ready-made session prompt; scope now includes migration, shims, CI fixes,
   the F-09 test fix, and career_sites default-off). Scope:
   - [ ] Create `src/matcha/` package layout; move flat modules + `scrapers/*`
         (→ `src/matcha/sources/`); update imports, **no behavior change**
   - [ ] `src/matcha/errors.py` — typed hierarchy: `MatchaError > ConfigError /
         SourceError > BackendError / ParseError / FilterError / EnrichmentError`
   - [ ] `src/matcha/probe.py` — port `ProbeResult` + `probe_command` pattern from
         `~/Code/projects/Agent-Reach/agent_reach/probe.py` (real execution,
         stale-venv detection via exit 126/127; retry only transient failures;
         side-effect-free probes; UTF-8 child env)
   - [ ] `src/matcha/doctor.py` + `src/matcha/sources/base.py` + `registry.py` —
         Source base class (ordered backends, tier, check() returns
         (status, message) ok|warn|off|error, active_backend) + ALL_SOURCES
         registry; refactor each scraper into a Source subclass
   - [ ] `matcha doctor [--json]` subcommand wired into the CLI; per-source error
         isolation + `scrub_url_credentials`
   - [ ] `ScraperResult` gains provenance: `backend`, `data_quality`
         (full|partial|snippet)
   - [ ] pytest tests for `probe.py` + `doctor.py` + source contracts
   - [ ] Root re-export shims + pyproject `[project]`/console script +
         Makefile/CI/Docker/bandit path updates + `pip install -e .`
   - [ ] CI fixes: full test suite (`unittest discover`), matrix +3.14
   - [ ] Fix time-dependent test `test_date_string_within` (F-09)
   - [ ] `career_sites` registered but default-off (F-11)
   - **Acceptance:** `matcha doctor --json` lists all sources with real status;
         FULL test suite passes (122/122 after F-09 fix); `python3 main.py
         --help` still works; CI green
3. **Do NOT build Phase 1+ features** (no OpenCLI backends, no Exa, no filters
   module, no enrichment, no AI changes) during Phase 0.

## Blockers / Notes

- No blockers. Waiting on the user's start decision.
- Before implementing `agent_reach_io.py` (Phase 1): verify the exact
  `agent-reach doctor --json` output shape and `agent-reach install
  --channels=opencli` flags in `~/Code/projects/Agent-Reach/agent_reach/cli.py`.
- `scrapers/career_sites.py` is untracked but intended as a source — keep it
  through the Phase 0 refactor (it gets its own `check()`).
- Known pre-existing test failure to fix in Phase 0: `test_days_filter.py::
  test_date_string_within` is a time-bomb (F-09) — "Posted: June 6, 2026" is
  >7 days old now; rewrite the fixture time-relative. The function itself is
  correct.
- Full findings register: `revamp/matcha-2.0-implementation-analysis.md`
  (F-01..F-23 with severities and resolutions).
