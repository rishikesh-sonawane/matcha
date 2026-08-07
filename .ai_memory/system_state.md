# Current System State — Matcha

> Last verified: 2026-08-07 (Session 21 — no HTTP caching, all-seen "no new jobs" state, all 8 sources alive).
> If any checkbox below conflicts with the actual code, **the code wins** —
> update this file.

## Overview

Matcha **1.x functionality is complete and runs from the 2.0 `src/matcha/`
layout as an installed package.** **Phase 0 + Phase 1 (entry-point migration,
OpenCLI backends, top-N enrichment, Exa Web Search, `agent_reach_io`, Naukrijob-page
extraction) + Phase 2 (normalize + central filters) + Phase 4 (ranking
recalibration) + Phase 5 (provider-agnostic AI client) + Phase 6 (agent +
automation) + Phase 7 (hardening) + Phase 3-adjacent polish (saved-jobs
enriched columns, §9.5 AI verdict pass) + results-quality fixes (junk-title
gate, matcher dilution calibration, remote hint) + Session 17 (AI enabled on
this machine, AI re-scoring moved post-enrichment, Naukri dead listings
dropped, junk-title gate extended) + Session 18 (docs overhaul + doctor AI
status + MCP AI surface) + Session 19 (config-wipe root-cause fix, fernet-only
secret storage, Naukri aggregate-URL gate) are DONE.** All 666 tests pass;
mypy clean; coverage gate ≥80% (81%+). **AI is LIVE on this machine**
(`ai_provider=kilo`; key stored via the fernet file store — no OS keychain;
`check_ai_available()=True`; live-verified: query expansion, AI re-scoring →
top jobs 85.0, 5 verdicts, 35 AI calls/run within the 60-call budget).
**Session 19 fixed the two user-reported failures at the root:** (1) the
interactive TUI's partial `save_config` silently wiped `ai_provider` + the
OpenCLI consents + deleted the stored SerpAPI key on every run — the (AI)
banner showed while ZERO AI calls fired (hence the flat ~54% ceiling);
`save_config` now merges over the persisted file and never touches secrets
the caller didn't pass; (2) Naukri discovery admitted SEARCH/careers listing
pages as jobs and labeled un-enriched rows "full" — discovery now gates on
`/job-listings-*` (the same predicate the job-page backend enriches) and
per-row provenance stays honest `snippet` until a real page merge. Secrets
are now **fernet-only** (`keyring` removed from deps per user preference —
no macOS keychain prompts). **`matcha doctor` now verifies AI
setup in one place** — an `ai` report entry (provider, best/fast models,
`key_set`, `available`; never the key) rendered as an "AI matching" line,
surfaced identically through `matcha doctor --json` and the MCP
`matcha_status` tool. Next: fresh spec — do NOT start a new phase without
one.

## Layout

- `src/matcha/` — real modules: `main.py profile.py ai.py ai_cache.py
  matcher.py config.py settings.py models.py actions.py` + `errors.py
  probe.py utils.py doctor.py`
- `src/matcha/sources/` — `base.py` (Source ABC) + `__init__.py` (ALL_SOURCES
  registry) + 8 source modules + `constants.py utils.py` +
  **`breaker.py`** (Phase 7 circuit breakers, persisted source_state.json) +
  **`rss.py`** (Phase 7 RSS source)
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
- `src/matcha/ai.py` — **provider-agnostic AI client** (Phase 5): `PROVIDERS`
  presets (Groq/Kilo/OpenRouter/OpenAI/local-no-key), `_get_model(tier)`
  best/fast (env → config → settings → preset), thread-safe per-run budget
  guard (`ai.max_calls`), `_run_with_cache` wiring
- `src/matcha/ai_cache.py` — **AI result disk cache** (Phase 5): SQLite,
  keyed `sha256(task+model+messages)`, TTL, lazy prune, env-overridable path,
  opt-in via `settings.ai.cache_ttl` (default 0)
- `src/matcha/track.py` — **new-vs-seen tracking** (Phase 6): `seen_urls`
  table in the shared jobs.db; `mark_seen`/`partition_new`/`stats`; consumed
  only by `watch`
