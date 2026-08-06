# Active Task State — Matcha

## Current Focus

**Phase 1 (Data quality) parts 1–3 DONE: entry-point migration, OpenCLI
backends, and top-N enrichment.** Matcha now (a) runs as an installed package,
(b) searches LinkedIn/Indeed through the user's logged-in Chrome when
consented + healthy, and (c) enriches top-N ranked jobs with full
descriptions + apply URLs. 215/215 tests pass. Remaining Phase-1 items:
**Exa Web Search backend, Naukri job-page extraction, `agent_reach_io.py`**,
per `revamp/matcha-2.0-strategy.md` §18.

> 2026-08-06 session 1: full repo audit + `.ai_memory/` rewrite.
> Session 2: Agent-Reach v1.5.0 study folded into revamp docs (strategy Rev 3).
> Session 3: pre-implementation analysis (F-01..F-23), strategy Rev 4.
> Session 4: **Phase 0 implemented** (src/ layout, shims, registry, doctor).
> Session 5: **Phase 1 part 1 — entry-point migration**.
> Session 6: **Phase 1 part 2 — OpenCLI backends** (probe/runner, consent flow).
> Session 7: **Phase 1 part 3 — enrichment** (`sources/enrichment.py`).
> Decisions locked in: shims-first (F-04); LinkedIn blank location = `"India"`
> (F-08); console entry `matcha.main:main`; consent keys
> `linkedin_consent`/`indeed_consent`; `-f json` locked (F-07); LinkedIn drops
> never-implemented `ddgs`; **Jina fallback is zero-config — NOT gated on
> OpenCLI consent** (strategy §8), capped at 10 jobs/batch.

---

## Phase 1 Part 3 — Enrichment (DONE 2026-08-06)

- [x] **`src/matcha/sources/enrichment.py`** (NEW, strategy §8): `enrich_job`
      (in-place; returns bool) + `enrich_top_n` (parallel
      `min(max_workers,5)`, returns `(enriched_count, ranked)`, jobs mutated
      in place so order preserved). Per-job isolation: failures set
      `enrich_error` and leave the job's search data untouched; worker raises
      are swallowed so a batch never aborts.
- [x] **LinkedIn**: `opencli linkedin job-detail <url>` → merges
      description/apply_url/workplace_type/job_type/applicants/listed/
      company_url; `data_quality="full"`, `enrich_source="opencli"`.
      **No salary** (F-06 compliant — merge keys exclude it; test asserts).
- [x] **Indeed**: `opencli indeed job <jk>` → merges description/job_type/
      salary/url (Indeed detail DOES include salary). Requires `job_key`.
- [x] **Gates**: OpenCLI path requires per-source `consent_granted`; **Jina
      Reader fallback (`https://r.jina.ai/<url>`) is zero-config — runs
      WITHOUT OpenCLI consent** (no browser/login involved), capped at
      `_JINA_MAX_JOBS = 10`/batch to respect rate limits; marks
      `data_quality="partial"` + `enrich_source="jina"`. Only for LinkedIn.
- [x] **Settings**: `EnrichmentConfig` (enabled/top_n=30/timeout=30/
      max_workers=5) + `_DEFAULTS["enrichment"]`; README YAML example updated.
- [x] **Wiring**: main.py `run()` calls `enrich_top_n` after `rank_jobs` with
      `console.status` + "Enriched N top jobs with details" message;
      `show_job_detail` now shows Salary/Workplace/Posted/Applicants/Apply
      URL; `o` key opens `apply_url` when present (else job URL).
- [x] **Tests**: `tests/test_enrichment.py` (17): merge contracts (incl.
      F-06), isolation (detail None + worker raise), gates (no consent →
      skip opencli path; jina runs without consent), top-N selection +
      order preservation, jina cap, jina failure isolation. Hermetic — no
      reliance on real config/bridge/network.
- **Acceptance met:** 215/215 tests (unittest + pytest); ruff/format/
  bandit clean; live gate smoke: no-consent enrichment skips in 0.06s with
  zero network.

## Immediate Next Steps (Phase 1 remainder, strategy §18)

1. **Exa Web Search backend** (`web` adapter, semantic search) + **Naukri
   job-page extraction** + `agent_reach_io.py` — remaining Phase-1 items.
2. **Optional pipeline polish (Phase 2 boundary — do NOT start yet):** step 8
   re-rank on enriched signals (AI over enriched top K); saved-jobs persist
   enriched fields (`actions.py` new columns); salary filter with `[salary?]`
   tag.
3. **Before `agent_reach_io.py`:** verify the exact `agent-reach doctor --json`
   shape + `agent-reach install --channels=opencli` flags in
   `~/Code/projects/Agent-Reach/agent_reach/cli.py`.
4. **Do NOT build Phase 2+ features** (no filters module, no AI changes)
   during Phase 1.

## Blockers / Notes

- No blockers. OpenCLI extension currently **disconnected** on this machine
  (daemon up, v1.8.4, `extensionConnected: false`) — live opencli search +
  job-detail paths are untestable until Chrome has the extension enabled;
  search falls back to guest-api/html and enrichment falls back to Jina
  (correct, graceful behavior).
- **mypy baseline:** 24 errors, all pre-existing 1.x typing debt in legacy
  files; new modules (backends/, enrichment) are clean. mypy is NOT a project
  dep or CI gate — defer to Phase 7.
- Full findings register: `revamp/matcha-2.0-implementation-analysis.md`
  (F-01..F-23; F-06/F-07/F-130 updated with Phase-1 resolutions).
