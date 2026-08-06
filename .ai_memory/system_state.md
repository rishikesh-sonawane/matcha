# Current System State — Matcha

> Last verified: 2026-08-06 (Phase 1 part 3 — top-N enrichment — done).
> If any checkbox below conflicts with the actual code, **the code wins** —
> update this file.

## Overview

Matcha **1.x functionality is complete and runs from the 2.0 `src/matcha/`
layout as an installed package.** **Phase 0 + Phase 1 parts 1–3 (foundation,
entry-point migration, OpenCLI backends, top-N enrichment) are DONE.** All
215 tests pass. Remaining Phase 1: Exa backend, Naukri job-page,
`agent_reach_io`; re-rank on enriched signals is Phase 2.

## Layout

- `src/matcha/` — real modules: `main.py profile.py ai.py matcher.py config.py
  settings.py models.py actions.py` + `errors.py probe.py utils.py doctor.py`
- `src/matcha/sources/` — `base.py` (Source ABC) + `__init__.py` (ALL_SOURCES
  registry) + 7 source modules + `constants.py utils.py`
- `src/matcha/sources/backends/` — **`opencli.py`** (Phase 1): side-effect-free
  probe, consent gate, tolerant command runner, detail helpers
  (`linkedin_job_detail`, `indeed_job_detail`)
- `src/matcha/sources/enrichment.py` — **top-N enrichment** (Phase 1 part 3):
  OpenCLI job-detail merge + Jina zero-config fallback, parallel ≤5, per-job
  isolation
- No root shims — root modules + `scrapers/` deleted in Phase 1 part 1;
  `matcha` console script is the entry point

## Component Status (behavior unchanged from 1.x)

- [x] **Profile ingestion** — `profile.py`: PDF resume (pdfplumber + AI extraction), LinkedIn URL (direct + DDG fallback), manual entry; AI title suggestion
- [x] **Query expansion** — `ai.py: ai_generate_queries` + validation gate in `main.py` (semantic dedup >85%, min-token, cap 5)
- [x] **Parallel scraping** — `main.py: search_jobs`, ThreadPoolExecutor ≤12, 45s batch timeout, live status table; `ScraperResult` error isolation per source
- [x] **Scrapers → Sources** — every source is now a `Source` subclass with real `check()` + provenance (`backend`, `data_quality`); dispatch still via `SCRAPER_DEFS` (career_sites excluded, default-off)
- [x] **OpenCLI backends (Phase 1)** — LinkedIn `opencli ▸ guest-api`, Indeed
      `opencli ▸ html ▸ ddgs`; used only when consented (`linkedin_consent` /
      `indeed_consent` in config.json, set via `matcha --configure`) **and**
      healthy (`opencli_status().ready`: `--version` probe + loopback `/status`,
      never `opencli doctor`); graceful fallback when the bridge is down
- [x] **Top-N enrichment (Phase 1 part 3)** — after `rank_jobs`, enrich top N
      (default 30, ≤5 parallel) via OpenCLI job-detail; LinkedIn merges
      description/apply_url/workplace/etc. (never salary — F-06), Indeed
      merges description/job_type/salary/url; per-job isolation
      (`enrich_error`); **Jina Reader zero-config fallback** when the bridge
      is down (ungated by consent, capped at 10, `data_quality=partial`);
      TUI shows Salary/Workplace/Posted/Applicants/Apply URL and `o` opens
      apply_url; settings `enrichment: {enabled,top_n,timeout,max_workers}`
- [x] **Deduplication** — `main.py: deduplicate`, rapidfuzz (title 82 / company 88)
- [x] **Heuristic ranking** — `matcher.py`: weights 35/25/15/15/10, seniority levels, floor = 5
- [x] **AI re-scoring** — top N (default 30) via `ai_score_job`, parallel ≤8, 60s timeout
- [x] **TUI** — prompt_toolkit full-screen: list/detail/saved modes, keys ↑↓ Enter s o n p l r q, pagination 10/page
- [x] **Job lifecycle** — `actions.py`: SQLite `~/.matcha/jobs.db`, statuses saved/applied/dismissed/interview/rejected/offer
- [x] **Config & security** — keyring + fernet for ai_key/serpapi_key; Pydantic validation
- [x] **Settings** — YAML (`matcha.yaml` → `~/.matcha/settings.yaml`), Pydantic validated
- [x] **Logging** — rotating file `~/.matcha/logs/matcha.log` (5MB × 3)
- [x] **CLI** — `--configure`, `--new-profile/-n`, `--non-interactive/-b`, `--config`,
      **`doctor [--json]`** (NEW — per-source health report)
- [x] **Rate limiting + cache** — token bucket per domain, resilient_get, requests-cache SQLite

## NEW — Doctor (`venv/bin/python main.py doctor`)

- `check_all(config)` → `{name: {status, name, message, tier, backends, active_backend}}`
  with per-source exception isolation (status="error") and credential scrubbing.
- Live sample (2026-08-06): LinkedIn `ok` (guest-api active) · Indeed `warn`
  (anti-bot gated — the known py3.14/cloudscraper issue) · Naukri `ok` · RemoteOK `ok`
  (HTTP 200) · Web Search `ok` · SerpAPI `off` (no key) · Career Sites `off` (default).
  Status: 4/7 ready.

## Test Baseline (2026-08-06)

- **152/152 tests pass** (`unittest discover tests` AND `pytest tests/`).
  Baseline before Phase 0: 122 tests, 1 pre-existing failure
  (`test_date_string_within` — F-09 time-bomb, now rewritten time-relative).
