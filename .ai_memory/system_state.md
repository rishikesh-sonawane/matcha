# Current System State — Matcha

> Last verified: 2026-08-06 (repo audit + test run). If any checkbox below
> conflicts with the actual code, **the code wins** — update this file.

## Overview

Matcha **1.x is complete and functional** (flat layout, thin data, two-pass
ranking). Matcha **2.0 planning AND pre-implementation analysis are complete**
(strategy rev 4 at `revamp/matcha-2.0-strategy.md`;
`revamp/matcha-2.0-implementation-analysis.md` = findings F-01..F-23),
and **Phase 0 has not started** — the codebase is still the 1.x flat layout.
Phase 0 scope was expanded (migration + shims + CI fixes + F-09 test fix).

## Component Status (1.x — as built)

- [x] **Profile ingestion** — `profile.py`: PDF resume (pdfplumber + AI extraction), LinkedIn URL (direct + DDG fallback), manual entry; AI title suggestion
- [x] **Query expansion** — `ai.py: ai_generate_queries` + validation gate in `main.py` (semantic dedup >85%, min-token, cap 5)
- [x] **Parallel scraping** — `main.py: search_jobs`, ThreadPoolExecutor ≤12, 45s batch timeout, live status table; `ScraperResult` error isolation per source
- [x] **Scrapers** — linkedin (guest API ~10), indeed India (cloudscraper→DDGS, breaks on py3.14), naukri (DDGS, search-page links), remoteok (JSON API), web_search (DDGS site:), serpapi_jobs (optional key), career_sites (untracked, 200+ India/global employers)
- [x] **Deduplication** — `main.py: deduplicate`, rapidfuzz (title 82 / company 88), hybrid approach
- [x] **Heuristic ranking** — `matcher.py`: token-boundary skill matching, weights 35/25/15/15/10, seniority levels, floor = 5 (no zero-score drop)
- [x] **AI re-scoring** — top N (default 30) via `ai_score_job`, parallel ≤8, 60s timeout, JSON extraction fallback
- [x] **TUI** — `prompt_toolkit` full-screen: list/detail/saved modes, keys ↑↓ Enter s o n p l r q, pagination 10/page, highlight
- [x] **Job lifecycle** — `actions.py`: SQLite `~/.matcha/jobs.db`, statuses saved/applied/dismissed/interview/rejected/offer
- [x] **Config & security** — `config.py`: keyring + fernet for ai_key/serpapi_key; Pydantic `ConfigSchema` validation
- [x] **Settings** — `settings.py`: YAML (`matcha.yaml` → `~/.matcha/settings.yaml`) merged over defaults, Pydantic validated
- [x] **Logging** — rotating file `~/.matcha/logs/matcha.log` (5MB × 3), stderr suppressed, noisy libs at WARNING
- [x] **CLI flags** — `--configure`, `--new-profile/-n`, `--non-interactive/-b`, `--config <yaml>`
- [x] **CI/CD** — GitHub Actions 4-stage (lint → typecheck → test → docker build/push GHCR); Docker multi-stage non-root; pre-commit (ruff, whitespace, yaml)
- [x] **Rate limiting + cache** — `scrapers/utils.py`: token bucket per domain, resilient_get, requests-cache SQLite

## Test Baseline (run 2026-08-06, `venv/bin/python -m unittest discover tests -v`)

- **122 tests, 121 pass, 1 known pre-existing failure:**
  `tests/test_days_filter.py :: TestWebSearchSnippetAgeFilter.test_date_string_within`
  — `_is_older_than_days("Posted: June 6, 2026", 7)` returns `True`, test expects `False`.
  **Root cause (F-09): the test is a time-bomb** — "June 6, 2026" is >7 days
  before any run date after mid-June 2026 (it fails now); the function is
  correct. Fix the fixture to be time-relative. Also: **CI only runs
  `tests.test_core`** (F-02) and the matrix misses 3.14 (F-03) — both fixed in
  Phase 0.
- Makefile targets: `make test` / `test-verbose` / `lint` (ruff) / `format` / `static-analysis` (bandit) / `pre-commit` / `check`.

## Git State (2026-08-06)

- Branch `main`, up to date with `origin/main`.
- **Untracked (not yet committed):**
  - `.ai_memory/` (this directory)
  - `revamp/initial-session-prompt.txt`, `revamp/matcha-2.0-strategy.md`, `revamp/opencli-integration-plan.md`, `revamp/phase-0-handoff-prompt.txt`
  - `scrapers/career_sites.py`
