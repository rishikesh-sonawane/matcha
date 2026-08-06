# Active Task State — Matcha

## Current Focus

**Phases 1, 2, 4 and 5 are COMPLETE.** The pipeline is now: profile → queries
→ search → dedup → normalize → central filters → **confidence-weighted rank** →
enrich top N → present. Filters are centrally enforced (quality → age →
must-skills → location → salary) with per-stage counts; ranking is
confidence-weighted (full 1.0 · partial 0.85 · snippet 0.7) with
recency/workplace/must-skill signals, a soft-mode rank cap, AI gated to
enriched candidates, a flatline guard, and `[full]`/`[partial]`/`[snippet]`
provenance tags beside `[age?]`/`[salary?]`. The AI brain is now a
**provider-agnostic OpenAI-compatible REST client** (ai.py + ai_cache.py):
provider presets (Groq/Kilo/OpenRouter/OpenAI/local-no-key), model tiers
(best/fast), per-run budget guard (`ai.max_calls`, TUI summary line), and an
opt-in disk cache (`ai.cache_ttl`, keyed on task+model+messages). **430/430
tests pass.** Next: Phase 6 (agent + automation: `--json`, SKILL.md,
`matcha watch`, MCP) — do NOT start yet.

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
> (`llama-3.3-70b-versatile` EOL 2026-08-16)**.

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

## Immediate Next Steps (Phase 6 boundary — do NOT start yet)

1. **Phase 6 — Agent + automation**: `--json` output, SKILL.md + installer,
   `matcha watch` + `track.py` (new-vs-seen SQLite), optional MCP server;
   the optional AI verdict pass (§9.5, top-K "would you apply?" line) rides
   on the now-provider-agnostic client.
2. **Phase 3-adjacent polish**: saved-jobs persist enriched+normalized fields
   (`actions.py` new columns: salary, salary_int, apply_url, listed_epoch);
   salary filter already works via `profile.min_salary` / `settings`.
3. **Do NOT build Phase 7+ features** (hardening: circuit breakers, config
   hardening, RSS, coverage gate) until the above are specced.

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
  redirect, skipped gracefully).
- **mypy baseline:** 24 errors, all pre-existing 1.x typing debt in legacy
  files; new modules (backends/, agent_reach_io, enrichment, naukri,
  normalization, filters) are clean. mypy is NOT a project dep or CI gate —
  defer to Phase 7.
- Full findings register: `revamp/matcha-2.0-implementation-analysis.md`
  (F-01..F-23; F-06/F-07/F-14/F-130 updated with Phase-1 resolutions).
