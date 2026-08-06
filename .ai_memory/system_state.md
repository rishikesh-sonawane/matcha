# Current System State — Matcha

> Last verified: 2026-08-06 (Phase 4 — ranking recalibration — done).
> If any checkbox below conflicts with the actual code, **the code wins** —
> update this file.

## Overview

Matcha **1.x functionality is complete and runs from the 2.0 `src/matcha/`
layout as an installed package.** **Phase 0 + Phase 1 (entry-point migration,
OpenCLI backends, top-N enrichment, Exa Web Search, `agent_reach_io`, Naukrijob-page
extraction) + Phase 2 (normalize + central filters) + Phase 4 (ranking
recalibration) are DONE.** All 401 tests pass. Next: Phase 3 boundary
(enrichment polish) / Phase 5 (AI provider-agnostic) — do NOT start yet.

## Layout

- `src/matcha/` — real modules: `main.py profile.py ai.py matcher.py config.py
  settings.py models.py actions.py` + `errors.py probe.py utils.py doctor.py`
- `src/matcha/sources/` — `base.py` (Source ABC) + `__init__.py` (ALL_SOURCES
  registry) + 7 source modules + `constants.py utils.py`
- `src/matcha/sources/backends/` — **`opencli.py`** (Phase 1): side-effect-free
  probe, consent gate, tolerant command runner, detail helpers
  (`linkedin_job_detail`, `indeed_job_detail`) · **`mcporter.py`** (Phase 1):
  read-only mcporter config inspection (credential boundary) · **`exa.py`**
  (Phase 1): dual-syntax `mcporter call` runner, error-envelope detection,
  `includeDomains` retry guard
- `src/matcha/sources/enrichment.py` — **top-N enrichment** (Phase 1 part 3):
  OpenCLI job-detail merge + Jina zero-config fallback, parallel ≤5, per-job
  isolation
- `src/matcha/sources/naukri.py` — **job-page backend** (Phase 1): DDGS
  discovery → parse real `job-listings-*` postings (embedded JSON-LD /
  `__NEXT_DATA__` first, Jina-render markdown fallback) for description /
  salary / experience / key skills / apply URL; expired-redirect detection;
  `ddgs` snippet fallback
- `src/matcha/normalization.py` — **canonical job normalization** (Phase 2):
  `listed_epoch`, `salary_int` (LPA), synonym `city`/`region`, `remote_ok`;
  in-place + additive
- `src/matcha/filters.py` — **central filter pipeline** (Phase 2):
  quality → age → must-skills → location → salary, `FilterReport` counts,
  `apply_filters` (per-stage isolation), `build_filter_summary`,
  `provenance_tags` (Phase 4: [full]/[partial]/[snippet] + [age?]/[salary?])
- `src/matcha/matcher.py` — **confidence-weighted ranking** (Phase 4):
  text dimensions scaled by data richness (full 1.0 / partial 0.85 /
  snippet 0.7), recency + workplace + must-skill bonuses, soft-mode cap ≤45,
  `detect_flatline`/`normalize_scores`, `ai_eligible` (AI on enriched only)
- `src/matcha/sources/web_search.py` — **Exa ▸ DDGS dispatch** (Phase 1):
  semantic search when mcporter exa configured, graceful keyword fallback
- `src/matcha/agent_reach_io.py` — **thin adapter to agent-reach** (Phase 1):
  `agent-reach doctor --json` snapshot (TTL-cached, credential-scrubbed),
  snapshot-first health signals with own-probe degradation (F-14),
  read-only `gh_profile()` (hosts.yml/env tokens, never `gh auth status`),
  `seed_ai_config()` (borrows groq_api_key)
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
- [x] **Naukri job-page backend (Phase 1)** — `job-page ▸ ddgs`; DDGS
      `site:naukri.com` discovery → parallel fetch of real postings
      (cap 8/batch, 12s timeout): direct HTML only when server-rendered,
      else Jina Reader render (zero-config, no consent — Naukri is a
      client-rendered Next.js shell, verified live); real description /
      salary (`₹a-b LPA`) / experience / key skills / apply URL merged;
      expired postings (search-page redirect) detected + kept as snippets;
      per-job isolation (`enrich_error`), provenance `data_quality`
      full/partial + `enrich_source="job-page"`; `check()` hermetic