- `src/matcha/mcp_server.py` — **optional MCP server** (Phase 6): guarded
  `mcp>=1.0` extra; FastMCP `matcha_status` + `matcha_search` tools,
  credential-scrubbed errors; `matcha_status` now includes the doctor `ai`
  entry (provider/models/key_set/available)
- `src/matcha/skill/` — **bundled agent SKILL.md** (Phase 6): bilingual
  zh+en, YAML frontmatter, package-data shipped; `matcha.skill` package also
  hosts `install_skill`/`uninstall_skill`/`default_destinations`
- **Phase 7 hardening** — `utils.py` (ensure_no_symlink_path /
  atomic_write_text / read_small_text_no_follow / make_private_dir),
  `errors.py` (ConfigSecurityError), `config.py` (atomic 0600 writes,
  symlink rejection, reads-never-create, 1MB caps), `sources/breaker.py`
  (persisted circuit breakers), `sources/rss.py` (feedparser RSS),
  `profile.enrich_github_profile` + `agent_reach_io.gh_repos` + `matcha
  github`
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
      expired postings (search-page redirect) detected and **DROPPED**
      (Rev 16: `_EXPIRED` sentinel → removed from the batch, URLs logged;
      fetch/parse failures still keep the snippet row with `enrich_error`);
      per-job isolation, provenance `data_quality` full/partial +
      `enrich_source="job-page"`; `check()` hermetic
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
      60s timeout; **gated to enriched candidates** (`ai_eligible`); **Rev 16
      ordering fix:** `run_search` now heuristically ranks → enriches →
      `_ai_rescore` (post-enrichment) → re-ranks → `_apply_flatline_guard`
      (shared helper) → verdicts, so the AI judge scores real descriptions;
      `rank_jobs(use_ai=True)` keeps the pass for direct callers
- [x] **Provider-agnostic AI client (Phase 5, §10.2)** — OpenAI-compatible
      REST to `{base_url}/chat/completions`; presets Groq/Kilo/OpenRouter/
      OpenAI/local (local needs no key); model tiers best (scoring/profile) /
      fast (queries/titles); per-run budget guard `ai.max_calls` (TUI
      `AI budget: N/M used (R left)` line); opt-in disk cache
      `ai.cache_ttl` keyed on task+model+messages (self-invalidating on
      provider/prompt change); `matcha --configure` provider wizard;
      keys stay in keyring/fernet; zero config ⇒ heuristic-only
- [x] **Agent + automation surface (Phase 6, §13)** — shared `run_search`
      pipeline (quiet mode) drives TUI + `matcha search`/`watch`/MCP;
      `search --json` document (`build_search_payload`, jobs[] with
      match_score + reasons); `track.py` seen_urls powers `watch`
      (new-vs-seen, writes `~/.matcha/latest.json`); bilingual SKILL.md +
      `matcha skill --install/--uninstall`; optional guarded MCP server
      (`matcha mcp`, `pip install -e '.[agent]'`)
- [x] **Circuit breakers (Phase 7, §6.7)** — per-source state persisted in
      `~/.matcha/source_state.json`; 3 consecutive failures → 30-min
      cooldown (search skips the source); any success resets; atomic 0600 /
      symlink-rejected IO, thread-safe (`_lock`), doctor reports `circuit`
- [x] **Config hardening (Phase 7, §17)** — atomic owner-only writes
      (0600/0700), component-wise symlink rejection, reads never create
      files, 1MB size caps; fernet-key write TOCTOU guarded
- [x] **GitHub profile enrichment (Phase 7, §11)** — `matcha github enrich`
      merges `gh api user/repos` language+topic skills into profile.json;
      read-only discipline (never `gh auth status`); graceful when gh absent
- [x] **RSS source (Phase 7, §6.2)** — `sources/rss.py` (feedparser):
      company/job-board feeds from `sources.rss.feeds` in settings; tier 0
      default-on; `data_quality=partial`