- New: `tests/test_probe.py`, `tests/test_doctor.py`, `tests/test_source_contracts.py`
  (registry unique names, check() status contract, ordered_backends permutation +
  override, doctor result shape, crash isolation, credential scrubbing).
- Quality gates all green: `ruff check .`, `ruff format --diff .`, `pre-commit run
  --all-files`, `bandit -r ... -lll` (on the CI targets), mypy baseline documented
  (24 pre-existing legacy errors; mypy not a project dep/CI gate).
- Makefile targets: `run` / `test` / `lint` / `format` / `static-analysis` / `pre-commit` / `check`.

## Git State (2026-08-06, post-Phase-0 — uncommitted)

- Branch `main`. Phase 0 changes are **not committed** (user hasn't asked).
- Tree: renames `RM` (root modules → `src/matcha/`, scrapers → `src/matcha/sources/`),
  new `??` (shims, src/matcha new modules, 3 new test files), modified `M`
  (ci.yml, pyproject.toml, tests/test_days_filter.py, tests/test_core.py [isort],
  scrapers/__init__.py shim). Tracked `__pycache__/*.pyc` show modified (pre-existing
  cruft — leave alone).

## Matcha 2.0 Roadmap (from revamp/matcha-2.0-strategy.md §18)

> Status legend: ⬜ not started · 🟡 in progress · ✅ done

- [x] **Phase 0 — Foundation (DONE 2026-08-06):** `src/matcha/` layout + root shims; `errors.py`; `probe.py`; `doctor.py` + `sources/base.py` + `sources/registry`; provenance fields; every scraper → Source subclass (**no behavior change**); `matcha doctor [--json]`; **entry-point migration deferred to Phase 1**; CI fixes (full suite + 3.14); F-09 test fix; `career_sites` default-off; F-08 India default. *Accept met: doctor lists all sources with real status; 152/152 tests green; `python3 main.py --help` works.*
- [ ] **Phase 1 — Data quality (remaining):** ~~entry-point migration~~ **DONE 2026-08-06** (console script `matcha = matcha.main:main`, `pip install -e .`, root shims + `scrapers/` deleted, bandit `-c pyproject.toml -r src/matcha -lll` — **bandit-coverage gap closed**, pyinstaller via console-script entry, Docker installs the package + `python3 -m matcha.main`); **OpenCLI backends for LinkedIn/Indeed (+ consent flow)**; Exa Web Search backend; Naukri job-page extraction; `agent_reach_io.py`. *Accept: LinkedIn ≥25 results with descriptions (consented); Indeed works on py3.14; doctor shows active backends.*
- [ ] **Phase 2 — Normalize + filters (2–3 days):** `normalization.py`; `filters.py` (quality → age → must-skills → location → salary); filter report in TUI + JSON. *Accept: `--days` enforced centrally; unknown-age tagged `[age?]`; garbage dropped.*
- [ ] **Phase 3 — Enrichment (2–3 days):** `sources/enrichment.py` (OpenCLI job-detail, top 30, parallel); model + DB columns; TUI detail fields. *Accept: top-30 enriched ≤60s; per-job failures graceful.*
- [ ] **Phase 4 — Ranking recalibration (2–3 days):** confidence-weighted scoring; recency/workplace signals; AI on enriched candidates; flatline detection; provenance tags. *Accept: score distribution spreads; full-data jobs outrank snippet-guesses.*
- [ ] **Phase 5 — AI provider-agnostic (2–3 days):** `ai/client.py` (OpenAI-compatible REST), presets, model tiers, disk cache, budget guard. *Accept: works with Groq free tier and zero config; no key leak.*
- [ ] **Phase 6 — Agent + automation (2–3 days):** `--json`; SKILL.md + installer; `matcha watch` + `track.py`; optional MCP server. *Accept: an agent drives a full search via the skill; watch surfaces only new jobs.*
- [ ] **Phase 7 — Hardening (1–2 days):** circuit breakers; config hardening; GitHub profile enrichment; RSS source; coverage ≥80%; **mypy debt cleanup (24 pre-existing errors)**; README/docs.

**Design pillars:** multi-backend richest-first routing · doctor-first observability ·
filters as a central pipeline stage · enrichment over volume · graceful degradation ·
provenance is data · failproof by construction.

## Known Gaps / Pain Points (1.x → fixed in 2.0)

1. Thin, stale, noisy data (LinkedIn ~10 no desc; Indeed broken on py3.14; Naukri search-page links; snippet-guessed fields) — Phase 1 (OpenCLI backends landed; enrichment + Exa + Naukri job-page remain)
2. Exa backend, Naukri job-page extraction, `agent_reach_io` — Phase 1 remainder; re-rank on enriched signals (step 8 of §7) + saved-jobs enriched columns — Phase 2
3. Pydantic models defined but only partially used at runtime — Phase 2
4. AI hardcoded to one provider (legacy `MINIMAX` env var name) — Phase 5
5. No centralized job-age/must-skills/salary filters, no enrichment — Phases 2–3
6. OpenCLI extension currently disconnected on this machine (daemon up, ext down) — opencli path untestable live until Chrome + extension are up; falls back correctly
7. mypy: 24 pre-existing legacy errors (not gating) — Phase 7
8. Dedup O(n²) (F-10) — Phase 4

## Key References (revamp/)

- `matcha-2.0-strategy.md` — the plan (Rev 6, source of truth; §6.2/§6.3 corrected for OpenCLI work, §8 marked implemented)
- `matcha-2.0-implementation-analysis.md` — pre-implementation analysis: verified env, OpenCLI interfaces, migration plan, findings F-01..F-23
- `phase-0-handoff-prompt.txt` — Phase 0 spec (implemented 2026-08-06)
- `opencli-integration-plan.md` — superseded-but-adopted background
