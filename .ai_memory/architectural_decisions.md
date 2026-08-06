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
- **Status:** **Implemented** (Phase 1, 2026-08-06)
- **Decision:** Each source gets an **ordered backend list** (e.g. LinkedIn: `opencli ▸ guest-api ▸ ddgs`) with fallback on failure; health is determined by **actually executing** the tool (ported `probe.probe_command`), never `shutil.which` alone. The active backend is always visible.
- **Context:** Ported from Agent-Reach's `Channel` pattern; a broken backend must degrade to the next one instead of returning empty.
- **Consequences:** `sources/base.py` (Source ABC) + `sources/registry.py` (circuit breakers persisted to `~/.matcha/source_state.json`); `probe.py` with `ProbeResult(status: ok|missing|broken|timeout|error)`; doctor reports per-source status + active backend + fix hint.

### ADR 03: Filters are a centralized pipeline stage, enforced centrally
- **Status:** **Implemented** (Phase 2, 2026-08-06)
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
- **Status:** **Implemented** (Phase 1 part 3, 2026-08-06)
- **Decision:** Scope is **enrichment only**: fetch full job detail (description, salary, apply_url, workplace, applicants, listed) and open the apply page. No automated submission.
- **Context:** User explicitly scoped out apply automation; OpenCLI `job-detail` is mature while application flow isn't.
- **Consequences:** `sources/enrichment.py` (top N=30, parallel ≤5, per-job isolation, graceful failure); `o` opens `apply_url` when present else job URL; saved jobs persist enriched fields.

### ADR 08: Existing scrapers stay as named fallbacks, never deleted
- **Status:** **Implemented** (Phase 0/1, 2026-08-06)
- **Decision:** OpenCLI/Exa/Agent-Reach are optional premium backends; the existing scrapers remain as zero-config fallbacks and are refactored into `sources/*` Source subclasses (parsers kept as backends).
- **Context:** No Node.js/Chrome/consent guarantee; "runs fully without Agent-Reach and fully without AI".
- **Consequences:** Phase 0 is a behavior-neutral refactor of `scrapers/*` → `sources/*`; every source gets a `check()`; `scrapers/career_sites.py` included.

### ADR 09: India-focused, region-configurable
- **Status:** Accepted (2026-08-06)
- **Decision:** India is the primary market (Naukri, India career sites, `in.indeed.com`), but region is configurable (`indeed_domain`, city/region synonym tables, remote/hybrid/onsite preference).
- **Context:** User chose "India-focused" in the scope prompt; career_sites.py already covers 200+ Indian + global employers.
- **Consequences:** `indeed_domain` config key exists; `normalization.py` city synonym table (Pune/Poona); location/remote filter semantics: exact city ≥ region ≥ remote-friendly.

### ADR 10: Persist AI memory in git; commit at session end
- **Status:** **Active convention** (2026-08-06, re-affirmed from prior project convention)
- **Decision:** The `.ai_memory/` directory is committed to the repo and updated continuously; `git commit` at the end of a working session makes recovery deterministic.
- **Context:** AI assistants are stateless; chat history is disposable, the repo + `.ai_memory/` are the source of truth.
- **Consequences:** `session_log.md` is append-only (crash-safe write-ahead log); `system_state.md`/`active_task.md` are updated per step; recovery = `git status`/`git diff` + journal tail.

### ADR 11: Naukri job-page fetch = Jina Reader render, not direct HTML
- **Status:** **Implemented** (Phase 1, 2026-08-06)
- **Decision:** `sources/naukri.py` gets backends `["job-page", "ddgs"]`. The
  job-page backend discovers real `job-listings-*` URLs via DDGS, then fetches
  each posting **through Jina Reader** (`r.jina.ai/<url>`, zero-config,
  browser-like) and parses the rendered markdown; a direct GET with embedded
  `application/ld+json` JobPosting / `__NEXT_DATA__` parse is tried first and
  wins if Naukri ever server-renders again.
- **Context:** Verified live (2026-08-06): Naukri serves a client-rendered
  Next.js RSC shell to plain requests (empty `jobDetails:[]`, no JSON-LD, no
  meta/og) and the internal `jobapi/v3` endpoints reject unauthenticated calls
  (404/405 without a CSRF session). DDGS-indexed postings are often expired
  (search-page redirect) — detected and kept as snippets.
- **Consequences:** Naukri now yields genuine description/salary/experience/key
  skills/apply URL; expired postings degrade gracefully; `check()` stays
  hermetic (library-based) so doctor/contract tests stay offline-safe.