- [x] **TUI** — prompt_toolkit full-screen: list/detail/saved modes, keys ↑↓ Enter s o n p l r q, pagination 10/page
- [x] **Job lifecycle** — `actions.py`: SQLite `~/.matcha/jobs.db`, statuses saved/applied/dismissed/interview/rejected/offer
- [x] **Config & security** — keyring + fernet for ai_key/serpapi_key; Pydantic validation
- [x] **Settings** — YAML (`matcha.yaml` → `~/.matcha/settings.yaml`), Pydantic validated
- [x] **Logging** — rotating file `~/.matcha/logs/matcha.log` (5MB × 3)
- [x] **CLI** — `--configure`, `--new-profile/-n`, `--non-interactive/-b`, `--config`,
      **`doctor [--json]`** (NEW — per-source health report)
- [x] **Rate limiting + cache** — token bucket per domain, resilient_get, requests-cache SQLite

## NEW — Doctor (`venv/bin/python main.py doctor`)

- `check_all(config)` → per-source entries
  `{name: {status, name, message, tier, backends, active_backend}}` **plus an
  `ai` entry** `{status, name, message, provider, provider_label,
  known_provider, requires_key, key_set, url, model_best, model_fast,
  available}` (Session 18) — with per-source + AI exception isolation
  (status="error") and credential scrubbing (URL included). AI status:
  `ok`=wired / `off`=heuristic-only / `warn`=partial (key-without-provider,
  unknown provider, missing pieces).
- Live sample (2026-08-07): LinkedIn `ok` (guest-api active) · Indeed `warn`
  (anti-bot gated — the known py3.14/cloudscraper issue) · Naukri `ok` · RemoteOK `ok`
  (HTTP 200) · Web Search `ok` · SerpAPI `off` (no key) · Career Sites `off` (default);
  **AI `ok` — Kilo Gateway (default) · best/fast kilo-auto/small · key set**.
  Status: 4/7 sources ready + AI ready.

- [x] **Session 20 — working links + no repeat results (DONE 2026-08-07):**
  live link audit proved LinkedIn `/job-apply/` links 404 while `jobs/view`
  URLs are stable → `stable_apply_url()` normalizes at parse + enrichment;
  HTTP cache TTL 5 min (env-tunable, `import os` fixed); TUI joins
  `seen_urls` (hide-seen default, `h` toggle, save retires); provenance tags
  escaped + Match column widened so `[full]/[age?]` finally render. 675/675
  tests; ruff/mypy clean; coverage 81%.

- [x] **Session 21 — no caching + all sources alive (DONE 2026-08-07):**
  HTTP cache OFF by default (`MATCHA_HTTP_CACHE_TTL=0`, plain session, stale
  53MB cache purged); all-seen runs show a "No new jobs" state instead of
  replaying the same list; junk gate + "Job Listings"/"Join Our Team";
  Indeed empty-title recovery via job-detail (primary query ≤8); SerpAPI
  apply_options URLs (was dropping 43/43); per-source query caps + batch
  timeout 45→75s. Live: 230 found/140 kept, Indeed 92%, Google 95%, Career
  Sites 85%, 0 junk, 0 ephemeral links. 680/680 tests; ruff/mypy clean;
  coverage 81%.

## Test Baseline (2026-08-07)

- **680/680 tests pass** (`unittest discover tests` AND `pytest tests/`).
  675 at end of Session 20; +5 from Session 21 (Indeed empty-title recovery
  ×2, per-source query caps, per-query Indeed recovery flag, SerpAPI
  apply_options/source_link URL fallback).
  675/675 at end of Session 20: +9 (LinkedIn stable apply-url normalization
  ×4, `_visible_ranked` seen-hiding + table `[seen]` marker, escaped
  provenance-tag rendering, prompt_loop partial-seen + all-seen notes) +
  the utils.py `import os` crash fix.
  666/666 at end of Session 19: +4 (config partial-save preserves
  ai_provider/consents ×2, Naukri aggregate-URL drop at discovery, beyond-cap
  rows stay honest snippet) + junk-title case additions + 1 test renamed
  (aggregate drop).
  659 at end of Session 18 (docs overhaul); +8 doctor AI tests from Session 18 (ai_status
  snapshot resolution, ok/off/warn/unknown-provider/error status mapping,
  URL credential scrub, key-leak guard, format + JSON `ai` entry) +1 MCP
  `matcha_status` AI-entry test.
  646 at end of Session 16; +3 new from Session 17 (Naukri expired-drop ×2,
  run_search AI-rescore-after-enrichment) + case additions (junk-title
  listing pages, live-page-not-misdetected).
  623 at end of Phase 7; +23 from Session 16 (actions enriched-columns/
  migration/UPSERT tests, ai verdict parse/gate/budget/cache, run_search
  verdict wiring + payload, junk-title + remote-hint filter tests, matcher
  dilution regressions).
  455 at end of Phase 6; +168 from Phase 7 suites: `test_breaker.py` (9),
  `test_config_hardening.py` (27), `test_rss.py`, `test_github_enrich.py`,
  `test_main_surface.py` (31), `test_profile_extra.py`, `test_actions.py`,
  `test_sources_utils.py`, `test_base.py`, `test_settings_extra.py`,
  `test_coverage_sources.py` (49).
