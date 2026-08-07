# Active Task State — Matcha

## Current Focus

**Phases 1, 2, 4, 5, 6, 7 AND the Phase 3-adjacent polish are COMPLETE.**
The pipeline is now: profile → queries → search → dedup → normalize →
central filters → **confidence-weighted rank** → enrich top N → optional
**top-K AI verdict** → present — shared via the `run_search` headless
pipeline across the TUI and the agent surface (`matcha search --json`,
`matcha watch`, MCP). Filters are centrally enforced (quality → age →
must-skills → location → salary) with per-stage counts; the quality gate
also drops junk listing-page titles ("Link to naukri.com", "It Jobs"); the
location stage prints an actionable hint when it excludes remote jobs.
Ranking is confidence-weighted (full 1.0 · partial 0.85 · snippet 0.7) with
recency/workplace/must-skill signals, a soft-mode rank cap, AI gated to
enriched candidates, provenance tags, and **Rev-15 calibration** (skill-
ratio saturation + job-title coverage) so long profiles/headlines can't
dilute real matches into a flat low band. AI is provider-agnostic (presets,
model tiers, budget guard, opt-in cache) plus the **§9.5 verdict pass**
(`settings.ai.verdict_k`, default 5) rendering a "would you apply?" line in
the detail panel + `search --json`. Saved jobs persist the enriched/
normalized fields via an idempotent SQLite migration (UPSERT preserves
status/notes). **Phase 7 (hardening) is DONE** (circuit breakers, config
hardening, GitHub enrichment, RSS, mypy clean 38/38, coverage gate 81%+).
**Session 17 (2026-08-06): AI is now LIVE on this machine** — the stored
Kilo key (`MINIMAX` env) was never wired (`ai_provider` empty ⇒
`check_ai_available()=False` ⇒ every AI feature ran heuristic-only); set
`kilo` preset + live-verified (query expansion → 4 variants, AI re-scoring
→ top jobs 85, 5 verdicts, 36/60 AI calls). **AI re-scoring moved to AFTER
enrichment** (`_ai_rescore` + shared `_apply_flatline_guard`) so the judge
scores real descriptions (§9.3 ordering). **Naukri dead postings are now
DROPPED** (`_EXPIRED` sentinel on expired→search-page redirects). Junk-
title gate extended (`top companies hiring for …`). **659/659 tests pass.**
**Session 18 (2026-08-07): docs overhaul + doctor AI status + MCP AI
surface** — README rewritten + verified against source (env vars, AI setup,
CLI command reference, config precedence, `~/.matcha` file layout) and a new
QUICKSTART.md (5 commands); **`matcha doctor` now reports AI availability in
one place** — an `ai` entry (provider / best+fast models / `key_set` /
`available`; never the key) rendered as an "AI matching" line, surfaced
identically via `doctor --json` and the MCP `matcha_status` tool.
Next: fresh spec or further polish — do NOT start a new phase without one.