### ADR 12: Exa/mcporter = read-only config probe + dual-syntax call, DDGS fallback
- **Status:** **Implemented** (Phase 1, 2026-08-06)
- **Decision:** `backends/mcporter.py` inspects mcporter config **read-only**
  (`MCPORTER_CONFIG` → `~/.mcporter/mcporter.json{,c}` → `<cwd>/config/mcporter.json`),
  never starts mcporter, never expands `imports` (credential boundary).
  `backends/exa.py` shells `mcporter call` with **dual syntax** (current
  openclaw 0.8+ `key=value` first, legacy 0.7 DSL retried on failure),
  retries once without `includeDomains`, and treats error envelopes as
  failures. Web Search dispatches exa-when-configured ▸ DDGS.
- **Context:** The mcporter CLI was rewritten upstream (0.7 DSL → 0.8+ syntax);
  remote servers can't be verified without running them, so configured-but-
  unverified is `warn`, never `ok`; absent → graceful DDGS fallback (verified live).
- **Consequences:** No credential widening, honest doctor status, zero-config
  semantic search when the user installs mcporter.

### ADR 13: `agent_reach_io.py` = snapshot-first health with own-probe degradation
- **Status:** **Implemented** (Phase 1, 2026-08-06)
- **Decision:** When Agent-Reach is installed, health reads come from
  `agent-reach doctor --json` (TTL-cached 30s, credential-scrubbed); when
  absent, Matcha uses its own probes + a one-time warning hint (F-14).
  `gh_profile()` never runs `gh auth status` (writes a device-id) — it reads
  `GH_TOKEN`/`GITHUB_TOKEN` env or a github.com `hosts.yml` entry, then
  `gh api user` with read-only env. `seed_ai_config()` borrows `groq_api_key`
  from `~/.agent-reach/config.yaml` (symlink-rejected, ≤1MB).
- **Context:** Agent-Reach is an installer+doctor tool, not a wrapper; reusing
  its health signal avoids re-implementing probes, and read-only config reads
  keep the credential boundary tight.
- **Consequences:** Six functions (`agent_reach_available`, `doctor_snapshot`,
  `opencli_ready`, `exa_search`, `gh_profile`, `seed_ai_config`) all degrade
  to zero-config behavior when agent-reach is absent (verified live).

### ADR 14: Ranking is confidence-weighted; signals reward fresh/remote/must-have
- **Status:** **Implemented** (Phase 4, 2026-08-06)
- **Decision:** `matcher.compute_relevance` keeps the 35/25/15/15/10 max
  dimension weights but scales the text-derived skills+keyword dimensions by
  a **data confidence** factor (data_quality `full` 1.0 / `partial` 0.85 /
  `snippet` 0.7; description-length proxy only for unstamped rows) so a match
  on an empty field contributes ~0. Adds bounded signals: recency (+5/3/1 by
  `listed_epoch`), workplace agreement (+3 vs `remote_preference`),
  must-have-skill coverage (+2 each, cap +6, synonym-aware). Jobs kept by
  `soft_must_skills` are **capped at 45** so they never outrank hard matches.
  The AI pass runs **only on enriched candidates** (`ai_eligible`), and a
  flatline guard (`detect_flatline`/`normalize_scores`) warns on homogeneous
  distributions (optional stretch via `ranking.normalize_scores`).
- **Context:** Phase-1 acceptance demanded full-data jobs outrank
  snippet-guesses; the AI prompt's skills/location weights were wasted on
  snippet rows; flat 92%-everywhere scoring needed a calibration signal.
- **Consequences:** `[full]`/`[partial]`/`[snippet]` provenance tags beside
  `[age?]`/`[salary?]`; score distribution spreads by data richness.

### ADR 15: Provenance is data — stamp result-level quality/backend onto every row
- **Status:** **Implemented** (Phase 4, 2026-08-06)
- **Decision:** `main.search_jobs` stamps each row with its `ScraperResult`
  `data_quality` + `backend` via `setdefault` at ingest, so every source's
  rows carry provenance even when the source only sets it at result level
  (only Naukri/enrichment set per-row flags today).
- **Context:** Without stamping, confidence scaling and the TUI provenance
  tags were dead for most sources (rows lacked `data_quality`).
- **Consequences:** Ranker confidence, AI gating, and `[full]`/`[snippet]`
  tags work uniformly across all sources; explicit per-row flags still win
  (setdefault).

### ADR 16: AI client = provider presets + model tiers + budget guard + opt-in disk cache
- **Status:** **Implemented** (Phase 5, 2026-08-06)
- **Decision:** `ai.py` stays a single module (public surface + prompts kept
  for test-mock compatibility) implementing a **provider-agnostic
  OpenAI-compatible REST client** (`POST {base_url}/chat/completions`):
  `PROVIDERS` presets (Groq / Kilo Gateway / OpenRouter / OpenAI / local),
  selected via `ai_provider` (env `AI_PROVIDER` ▸ config.json), with model
  tiers `best` (scoring, profile extraction) vs `fast` (queries, titles)
  resolving env → config → settings → preset. A **per-run budget guard**
  (`ai.max_calls`, default 60, thread-safe) caps spend — exhausted calls
  return None once with a warning, and jobs keep heuristic scores. A **disk
  cache** (`ai_cache.py`, SQLite) is **opt-in** (`ai.cache_ttl`, default 0)
  and keyed on `task + resolved model + exact messages` so entries
  self-invalidate on provider/model/prompt changes; cache hits never consume
  budget. `matcha --configure` gained a provider wizard; the Groq seed model
  is `openai/gpt-oss-120b` (`llama-3.3-70b-versatile` EOL 2026-08-16).