- `.gitignore` excludes: `.kilo/`, `improvements.txt`, `__pycache__/`.

## Matcha 2.0 Roadmap (from revamp/matcha-2.0-strategy.md §18)

> Status legend: ⬜ not started · 🟡 in progress · ✅ done

- [ ] **Phase 0 — Foundation (2–3 days, scope expanded):** `src/matcha/` layout + **root shims**; `errors.py`; `probe.py`; `doctor.py` + `sources/base.py` + `sources/registry.py`; provenance fields on `ScraperResult`; refactor `scrapers/*` → `sources/*` (**no behavior change**); `matcha doctor [--json]`; **entry-point migration** (pyproject console script `matcha`, `pip install -e .`, Makefile/CI/Docker/bandit paths); **CI fixes** (full suite + 3.14 matrix); **F-09 test fix**; `career_sites` default-off; LinkedIn location default decision (F-08). *Accept: doctor lists all sources with real status; FULL suite green; `python3 main.py --help` still works.*
- [ ] **Phase 1 — Data quality (3–5 days):** OpenCLI backends for LinkedIn/Indeed (+ consent flow); Exa Web Search backend; Naukri job-page extraction; `agent_reach_io.py`. *Accept: LinkedIn ≥25 results with descriptions (consented); Indeed works on py3.14; doctor shows active backends.*
- [ ] **Phase 2 — Normalize + filters (2–3 days):** `normalization.py` (listed_epoch, salary_int, city, remote_ok); `filters.py` (quality → age → must-skills → location → salary); filter report in TUI + JSON. *Accept: `--days` enforced centrally; unknown-age tagged `[age?]`; garbage dropped.*
- [ ] **Phase 3 — Enrichment (2–3 days):** `sources/enrichment.py` (OpenCLI job-detail, top 30, parallel); model + DB columns; TUI detail fields; apply_url-aware `o`. *Accept: top-30 enriched ≤60s; per-job failures graceful.*
- [ ] **Phase 4 — Ranking recalibration (2–3 days):** confidence-weighted scoring; recency/workplace signals; AI on enriched candidates; flatline detection; verdict pass; provenance tags `[full]/[snippet]/[salary?]/[age?]`. *Accept: score distribution spreads; full-data jobs outrank snippet-guesses.*
- [ ] **Phase 5 — AI provider-agnostic (2–3 days):** `ai/client.py` (OpenAI-compatible REST), presets (Groq/Kilo/OpenRouter/local), model tiers, disk cache, budget guard, `matcha configure ai`. *Accept: works with Groq free tier and with zero config; no key leak; cache hits.*
- [ ] **Phase 6 — Agent + automation (2–3 days):** `--json`; SKILL.md + installer; `matcha watch` + new-vs-seen (`track.py`); optional MCP server. *Accept: an agent drives a full search via the skill; watch surfaces only new jobs.*
- [ ] **Phase 7 — Hardening (1–2 days):** circuit breakers; config hardening (atomic writes, 0600, symlink rejection); GitHub profile enrichment; RSS source; coverage ≥80%; README/docs.

**Design pillars for every phase:** multi-backend richest-first routing
(`opencli ▸ guest-api ▸ ddgs`) · doctor-first observability · filters as a
central pipeline stage · enrichment over listing count · graceful degradation
· provenance is data · failproof by construction.

## Known Gaps / Pain Points (1.x → fixed in 2.0)

1. Thin, stale, noisy data (LinkedIn ~10 no desc; Indeed broken on py3.14; Naukri search-page links; snippet-guessed fields)
2. No per-source health signal / no doctor / no circuit breakers
3. Pydantic models defined but only partially used at runtime
4. AI hardcoded to one provider (legacy `MINIMAX` env var name)
5. No job-age filter, no must-have-skills/salary/location filters, no enrichment
6. `scrapers/__init__.py` is empty (career_sites not exported)
7. 1 pre-existing test failure (time-bomb F-09; fixed in Phase 0)
8. Dedup O(n²) (F-10); LinkedIn default location "United States" (F-08); CI runs only test_core (F-02)

## Key References (revamp/)

- `matcha-2.0-strategy.md` — the plan (Rev 4, source of truth)
- `matcha-2.0-implementation-analysis.md` — **pre-implementation analysis: verified env, OpenCLI interfaces, migration plan, findings F-01..F-23**
- `phase-0-handoff-prompt.txt` — ready-made prompt for starting Phase 0 (scope expanded)
- `opencli-integration-plan.md` — superseded-but-adopted background