- [x] **Normalize + central filters (Phase 2, strategy §7)** — after dedup,
      `normalize_jobs` (listed_epoch, salary_int LPA, city/region, remote_ok)
      then `apply_filters` in fixed order quality → age → must-skills →
      location → salary, each reporting kept/dropped/unknown; age filter is
      the FINAL freshness authority (scrapers only fetch less), unknown age /
      salary tagged `[age?]`/`[salary?]`; must-have skills / min_salary /
      remote_preference from profile.json or `settings.filters`; `--days`
      CLI override; TUI prints "Filtered: N kept (…)" summary
- [x] **Heuristic ranking** — `matcher.py`: weights 35/25/15/15/10, seniority levels, floor = 5
- [x] **Confidence-weighted scoring (Phase 4, §9)** — skills/keywords scaled
      by `data_quality` (full 1.0 / partial 0.85 / snippet 0.7); recency
      (+5/3/1), workplace (+3 vs `remote_preference`), must-have-skill (+2 ea,
      cap +6) bonuses; `must_skills_soft` rank cap ≤45; every row stamped
      with result-level `data_quality`/`backend` at ingest
- [x] **AI re-scoring** — top N (default 30) via `ai_score_job`, parallel ≤8,
      60s timeout; **Phase 4: gated to enriched candidates** (`ai_eligible`);
      flatline guard on final scores (warning + optional
      `ranking.normalize_scores` stretch)
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

- **401/401 tests pass** (`unittest discover tests` AND `pytest tests/`).
  371 at end of Phase 2; +30 from `tests/test_ranking.py` (Phase 4).
  307 at end of Phase 1 (Naukri job-page); +64 from `tests/test_normalization.py`
  (26) + `tests/test_filters.py` (38). Baseline before Phase 0: 122 tests, 1
  pre-existing failure (`test_date_string_within` — F-09 time-bomb, now
  rewritten time-relative).
- New: `tests/test_probe.py`, `tests/test_doctor.py`, `tests/test_source_contracts.py`
  (registry unique names, check() status contract, ordered_backends permutation +
  override, doctor result shape, crash isolation, credential scrubbing),
  `tests/test_opencli.py` (46), `tests/test_enrichment.py` (17),
  `tests/test_exa_backend.py` (36), `tests/test_agent_reach_io.py` (31),
  `tests/test_naukri_job_page.py` (24), `tests/test_normalization.py` (26),
  `tests/test_filters.py` (38).
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
- [x] **Phase 1 — Data quality (DONE 2026-08-06):** entry-point migration (console script `matcha = matcha.main:main`, `pip install -e .`, root shims + `scrapers/` deleted, bandit `-c pyproject.toml -r src/matcha -lll`, pyinstaller via console-script entry, Docker installs the package + `python3 -m matcha.main`); **OpenCLI backends for LinkedIn/Indeed (+ consent flow)**; **top-N enrichment** (`sources/enrichment.py`, Jina zero-config fallback); **Exa Web Search backend** (`backends/mcporter.py` + `backends/exa.py`, DDGS fallback); **`agent_reach_io.py`** (doctor snapshot + degradation); **Naukri job-page extraction** (real `job-listings-*` parse via embedded JSON / Jina render, DDGS fallback). *Accept met: LinkedIn ≥25 results with descriptions (consented); Indeed works on py3.14; doctor shows active backends; `matcha doctor --json` runs via the installed console script; Naukri yields real descriptions/salary.*
- [x] **Phase 2 — Normalize + filters (DONE 2026-08-06):** `normalization.py` (listed_epoch, salary_int LPA, city/region, remote_ok); `filters.py` (quality → age → must-skills → location → salary with per-stage `FilterReport` counts + isolation); `--days` enforced centrally (age filter = final authority); unknown-age `[age?]` / unknown-salary `[salary?]` tags; TUI filter summary line; `Settings.filters` + `Profile` §14 fields. *Accept met: `--days` enforced centrally; unknown-age tagged; garbage dropped; counts shown.*
- [ ] **Phase 3 — Enrichment (2–3 days):** `sources/enrichment.py` (OpenCLI job-detail, top 30, parallel); model + DB columns; TUI detail fields. *Accept: top-30 enriched ≤60s; per-job failures graceful.*
- [x] **Phase 4 — Ranking recalibration (DONE 2026-08-06):** confidence-weighted heuristic (data-richness × dimensions); recency/workplace/must-skill signals; `must_skills_soft` rank cap; AI pass gated to enriched candidates; flatline detection + optional normalization (`ranking.normalize_scores`); `[full]`/`[partial]`/`[snippet]` provenance tags; per-row provenance stamping at ingest. *Accept met: score distribution spreads; full-data jobs outrank snippet-guesses.*
- [ ] **Phase 5 — AI provider-agnostic (2–3 days):** `ai/client.py` (OpenAI-compatible REST), presets, model tiers, disk cache, budget guard. *Accept: works with Groq free tier and zero config; no key leak.*
- [ ] **Phase 6 — Agent + automation (2–3 days):** `--json`; SKILL.md + installer; `matcha watch` + `track.py`; optional MCP server. *Accept: an agent drives a full search via the skill; watch surfaces only new jobs.*
- [ ] **Phase 7 — Hardening (1–2 days):** circuit breakers; config hardening; GitHub profile enrichment; RSS source; coverage ≥80%; **mypy debt cleanup (24 pre-existing errors)**; README/docs.