- New: `tests/test_probe.py`, `tests/test_doctor.py`, `tests/test_source_contracts.py`
  (registry unique names, check() status contract, ordered_backends permutation +
  override, doctor result shape, crash isolation, credential scrubbing),
  `tests/test_opencli.py` (46), `tests/test_enrichment.py` (17),
  `tests/test_exa_backend.py` (36), `tests/test_agent_reach_io.py` (31),
  `tests/test_naukri_job_page.py` (24), `tests/test_normalization.py` (26),
  `tests/test_filters.py` (38), `tests/test_ai_client.py` (29),
  `tests/test_track.py` (6), `tests/test_skill.py` (5),
  `tests/test_agent_surface.py` (13).
- Quality gates all green: `ruff check .`, `ruff format --diff .`, `pre-commit run
  --all-files`, `bandit -r ... -lll`, **mypy clean (0 errors, 38 files)**,
  **coverage ≥80% (`make test-coverage`, `fail_under=80` in
  [tool.coverage.report])**.
- Makefile targets: `run` / `test` / `test-coverage` / `lint` / `format` /
  `static-analysis` / `pre-commit` / `check`.

## Git State (2026-08-06, post-Phase-7)

- Branch `main`, ahead of `origin/main`. Committed: `bf70014` (Phase 1-2-4),
  `bb87e7c` (docs sync), `430c323` (Phase 5), `9c062bb` (Phase 6).
  **Phase 7 is the current uncommitted work** (breaker.py / rss.py /
  utils.py / config.py / errors.py / profile.py / agent_reach_io.py /
  actions.py / settings.py / base.py / main.py / doctor.py + 11 test files
  + pyproject/CI/Makefile + docs). Nothing is pushed.

## Matcha 2.0 Roadmap (from revamp/matcha-2.0-strategy.md §18)

> Status legend: ⬜ not started · 🟡 in progress · ✅ done