- **Context:** User asked for no lock-in + free-tier friendly + works without
  AI (ADR 04); legacy `MINIMAX` env name kept as an alias; cache default 0
  keeps results predictable (no stale AI output) and existing mock-based
  suites hermetic.
- **Consequences:** Works with Groq free tier or Ollama-local with zero
  config; heuristic-only fallback when no key; TUI run summary shows
  `AI budget: N/M used (R left)`.

### ADR 17: One shared headless pipeline; agents get JSON + SKILL.md + optional MCP
- **Status:** **Implemented** (Phase 6, 2026-08-06)
- **Decision:** The full search pipeline was extracted into
  `main.run_search(...)` — profile → queries → search → normalize → central
  filters → rank → enrich — and is the single path behind the TUI AND the
  new `matcha search`/`watch`/MCP surfaces (`quiet` mode swaps rich
  Live/Progress for no-ops so headless stdout stays JSON-clean). Agents get:
  (a) `search --json` — one structured document (`build_search_payload`:
  jobs[] with `match_score` + `reasons` + provenance); (b) `watch` —
  new-vs-seen via a `seen_urls` table in the shared `jobs.db` (`track.py`,
  consumed ONLY by watch so interactive runs never pollute the newness
  signal), writing `~/.matcha/latest.json`; (c) a bilingual SKILL.md shipped
  as package data with an installer (`matcha skill --install` →
  `~/.agents/skills/matcha` + `~/.claude/skills/matcha`); (d) an optional
  MCP server (`matcha mcp`, `mcp>=1.0` optional extra, guarded import,
  read-only `matcha_status` + `matcha_search` tools, credential-scrubbed
  errors).
- **Context:** Strategy ADR 06 made the agent surface first-class; the
  acceptance criterion was "an agent drives a full search via the skill;
  watch surfaces only new jobs". Agent-Reach's `skill/SKILL.md` and
  `integrations/mcp_server.py` were used as reference patterns.
- **Consequences:** One code path = no TUI/headless drift; `watch` is
  cron-able; MCP stays optional (hint + exit 1 without the extra).

### ADR 18: Hardening = persisted circuit breakers + private-file discipline (Phase 7)
- **Status:** **Implemented** (Phase 7, 2026-08-06)
- **Decision:** (a) Per-source **circuit breakers** persist to
  `~/.matcha/source_state.json` (`ok_streak`/`fail_streak`/`last_ok`/
  `cooldown_until`): 3 consecutive search failures open a 30-min cooldown
  during which `search_jobs` skips the source with a visible note; any
  success resets. Reads are symlink-rejected + size-capped, writes atomic
  0600, every IO failure degrades to empty state, and a `threading.Lock`
  serializes the read-modify-write across the ≤12 search workers (atomic
  os.replace prevents torn cross-process reads). Doctor reports a `circuit`
  key per source. (b) **Config hardening** (`utils.py` +
  `config.py` + `errors.py`): every write is atomic + owner-only
  (0600 files / 0700 dirs), every read refuses symlinks component-wise and
  never creates files, reads are size-capped (1MB); new `ConfigSecurityError`.
  (c) **GitHub profile enrichment** (`matcha github enrich`) merges
  `gh api user/repos` language+topic skills into profile.json read-only.
  (d) **RSS source** (`sources/rss.py`, feedparser, feeds from
  `sources.rss.feeds`). (e) **mypy clean** (36→0 errors) and a **coverage
  gate ≥80%** (`fail_under=80`, CI + `make test-coverage`).
- **Context:** Phase 7 spec (§6.7/§17/§18) — a failing source should stop
  being retried every run (cooldown), config files are high-value attack
  surfaces (symlink tricks, oversized reads), and quality gates were
  documented but not enforced.
- **Consequences:** Resilient sources (skip-not-crash), attack-hardened
  private files, `matcha github` one-shot enrichment, an 8th source, and
  enforced mypy + coverage gates. The new hermetic suites also surfaced
  three real bugs fixed in this phase: `actions._db()` never committed
  (saved jobs were silently lost), `settings.load_settings` shallow-copied
  defaults (a `days: 3` overlay leaked into later calls), and
  `extract_experience` was case-sensitive.

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
