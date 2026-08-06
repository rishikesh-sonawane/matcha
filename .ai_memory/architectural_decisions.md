# Architectural Decisions (ADR)

> Log of significant decisions for Matcha. New ADR whenever a significant
> decision lands. Older, already-implemented 1.x decisions are kept at the
> bottom under "Implemented (1.x)".

## Matcha 2.0 Decisions

### ADR 01: Rebuild as "Matcha 2.0" around the data layer, not the ranking layer
- **Status:** Accepted (2026-08-06, strategy rev 2)
- **Decision:** Matcha's core promise fails because of a **data-quality bottleneck** (thin/stale/noisy scraped data), not ranking. The rebuild therefore prioritizes acquisition: multi-backend sources, enrichment, centralized filters — ranking is a filter on top of good data ("Data first, ranking second").
- **Context:** LinkedIn guest API ~10 results/no descriptions; Indeed cloudscraper segfaults on Python 3.14; Naukri yields search-page links; ranking on empty text produces the flat "92% everywhere" scoreline.
- **Consequences:** 8-phase roadmap (P0 foundation → P7 hardening); scrapers refactored into `sources/` with per-source backends; ranking work deferred to Phase 4. Source of truth: `revamp/matcha-2.0-strategy.md`.

### ADR 02: Multi-backend routing, richest-first, with real probes
- **Status:** Accepted (2026-08-06)
- **Decision:** Each source gets an **ordered backend list** (e.g. LinkedIn: `opencli ▸ guest-api ▸ ddgs`) with fallback on failure; health is determined by **actually executing** the tool (ported `probe.probe_command`), never `shutil.which` alone. The active backend is always visible.
- **Context:** Ported from Agent-Reach's `Channel` pattern; a broken backend must degrade to the next one instead of returning empty.
- **Consequences:** `sources/base.py` (Source ABC) + `sources/registry.py` (circuit breakers persisted to `~/.matcha/source_state.json`); `probe.py` with `ProbeResult(status: ok|missing|broken|timeout|error)`; doctor reports per-source status + active backend + fix hint.

### ADR 03: Filters are a centralized pipeline stage, enforced centrally
- **Status:** Accepted (2026-08-06)
- **Decision:** All filters (data quality → job age → must-have skills → location/remote → salary) live in one `filters.py`, run on normalized jobs, each returning `(keep, reason)` with counts logged and shown (`ingest=412 normalize=412 dedup→287 filter→96 age_dropped=142 …`). `--days` is the **final authority** — a source lying about age can't leak old jobs in.
- **Context:** User explicitly required a job-age filter and "good relevant jobs"; per-scraper ad-hoc filtering is untrustworthy.
- **Consequences:** `normalization.py` (listed_epoch, salary_int LPA, city synonyms, remote_ok); unknown-age jobs tagged `[age?]` (never falsely dropped; `--strict-age` drops them); settings.yaml `filters:` section.

### ADR 04: AI brain = provider-agnostic REST; MCP only for data plumbing
- **Status:** Accepted (2026-08-06)
- **Decision:** AI reasoning (profile extraction, query gen, scoring, verdict) goes through **OpenAI-compatible REST** (`POST {base_url}/chat/completions`) with provider presets (Groq / Kilo Gateway / OpenRouter / OpenAI / Ollama-local) and **no API key required** (heuristic-only mode). MCP is used only for Exa (via `mcporter`) and an optional Matcha MCP server — never required.
- **Context:** Current AI is hardcoded to one provider with a confusing `MINIMAX` env var; user wants no lock-in, free-tier friendly, works without AI.
- **Consequences:** `ai/client.py`, `ai/prompts.py` (versioned, single-sourced), `ai/tasks.py`, `ai/cache.py` (SQLite, TTL 24h), budget guard `max_calls: 60`, model tiers `model_fast`/`model_best`, `matcha configure ai` wizard, `agent_reach_io.seed_ai_config` (borrow Groq key from Agent-Reach).

### ADR 05: Robustness & observability are features, not afterthoughts
- **Status:** Accepted (2026-08-06)
- **Decision:** Failproof-by-construction: per-source/per-job isolation, real probing, circuit breakers (3 strikes → cooldown), retries with backoff, per-source timeouts, caching, offline-friendly, and a `doctor` pre-flight so no failure is silent. Typed error taxonomy (`errors.py`), zero bare `except`, credential scrubbing in all output.
- **Context:** 1.x silently swallowed errors in 12+ locations; no health signal; a single dead scraper silently shrank results.
- **Consequences:** `doctor.py`, `probe.py`, `errors.py`, per-source circuit state; rotating file logging; TUI startup line per source.