**Design pillars:** multi-backend richest-first routing · doctor-first observability ·
filters as a central pipeline stage · enrichment over volume · graceful degradation ·
provenance is data · failproof by construction.

## Known Gaps / Pain Points (1.x → fixed in 2.0)

1. Thin, stale, noisy data — **Phases 1–2 fixed the big levers** (OpenCLI backends, top-N enrichment, Exa web, Naukri job-page, central filters); LinkedIn still thin on this machine until the Chrome extension is connected; Naukri DDGS index is stale (expired links gracefully kept as snippets)
2. Re-rank on enriched signals (step 8 of §7) + `must_skills_soft` rank cap + `[full]`/`[snippet]` tags — Phase 4
3. Pydantic models defined but only partially used at runtime (Job/Profile now extended; not yet the runtime boundary) — Phase 4+
4. AI hardcoded to one provider (legacy `MINIMAX` env var name) — Phase 5
5. Saved-jobs DB doesn't persist enriched/normalized fields (salary, salary_int, apply_url, listed_epoch) — Phase 3-adjacent polish
6. OpenCLI extension currently disconnected on this machine (daemon up, ext down) — opencli path untestable live until Chrome + extension are up; falls back correctly
9. mcporter not installed — Exa backend untestable live; `exa_status()==off` → Web Search stays on DDGS; install + `mcporter config add exa https://mcp.exa.ai/mcp --scope home` to exercise
10. agent-reach not installed — `doctor_snapshot()` returns None + one-time warning; all `agent_reach_io` health signals degrade to own probes. gh IS installed + authenticated — `gh_profile()` works live (read-only hosts.yml, never `gh auth status`)
11. Naukri client-rendered + anti-bot — plain requests get an empty SPA shell; jobapi requires CSRF session; the Jina-render path works (verified live) and expired postings redirect to search pages (skipped)
7. mypy: 24 pre-existing legacy errors (not gating) — Phase 7
8. Dedup O(n²) (F-10) — Phase 4

## Key References (revamp/)

- `matcha-2.0-strategy.md` — the plan (Rev 10, source of truth; §6.2/§6.3 corrected for OpenCLI + Exa/mcporter work, §6.5 + §8 + §7 marked implemented)
- `matcha-2.0-implementation-analysis.md` — pre-implementation analysis: verified env, OpenCLI interfaces, migration plan, findings F-01..F-23
- `phase-0-handoff-prompt.txt` — Phase 0 spec (implemented 2026-08-06)
- `opencli-integration-plan.md` — superseded-but-adopted background