- [x] **Phase 0 — Foundation (DONE 2026-08-06):** `src/matcha/` layout + root shims; `errors.py`; `probe.py`; `doctor.py` + `sources/base.py` + `sources/registry`; provenance fields; every scraper → Source subclass (**no behavior change**); `matcha doctor [--json]`; **entry-point migration deferred to Phase 1**; CI fixes (full suite + 3.14); F-09 test fix; `career_sites` default-off; F-08 India default. *Accept met: doctor lists all sources with real status; 152/152 tests green; `python3 main.py --help` works.*
- [x] **Phase 1 — Data quality (DONE 2026-08-06):** entry-point migration (console script `matcha = matcha.main:main`, `pip install -e .`, root shims + `scrapers/` deleted, bandit `-c pyproject.toml -r src/matcha -lll`, pyinstaller via console-script entry, Docker installs the package + `python3 -m matcha.main`); **OpenCLI backends for LinkedIn/Indeed (+ consent flow)**; **top-N enrichment** (`sources/enrichment.py`, Jina zero-config fallback); **Exa Web Search backend** (`backends/mcporter.py` + `backends/exa.py`, DDGS fallback); **`agent_reach_io.py`** (doctor snapshot + degradation); **Naukri job-page extraction** (real `job-listings-*` parse via embedded JSON / Jina render, DDGS fallback). *Accept met: LinkedIn ≥25 results with descriptions (consented); Indeed works on py3.14; doctor shows active backends; `matcha doctor --json` runs via the installed console script; Naukri yields real descriptions/salary.*
- [x] **Phase 2 — Normalize + filters (DONE 2026-08-06):** `normalization.py` (listed_epoch, salary_int LPA, city/region, remote_ok); `filters.py` (quality → age → must-skills → location → salary with per-stage `FilterReport` counts + isolation); `--days` enforced centrally (age filter = final authority); unknown-age `[age?]` / unknown-salary `[salary?]` tags; TUI filter summary line; `Settings.filters` + `Profile` §14 fields. *Accept met: `--days` enforced centrally; unknown-age tagged; garbage dropped; counts shown.*
- [ ] **Phase 3 — Enrichment (2–3 days):** `sources/enrichment.py` (OpenCLI job-detail, top 30, parallel); model + DB columns; TUI detail fields. *Accept: top-30 enriched ≤60s; per-job failures graceful.*
- [x] **Phase 4 — Ranking recalibration (DONE 2026-08-06):** confidence-weighted heuristic (data-richness × dimensions); recency/workplace/must-skill signals; `must_skills_soft` rank cap; AI pass gated to enriched candidates; flatline detection + optional normalization (`ranking.normalize_scores`); `[full]`/`[partial]`/`[snippet]` provenance tags; per-row provenance stamping at ingest. *Accept met: score distribution spreads; full-data jobs outrank snippet-guesses.*
- [x] **Phase 5 — AI provider-agnostic (DONE 2026-08-06):** `ai.py` + `ai_cache.py` (OpenAI-compatible REST), presets (Groq/Kilo/OpenRouter/OpenAI/local-no-key), model tiers best/fast, opt-in disk cache, per-run budget guard, `matcha --configure` provider wizard. *Accept met: works with Groq free tier and zero config (heuristic-only); no key leak; cache hits on re-run.*
- [x] **Phase 6 — Agent + automation (DONE 2026-08-06):** `run_search` shared pipeline; `search --json` document; `track.py` seen_urls + `matcha watch` new-vs-seen (writes latest.json); SKILL.md + installer (`matcha skill --install/--uninstall`); optional guarded MCP server (`matcha mcp`, `agent` extra). *Accept met: agent drives a full search via the skill; watch surfaces only new jobs.*
- [x] **Phase 7 — Hardening (DONE 2026-08-06):** circuit breakers (persisted `source_state.json`, thread-safe); config hardening (atomic 0600/0700, symlink rejection, reads-never-create, size caps); GitHub profile enrichment (`matcha github enrich`); RSS source (feedparser); coverage ≥80% gate (81%+, CI + Makefile); **mypy debt cleanup (36 → 0 errors)**. Plus real-bug fixes surfaced by the new suites (actions commit, settings deepcopy, extract_experience case). *Accept met: doctor shows circuit state; config writes atomic + symlink-rejected; mypy clean; coverage gate green.*
- [x] **Phase 3-adjacent polish + results quality (DONE 2026-08-06):** saved-jobs persist enriched/normalized fields (`actions.py` `ENRICHED_COLUMNS` + idempotent `_migrate` + UPSERT `save_job` + `job_entry`; Saved view Salary/Posted); §9.5 AI verdict pass (`ai.py` `ai_verdict`, `settings.ai.verdict_k` default 5, detail-panel + JSON `verdict`); junk listing-page titles dropped by the quality gate (`_is_junk_title`); matcher calibration (skill-ratio saturation `_SKILL_RATIO_CAP=10` + job-title-coverage title dimension) — live-verified 24.7→67 for an enriched DevOps Engineer; `filter_notes` remote-exclusion hint; track/actions sqlite ResourceWarnings fixed (py3.14 context managers never close); comprehensive test hermeticity vs live breaker state. 646/646 tests; ruff/format/mypy/bandit clean; coverage 81%.
- [x] **Session 17 — AI live + results quality round 2 (DONE 2026-08-06):** diagnosed + fixed the real reason "AI can't make smart decisions": the user's stored Kilo key (`MINIMAX` env, 67-char `sk-`) was never wired (`ai_provider` empty ⇒ `check_ai_available()=False`) → `configure_provider('kilo')`, live-verified end-to-end. AI re-scoring moved to AFTER enrichment (`_ai_rescore` + shared `_apply_flatline_guard`) so the judge scores real descriptions (live: top jobs 85.0, verdicts "Your 4 years of AWS/Terraform expertise…", 36/60 AI calls). Naukri dead postings (expired → search-page redirect) now DROPPED (`_EXPIRED` sentinel; URLs logged). Junk-title gate extended (`top companies hiring for …`). 650/650 tests; ruff/format/mypy/bandit clean.
- [x] **Session 18 — docs overhaul + doctor AI status + MCP AI surface (DONE 2026-08-07):** README rewritten + verified against source (full env-var reference + AI resolution order, exact AI preset models, corrected SerpAPI YAML sample — key is a `--configure` secret, CLI command reference, config precedence, `~/.matcha` layout, Docker/Makefile) + QUICKSTART.md (5 commands). `ai.py ai_status()` + doctor `ai` entry (ok/off/warn/error, scrubbed URL, key never leaks, "AI matching" section in the text report); MCP `matcha_status` surfaces the same `ai` entry (docstrings + hermetic test). 659/659 tests; ruff/format/mypy clean.