> 2026-08-06 session 1: full repo audit + `.ai_memory/` rewrite.
> Session 2: Agent-Reach v1.5.0 study folded into revamp docs (strategy Rev 3).
> Session 3: pre-implementation analysis (F-01..F-23), strategy Rev 4.
> Session 4: **Phase 0 implemented** (src/ layout, shims, registry, doctor).
> Session 5: **Phase 1 part 1 — entry-point migration**.
> Session 6: **Phase 1 part 2 — OpenCLI backends** (probe/runner, consent flow).
> Session 7: **Phase 1 part 3 — enrichment** (`sources/enrichment.py`).
> Session 8: **Phase 1 — Exa Web Search backend** (mcporter read-only probe +
>   dual-syntax runner, DDGS fallback).
> Session 9: **Phase 1 — `agent_reach_io.py`** (agent-reach doctor snapshot
>   + own-probe degradation + gh_profile + seed_ai_config).
> Session 10: **Phase 1 — Naukri job-page extraction** (sources/naukri.py
>   job-page backend: DDGS discovery → real page parse).
> Session 11: **Phase 2 — Normalize + filters** (`normalization.py`,
>   `filters.py`, TUI counts + tags, `--days`).
> Session 12: **Phase 4 — Ranking recalibration** (`matcher.py`
>   confidence-weighted + signals, AI-on-enriched gate, flatline guard,
>   provenance tags, per-row provenance stamping).
> Session 13: **Phase 5 — Provider-agnostic AI client** (ai.py presets /
>   tiers / budget guard + ai_cache.py opt-in SQLite disk cache + `matcha
>   --configure` provider wizard).
> Session 14: **Phase 6 — Agent + automation** (run_search shared pipeline,
>   `search`/`watch`/`skill`/`mcp` subcommands, track.py seen_urls,
>   SKILL.md installer, guarded MCP server).
> Session 15: **Phase 7 — Hardening** (circuit breakers persisted in
>   `source_state.json`, config atomic-0600/symlink-rejection/reads-never-
>   create, GitHub profile enrichment + `matcha github`, RSS source +
>   feedparser, mypy 36→0 errors, coverage gate 64%→81% with 11 new hermetic
>   suites (623 tests), CI + Makefile gates). Real bugs fixed: actions `_db`
>   commit (saved jobs were silently lost), settings deepcopy default leak,
>   extract_experience case, probe_url hardening, breaker thread-lock,
>   fernet write TOCTOU.
> Session 16: **Phase 3-adjacent polish + results-quality fixes** (saved-jobs
> enriched columns + §9.5 verdict pass + junk-title gate + matcher dilution
> calibration + remote hint; 646/646).
> Session 17: **AI live + results-quality round 2** (user: "results are
> pathetic … use AI … Naukri jobs no longer valid") — root cause: the
> stored Kilo key was never wired (`ai_provider` empty) ⇒ AI was off;
> `configure_provider('kilo')` + live-verified (query gen, AI re-scoring,
> verdicts). AI re-scoring moved post-enrichment (`_ai_rescore`,
> `_apply_flatline_guard`); Naukri expired postings DROPPED (`_EXPIRED`
> sentinel, URLs logged); junk-title gate extended; 650/650.
> Session 18: **docs overhaul + doctor AI status + MCP AI surface**
> (README env-var/AI-setup/CLI-reference rewrite + QUICKSTART.md; doctor
> `ai` entry with provider/models/key_set/available — never the key; MCP
> `matcha_status` surfaces it; 659/659).
> Decisions locked in: shims-first (F-04); LinkedIn blank location = `"India"`
> (F-08); console entry `matcha.main:main`; consent keys
> `linkedin_consent`/`indeed_consent`; `-f json` locked (F-07); LinkedIn drops
> never-implemented `ddgs`; **Jina fallback is zero-config — NOT gated on
> OpenCLI consent** (strategy §8), capped at 10 jobs/batch; **mcporter call
> dual syntax** (openclaw 0.8+ `key=value` first, legacy 0.7 DSL retry);
> **`includeDomains` array literal may not parse in either mcporter syntax →
> retry once without it**; **Naukri job-page = Jina-render parse, NOT direct
> HTML** (SPA shell + jobapi 403/404/405 verified live); **filters run in the
> fixed order quality → age → must-skills → location → salary (strategy §7.6),
> each overridable via settings `filters:`; age filter days=0 = today only;
> bare-number salary ranges count only when currency-prefixed so "3-6 Years"
> never parses as salary**; **Phase 5: provider chosen via
> `ai_provider` (env `AI_PROVIDER` or config.json); model tiers `best`/`fast`
> resolve env → config → settings → preset; the AI cache is OPT-IN
> (`settings.ai.cache_ttl`, default 0) and keyed on task+model+messages so it
> self-invalidates on provider/prompt change; `matcha --configure` now offers
> the provider wizard; Groq seed model updated to `openai/gpt-oss-120b`
> (`llama-3.3-70b-versatile` EOL 2026-08-16)**; **Phase 6: one shared
> `run_search` pipeline drives TUI + `search`/`watch`/MCP; `watch` is the
> ONLY consumer of `seen_urls` (TUI runs never pollute newness); the MCP
> server is guarded (`mcp` optional extra, hint + exit 1 when absent);
> `matcha.skill` is a PACKAGE (bundled SKILL.md + installer) — a same-named
> module is shadowed by the package dir**.

---

## Phase 2 — Normalize + central filters (DONE 2026-08-06)

- [x] **`src/matcha/normalization.py`** (NEW, strategy §7/§14): `normalize_job`
      (in place, additive) sets `listed_epoch` (relative "X days ago", ISO-8601,
      "Jan 5, 2026", RemoteOK `epoch` int, existing key), `salary_int`
      (upper-bound LPA: "₹28-35 LPA"→35, "7-12 Lacs"→12, "₹1.2 Cr"→120,
      "₹8,00,000 - ₹12,00,000"→12, monthly "₹1,00,000 a month"→12, "₹30-40K
      per month"→5; **currency-prefix guard** so experience "3-6 Years" never
      parses as salary), `city` (synonym map: Bangalore→Bengaluru, Gurgaon→
      Gurugram, Trivandrum→Thiruvananthapuram, remote/WFH→Remote, …),
      `region` (state/NCR map for the location filter's fallback), `remote_ok`
      (location/workplace/description, hybrid counts).
- [x] **`src/matcha/filters.py`** (NEW, strategy §7): `FilterReport` dataclass
      (name/kept/dropped/unknown/reason/tags) + five stages in fixed order —
      **quality** (empty title; title+company both placeholder — F-12 keeps
      placeholder-company jobs tagged `partial`; unresolved rc/clk|pagead/clk
      without `job_key`; no URL) → **age** (days window, unknown-age tagged
      `age:"unknown"` + kept, `strict_age` drops them, `days=0` = today only)
      → **must-skills** (word-boundary match on title+description, synonym map
      k8s↔kubernetes, aws↔amazon web services, ci/cd↔gitops; `min_must_matches`;
      `soft_must_skills` flags `must_skills_soft` instead of dropping) →
      **location** (exact city ≥ region fallback, remote acceptable per
      `remote_preference`/empty profile location, `remote: true` forces
      remote-only, unknown location kept) → **salary** (profile/settings
      `min_salary` LPA floor, unknown-salary tagged `salary_tag:"unknown"`
      + kept, `drop_unknown_salary`). `apply_filters` returns `(kept, reports)`;
      per-stage exception isolation (failproof). `build_filter_summary`
      renders "age −142 · must −21 · loc −33".
- [x] **Models/settings**: `FilterConfig` pydantic + `Settings.filters`
      defaults (days 7, strict_age false, min_must_matches 1, soft_must_skills
      false, remote false, min_salary 0, drop_unknown_salary false); `Job`
      + `Profile` extended per §14 (listed_epoch/salary_int/city/region/
      remote_ok; must_have_skills/min_salary/remote_preference).
- [x] **main.py**: after `search_jobs` → `normalize_jobs` → `apply_filters`
      (with console.status "Filtering results..."); the interactive `days`
      value feeds the age filter (the central authority — scrapers only fetch
      less); new `--days N` CLI flag overrides settings; TUI prints the filter
      summary line ("Filtered: N kept (…)") and tags `[age?]`/`[salary?]` next
      to match scores; "No jobs survived the filters" flow with counts.
- [x] **Tests**: `tests/test_normalization.py` (26) + `tests/test_filters.py`
      (37): every parser variant, experience-not-salary, city/region/remote,
      each stage's drop/tag semantics, fixed order + counts, summary rendering,
      stage-failure isolation, days=0 semantics. Hermetic — pure functions.
- **Acceptance met:** 430/430 tests (unittest + pytest); ruff/format/bandit
  clean; live smoke of the full pipeline (normalize → filter) verified exact
  per-stage counts and the surviving-job set.

## Phase 4 — Ranking recalibration (DONE 2026-08-06)

- [x] **`src/matcha/matcher.py`** (strategy §9): `compute_relevance` keeps the
      35/25/15/15/10 max dimension weights but scales the text-derived
      skills+keyword dimensions by `_data_confidence` (data_quality full 1.0 /
      partial 0.85 / snippet 0.7; length proxy only for unstamped rows) so a
      match on an empty field contributes ~0 and full-data jobs outrank
      snippet-guesses. New signals: `_recency_bonus` (+5 fresh / +3 recent /
      +1 ≤2wk, unknown-age 0), `_workplace_bonus` (+3 when the job's
      remote_ok/workplace agrees with `remote_preference`), `_must_skills_bonus`
      (+2 per matched must-have skill, cap +6, synonym-aware via
      `filters.matches_skill`). Soft-mode cap: `must_skills_soft` → ≤45.
      Calibration guard: `detect_flatline` (top-decile spread < 5 on ≥15
      scores) + `normalize_scores` (linear stretch to [5,100], monotonic).
      `ai_eligible`: AI re-scoring only for full/partial or ≥60-char desc.
- [x] **`main.py`**: `search_jobs` stamps every row with its result-level
      `data_quality`/`backend` (provenance is data — only Naukri/enrichment
      set per-row flags before); `rank_jobs` gates the AI pass to
      `ai_eligible` candidates and runs the flatline guard on FINAL scores
      (warning + optional `normalize_flatline` from
      `settings.ranking.normalize_scores`); results table renders
      `[full]`/`[partial]`/`[snippet]` tags via `filters.provenance_tags`.
- [x] **filters.py**: `_matches_skill` → public `matches_skill`; new
      `provenance_tags(job)` (quality + `[age?]`/`[salary?]`, §9.6 order).
- [x] **models/settings**: `RankingConfig(normalize_scores=False)` +
      `settings.ranking` defaults.
- [x] **Tests**: `tests/test_ranking.py` (30): confidence ordering
      (full>partial>snippet, empty-desc scaling), recency/workplace/must-skills
      signals, soft cap, `ai_eligible`, flatline detect/normalize,
      `provenance_tags`, per-row provenance stamping via mocked SCRAPER_DEFS.
      Existing matcher suites unchanged (long-desc no-flag jobs stay 1.0).
- **Acceptance met:** 430/430 tests (unittest + pytest); ruff/format/bandit
  clean; live smoke of `rank_jobs` verified ordering (full 86.2 > soft-capped
  45.0 > snippet 40.0) and correct provenance tags.

## Phase 5 — Provider-agnostic AI client (DONE 2026-08-06)

- [x] **`src/matcha/ai.py`** (strategy §10.2): `PROVIDERS` presets — groq
      (gpt-oss-120b/20b), kilo (kilo-auto/small), openrouter (`:free` models),
      openai, local (no key required, `http://localhost:11434/v1`);
      `_get_provider()` (env `AI_PROVIDER` ▸ config `ai_provider`);
      `_normalize_chat_url()` (appends `/chat/completions` — env/config may
      hold either a base or full endpoint); model tiers `_get_model(tier)`:
      best = env `AI_MODEL` ▸ config `ai_model` ▸ settings `ai.model_best` ▸
      preset; fast = env `AI_MODEL_FAST` ▸ settings `ai.model_fast` ▸ preset
      fast ▸ best fallback. `check_ai_available()` skips the key check for
      local providers. **Budget guard** (thread-safe, AI scoring runs in a
      pool): `reset_budget(max_calls=None)` / `budget_used()` /
      `budget_remaining()`; `_call_ai` consumes one unit before POST, warns
      once per run when exhausted, and cache hits never consume. Retry
      backoff 0.25s between the 2 attempts.
- [x] **`src/matcha/ai_cache.py`** (NEW): SQLite disk cache, key =
      `sha256(task + model + messages)` (self-invalidating on provider/model/
      prompt change), per-entry TTL, lazy prune every 32 puts, path from env
      `MATCHA_AI_CACHE` (tests) else `~/.matcha/ai_cache.sqlite`, tolerant to
      all storage errors (degrades to miss). `_run_with_cache` in ai.py wires
      all 4 tasks; **opt-in via `settings.ai.cache_ttl` (default 0)**.
- [x] **models/settings**: `ConfigSchema.ai_provider`; `AIConfig` gains
      `model_best`/`model_fast`/`max_calls=60`/`cache_ttl=0`; `settings`
      `_DEFAULTS["ai"]` updated; `agent_reach_io.GROQ_MODEL` →
      `openai/gpt-oss-120b` (EOL-aware).
- [x] **main.py**: `configure_ai()` is now a provider-preset wizard
      (label→provider lookup, key prompted only for key-requiring providers,
      optional url/model overrides via `configure_provider()` which clears
      stale overrides on provider switch); `run()` resets the budget per
      search and prints `AI budget: N/M used (R left)` after enrichment.
- [x] **Tests**: `tests/test_ai_client.py` (29): preset resolution, tier
      overrides + fallbacks, local availability, URL normalization, budget
      exhaust/reset/unlimited-default, cache key stability + TTL + clear,
      `_run_with_cache` hit-skip + model-in-key + disabled-by-default, task
      wiring, `configure_provider` store/clear/raise. Hermetic (no network,
      `MATCHA_AI_CACHE` → tmp, existing suites keep `cache_ttl=0`).
- **Acceptance met:** 430/430 tests (unittest + pytest); ruff/format/bandit
  clean; live smoke: groq preset URL/models resolve, local avail without key,
  budget 2→`None` with once-per-run warning, cache put/get/clear roundtrip.

## Phase 6 — Agent + automation surface (DONE 2026-08-06)

- [x] **`main.run_search()`** — the shared headless pipeline (profile → AI
      query expansion → search_jobs → normalize → apply_filters → rank_jobs
      → enrich_top_n) used by the TUI loop AND the new subcommands; `quiet`
      mode (`_NullLive`/`_NullProgress` stand-ins) keeps stdout JSON-clean;
      returns `{ranked, source_counts, source_errors, filter_summary,
      found_count, ai_used, ai_budget_used, enriched_count}`.
- [x] **`matcha search`** — `-q/-l/-d`, `--json` (structured document via
      `build_search_payload`/`_job_json`: command/generated_at/query/
      location/days/ai_used/ai_budget_used/source_counts/source_errors/
      filter_summary/found_count/enriched_count/jobs[] with `match_score` +
      `reasons`), `--output FILE`, `--top`, `--no-ai-queries`,
      `--no-enrich`; shared `_headless_credentials` guard (no profile / no
      query → error + exit 1).
- [x] **`src/matcha/track.py`** — `seen_urls` table in the shared
      `~/.matcha/jobs.db` (actions DB); `mark_seen` (upsert +
      seen_count bump, returns newly inserted), `partition_new` (new vs
      seen by URL), `stats`; no-URL jobs never marked. **Only `watch`
      consumes it** — TUI runs don't pollute newness.
- [x] **`matcha watch`** — same pipeline, diffs new/seen, marks seen
      (`--no-mark-seen` opt-out), writes the full doc to `--output`
      (default `~/.matcha/latest.json`), doc adds `new_count`/
      `seen_count`/`new_jobs`/`seen_urls_total`/`marked_seen`.
- [x] **SKILL.md + installer** — `src/matcha/skill/SKILL.md` (bilingual
      zh+en, YAML frontmatter) bundled as package data (pyproject
      `package-data`), `matcha.skill` package = data + installer
      (`install_skill`/`uninstall_skill`/`default_destinations`);
      `matcha skill --install/--uninstall [--dest]`.
- [x] **MCP server** — `src/matcha/mcp_server.py`: guarded `mcp` import
      (`pip install -e '.[agent]'`), FastMCP server with read-only
      `matcha_status` (doctor JSON) + `matcha_search` (run_search →
      build_search_payload), errors credential-scrubbed; `matcha mcp`
      prints the install hint + exit 1 when `mcp` is absent.
- [x] **pyproject** — `[project.optional-dependencies] agent = ["mcp>=1.0"]`;
      `[tool.setuptools.package-data] matcha = ["skill/*.md"]`; requirements
      header notes the extra.
- [x] **Tests**: `tests/test_track.py` (6), `tests/test_skill.py` (5),
      `tests/test_agent_surface.py` (13): payload shape + serializability,
      quiet run_search with a fake scraper, enrich gating, watch
      new/seen/seen_urls_total/marked_seen (tmp DB), `--no-mark-seen`,
      headless guards (no profile / no query / defaults), cmd_search JSON
      roundtrip, MCP guard (exit 1 + hint) + tool registration.
- **Acceptance met:** 455/455 tests (unittest + pytest); ruff/format/bandit
  clean; live smoke: `search --json` (72 found → 70 kept, full doc),
  `watch` (70 new/0 seen, wrote latest.json), `skill --install` (SKILL.md
  with frontmatter), `mcp` guard hint + exit 1.

## Phase 7 — Hardening (DONE 2026-08-06)

- [x] **Circuit breakers** — `src/matcha/sources/breaker.py` (strategy §6.7):
      per-source state persisted to `~/.matcha/source_state.json`
      (`ok_streak`/`fail_streak`/`last_ok`/`cooldown_until`); 3 consecutive
      failures open a 30-min cooldown during which `search_jobs` skips the
      source with a visible note; any success resets. Reads are
      symlink-rejected + size-capped, writes atomic 0600; every IO failure
      degrades to empty state (failproof). **Thread-safe**: `_lock`
      serializes the read-modify-write across the ≤12 search workers.
      Wired into `main.search_jobs` (record per source after each run) and
      `doctor.py` (`circuit` key with fresh `open` flag).
- [x] **Config hardening** (strategy §17) — `utils.py`: `ensure_no_symlink_path`
      (trust deepest existing non-symlink ancestor, reject links below it),
      `atomic_write_text` (temp + fsync + os.replace + 0600),
      `read_small_text_no_follow` (size-capped, symlink-rejected),
      `make_private_dir` (0700). `config.py`: all writes atomic 0600, all
      reads refuse symlinks and never create files, `_MAX_CONFIG_BYTES`
      1MB cap, fernet-key write TOCTOU guarded. New `ConfigSecurityError`/
      `ConfigReadOnlyError` in `errors.py`.
- [x] **GitHub profile enrichment** (strategy §11) — `agent_reach_io.gh_repos()`
      (read-only `gh api user/repos`, telemetry-off env) +
      `profile.enrich_github_profile()` (languages + topics → skill
      suggestions, capped 8) + `matcha github enrich` subcommand (no-profile
      guard → exit 1; unavailable → hint).
- [x] **RSS source** (strategy §6.2) — `sources/rss.py` (feedparser,
      feed-list from `sources.rss.feeds`, `resilient_get` rate-limited
      fetches, per-entry job mapping, data_quality partial), registered in
      `ALL_SOURCES` (tier 0, default on), conditional `SCRAPER_DEFS` entry,
      `RSSConfig` + `Settings.sources` wiring; feedparser added to deps.
- [x] **mypy debt cleanup** — `[tool.mypy]` in pyproject + fixed **36 → 0
      errors** across 12 legacy files (typed locals for dict read-back,
      `str|None` path handling, requests payload typing, DDGS Optional
      aliasing). mypy now clean on all 38 source files.
- [x] **Coverage gate ≥80%** — baseline 64% → **81%+** via 11 new hermetic
      suites (breaker, config-hardening, rss, github-enrich, main-surface,
      profile-extra, actions, sources-utils, base, settings-extra,
      coverage-sources = career_sites/serpapi/web_search/linkedin).
      `[tool.coverage] fail_under = 80`; `make test-coverage`;
      CI coverage step.
- [x] **Real bugs fixed by the new suites**: `actions._db()` never committed
      (saved jobs were silently lost — added `conn.commit()`); `settings`
      shallow `dict(_DEFAULTS)` let `_deep_merge` mutate shared defaults
      (→ `copy.deepcopy`); `extract_experience` was case-sensitive;
      `probe_url` now catches bare exceptions so a probe never crashes
      doctor; `datetime.utcnow()` → timezone-aware (py3.14 deprecation).
- [x] **Tests**: 11 new files, **623/623 tests** (unittest + pytest);
      ruff/format/mypy/bandit clean; pre-commit green; coverage gate green.
- **Acceptance met:** `matcha doctor --json` shows 8 sources + `circuit`
  key; `source_state.json` persists streaks; `matcha github enrich`
  degrades gracefully without gh; `make test-coverage` exits 0 at 81%.

## Immediate Next Steps

1. **Session 18 landed (2026-08-07, user-driven)**: README + QUICKSTART
   updated (verified against source); `matcha doctor` reports AI
   availability (`ai` entry: provider / best+fast models / `key_set` /
   `available` — never the key; "AI matching" line in the text report); the
   MCP `matcha_status` tool surfaces the same entry. Setup is now
   verifiable in one place: `matcha doctor` → `ok` on the AI matching line.
2. **Optional follow-ups the user may want**: connect the OpenCLI browser
   bridge (Chrome + extension) for real LinkedIn/Indeed enrichment
   (`matcha --configure` → consent); set `settings ai.cache_ttl: 86400` in
   `~/.matcha/settings.yaml` so repeat searches skip AI spend.
3. **Do NOT start a new phase without a fresh spec.**
4. OpenCLI extension still disconnected on this machine; mcporter and
   agent-reach not installed (unchanged).

## Blockers / Notes

- No blockers. OpenCLI extension currently **disconnected** on this machine
  (daemon up, v1.8.4, `extensionConnected: false`) — live opencli search +
  job-detail paths untestable until Chrome has the extension enabled.
  **mcporter NOT installed** — Exa backend untestable live; `exa_status()==off`
  → Web Search stays on DDGS. **agent-reach NOT installed** — `doctor_snapshot()`
  returns None + one-time hint; health signals degrade to own probes. **gh IS
  installed + authenticated** — `gh_profile()` works live (read-only).
- **Naukri is client-rendered + anti-bot** — Jina-render path is the workable
  zero-config fetch; DDGS-indexed URLs are often expired (→ search-page
  redirect, now DROPPED via the `_EXPIRED` sentinel; fetch failures still
  keep the snippet row).
- **mypy is CLEAN** — 0 errors across all 38 source files (Phase 7). Not a
  CI gate, but the debt is gone.
- **Coverage gate** — `fail_under = 80` in `[tool.coverage.report]`, enforced
  via `make test-coverage` and a CI step; current 81%+.
- **OpenCLI extension still disconnected** on this machine (daemon up, ext
  down) — live opencli search + job-detail untestable; falls back correctly.
- Full findings register: `revamp/matcha-2.0-implementation-analysis.md`
  (F-01..F-23; F-06/F-07/F-14/F-130 updated with Phase-1 resolutions).