### ADR 06: Human TUI and agent surface are equal front-ends
- **Status:** Accepted (2026-08-06, user scope decision)
- **Decision:** Identical pipeline for the TUI and for agents (`--json`, SKILL.md, optional MCP). Agent surface is first-class, not an afterthought.
- **Context:** User chose "human TUI and agent surface both equally" in the 4-question scope prompt.
- **Consequences:** Phase 6 delivers `--json`, `skill/SKILL.md` (zh+en) with installer, `matcha watch` + new-vs-seen `track.py`, optional MCP server mirroring Agent-Reach.

### ADR 07: Enrichment-only — never auto-submit applications
- **Status:** Accepted (2026-08-06, user scope decision)
- **Decision:** Scope is **enrichment only**: fetch full job detail (description, salary, apply_url, workplace, applicants, listed) and open the apply page. No automated submission.
- **Context:** User explicitly scoped out apply automation; OpenCLI `job-detail` is mature while application flow isn't.
- **Consequences:** `sources/enrichment.py` (top N=30, parallel ≤5, per-job isolation, graceful failure); `o` opens `apply_url` when present else job URL; saved jobs persist enriched fields.

### ADR 08: Existing scrapers stay as named fallbacks, never deleted
- **Status:** Accepted (2026-08-06)
- **Decision:** OpenCLI/Exa/Agent-Reach are optional premium backends; the existing scrapers remain as zero-config fallbacks and are refactored into `sources/*` Source subclasses (parsers kept as backends).
- **Context:** No Node.js/Chrome/consent guarantee; "runs fully without Agent-Reach and fully without AI".
- **Consequences:** Phase 0 is a behavior-neutral refactor of `scrapers/*` → `sources/*`; every source gets a `check()`; `scrapers/career_sites.py` included.

### ADR 09: India-focused, region-configurable
- **Status:** Accepted (2026-08-06)
- **Decision:** India is the primary market (Naukri, India career sites, `in.indeed.com`), but region is configurable (`indeed_domain`, city/region synonym tables, remote/hybrid/onsite preference).
- **Context:** User chose "India-focused" in the scope prompt; career_sites.py already covers 200+ Indian + global employers.
- **Consequences:** `indeed_domain` config key exists; `normalization.py` city synonym table (Pune/Poona); location/remote filter semantics: exact city ≥ region ≥ remote-friendly.

### ADR 10: Persist AI memory in git; commit at session end
- **Status:** Accepted (2026-08-06, re-affirmed from prior project convention)
- **Decision:** The `.ai_memory/` directory is committed to the repo and updated continuously; `git commit` at the end of a working session makes recovery deterministic.
- **Context:** AI assistants are stateless; chat history is disposable, the repo + `.ai_memory/` are the source of truth.
- **Consequences:** `session_log.md` is append-only (crash-safe write-ahead log); `system_state.md`/`active_task.md` are updated per step; recovery = `git status`/`git diff` + journal tail.

---

## Implemented (1.x) — historical decisions, already in the code

### ADR-1x: Structured logging, file-only, Rich TUI clean (2026-06-09, docs/superpowers/plans/2026-06-09-cli-ux-fix.md)
All logging to rotating file `~/.matcha/logs/matcha.log`; no StreamHandler → Rich Live/Progress never corrupted; noisy libs (primp, httpx, ddgs, urllib3) at WARNING; `os._exit(0)` in `main()` kills orphaned ddgs threads.

### ADR-2x: ScraperResult error isolation (blueprint.md ADR-2)
Every scraper returns `ScraperResult(jobs, errors, source)`; one failing source never blocks others; errors surfaced in the TUI status table.

### ADR-3x: Heuristic scoring overhaul (blueprint.md ADR-3/5, implemented)
Balanced weights (Skills 35 / Title 25 / Seniority 15 / Location 15 / Keywords 10), token-boundary skill matching, 4 seniority levels, floor = 5 (no zero-score drop), AI top_n 15→30, AI timeout 300→60s.

### ADR-4x: Secure credential storage (blueprint.md ADR-6, implemented)
`keyring` (OS-native) with `cryptography.fernet` fallback; non-secrets in JSON; no plaintext keys.

### ADR-5x: Rate-limiter compliance + shared constants (blueprint.md ADR-8/9, implemented)
All HTTP incl. DDGS routed through `resilient_get()` + per-domain token bucket (`scrapers/utils.py`); shared stop-word/pattern constants in `scrapers/constants.py`.

### ADR-6x: Iterative run loop + dedup fix (blueprint.md ADR-10/11, implemented)
`run()` with a `while` loop (no recursive `main()`); dedup fixed for empty-company edge case with exact-hash pass first.

### ADR-7x: Pydantic config/settings validation (blueprint.md ADR-7, implemented)
`ConfigSchema` (config.py) + `Settings` (settings.py) validated at load; `docker-compose.yml` fixed; `indeed_domain` configurable.