**Design pillars:** multi-backend richest-first routing · doctor-first observability ·
filters as a central pipeline stage · enrichment over volume · graceful degradation ·
provenance is data · failproof by construction.

## Known Gaps / Pain Points (1.x → fixed in 2.0)

1. Thin, stale, noisy data — **Phases 1–2 fixed the big levers** (OpenCLI backends, top-N enrichment, Exa web, Naukri job-page, central filters); LinkedIn still thin on this machine until the Chrome extension is connected; Naukri DDGS index is stale — **expired postings now dropped (Rev 16)**, unverified snippets beyond the 8/batch page cap remain
2. Re-rank on enriched signals (step 8 of §7) + `must_skills_soft` rank cap + `[full]`/`[snippet]` tags — Phase 4
3. Pydantic models defined but only partially used at runtime (Job/Profile now extended; not yet the runtime boundary) — Phase 4+
4. ~~AI hardcoded to one provider (legacy `MINIMAX` env var name)~~ **RESOLVED Phase 5** — provider presets + env/config/settings overrides; `MINIMAX` kept as the legacy env alias
5. Saved-jobs DB doesn't persist enriched/normalized fields (salary, salary_int, apply_url, listed_epoch) — Phase 3-adjacent polish
6. OpenCLI extension currently disconnected on this machine (daemon up, ext down) — opencli path untestable live until Chrome + extension are up; falls back correctly
9. mcporter not installed — Exa backend untestable live; `exa_status()==off` → Web Search stays on DDGS; install + `mcporter config add exa https://mcp.exa.ai/mcp --scope home` to exercise
10. agent-reach not installed — `doctor_snapshot()` returns None + one-time warning; all `agent_reach_io` health signals degrade to own probes. gh IS installed + authenticated — `gh_profile()` works live (read-only hosts.yml, never `gh auth status`)
11. Naukri client-rendered + anti-bot — plain requests get an empty SPA shell; jobapi requires CSRF session; the Jina-render path works (verified live) and expired postings redirect to search pages (skipped)
7. ~~mypy: 24 pre-existing legacy errors~~ **RESOLVED Phase 7** — 0 errors across 38 files
8. Dedup O(n²) (F-10) — Phase 4 (deferred)
9. OpenCLI extension disconnected on this machine — opencli path untestable live; falls back correctly

## Key References (revamp/)

- `matcha-2.0-strategy.md` — the plan (Rev 16, source of truth; §6.2/§6.3 corrected for OpenCLI + Exa/mcporter work, §6.5 + §6.7 + §7 + §8 + §9.3 + §10.2 + §11 + §13 + §17 marked implemented)
- `matcha-2.0-implementation-analysis.md` — pre-implementation analysis: verified env, OpenCLI interfaces, migration plan, findings F-01..F-23
- `phase-0-handoff-prompt.txt` — Phase 0 spec (implemented 2026-08-06)
- `opencli-integration-plan.md` — superseded-but-adopted background
