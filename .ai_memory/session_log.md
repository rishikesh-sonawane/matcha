# Session Log — Append-Only Journal

> Crash-safe trail of AI working sessions. If a session dies before the final
> memory sync (context limit, daily cap, crash, network), nothing important is
> lost — the raw trail lives here, plus in git.

## Rules

- The active assistant **appends** one short, timestamped entry after every completed step.
- **Never edit or delete old entries — only append.** This file is a write-ahead log, not a summary.
- The Memory Sync Protocol produces the compact *state summary* (`system_state.md` / `active_task.md`); this log is the raw *activity trail*.
- **Recovery:** a new session reads `git status` / `git diff`, then the tail of this log, to reconstruct anything that happened after the last sync.

## Log

### 2026-08-06 — Session 1: Full repo audit + .ai_memory rewrite (no code changes)

- **Step 1 — Repository audit.** Read the entire codebase: `main.py` (orchestrator/TUI, flat layout), `profile.py`, `ai.py` (OpenAI-compatible REST, legacy `MINIMAX` env), `matcher.py` (heuristic 35/25/15/15/10, floor=5), `config.py` (keyring+fernet), `settings.py` (YAML), `models.py` (Pydantic + ScraperResult), `actions.py` (SQLite lifecycle), all `scrapers/*` (incl. untracked `career_sites.py`), tests, CI, Docker, Makefile.
- **Step 2 — Revamp audit.** Read all of `revamp/`: strategy rev 2 (23 sections, 8 phases — the source of truth), `phase-0-handoff-prompt.txt`, `initial-session-prompt.txt`, `opencli-integration-plan.md`, `blueprint.md`, `restore_manifest.json`, `system_instructions.md`.
- **Step 3 — Baseline verification.** Ran `venv/bin/python -m unittest discover tests -v` → **122 tests, 121 pass, 1 known pre-existing failure**: `test_days_filter.py :: test_date_string_within` (`_is_older_than_days("Posted: June 6, 2026", 7)` in `scrapers/web_search.py` returns True, test expects False). Confirmed venv Python 3.14.6. Confirmed git state: `.ai_memory/`, `revamp/*`, `scrapers/career_sites.py` untracked; no `AGENTS.md`.
- **Step 4 — Rewrote all 6 `.ai_memory/` files** to reflect Matcha (previous contents were stale templates from an unrelated "ImageFlow DevOps OS" project):
  - `SYSTEM_CONTEXT.md` — Matcha mission, constraints, tech-stack matrix, AI rules, directory map.
  - `system_state.md` — real 1.x component status, test baseline, git state, Phase 0-7 roadmap with acceptance criteria, known gaps.
  - `active_task.md` — current focus: 2.0 planning done, awaiting user go-ahead for Phase 0; full Phase 0 scope checklist.
  - `architectural_decisions.md` — 10 new Matcha 2.0 ADRs + 7 implemented 1.x ADRs.
  - `README.md` — Matcha memory-bank guide (workflow, crash recovery, verify test).
  - `session_log.md` — this log (replaced empty `<date>` template stubs).
- **Next:** await user decision ("start Phase 0" vs "review doc"), then execute Phase 0 per `revamp/phase-0-handoff-prompt.txt`.

### 2026-08-06 — Session 2: Agent-Reach study + revamp doc update (no code changes)

- **Step 1 — Studied Agent-Reach v1.5.0** (`~/Code/projects/Agent-Reach`, the design parent of Matcha 2.0). Read: `channels/base.py` (Channel contract: check() → (status, message) ok/warn/off/error, ordered_backends honoring `<channel>_backend` override, active_backend set by check), `probe.py` (ProbeResult, `_BROKEN_EXIT_CODES=(126,127)`, retry-only-transient, UTF-8 child env, reinstall_hint), `doctor.py` (check_all dict shape {status,name,message,tier,backends,active_backend}, per-channel exception isolation, tier-grouped format_report, credential scrubbing), `config.py` + `utils/paths.py` (component-wise symlink rejection, atomic writes with O_DIRECTORY fsync, read_only mode, FEATURE_REQUIREMENTS), `backends/opencli.py` (never `opencli doctor` — auto-starts daemon; `--version` + loopback `/status` + extension detection), `channels/_opencli_site.py`, `linkedin.py`, `web.py` (Jina Reader), `exa_search.py`, `mcporter.py` (read-only config inspection, no editor-import expansion), `rss.py`, `github.py` (read-only env, no `gh auth status`), `integrations/mcp_server.py` (get_status tool), `skill/SKILL.md` (frontmatter + references), `cli.py`, `tests/test_channel_contracts.py`, `tests/test_doctor.py`.
- **Step 2 — Updated revamp docs:**
  - `revamp/matcha-2.0-strategy.md` → bumped to **Rev 3**; added §6.8 "Verified Agent-Reach reference (v1.5.0)" (pattern × source-file × what-Matcha-ports table); updated §6.3 (OpenCLI probe-without-side-effects), §6.4 (probe semantics), §6.5 (credential-boundary mcporter/gh reads), §6.6 (doctor `--json` result shape + warn/ok semantics), §8 (Jina Reader enrichment fallback), §16.2 (channel-contract tests), §17 (config hardening details).
  - `revamp/phase-0-handoff-prompt.txt` → updated steps 3/4/7 with the verified probe.py signature, doctor/channel contracts, result shape, and contract-test requirements.
  - `.ai_memory/SYSTEM_CONTEXT.md` → enriched "Upstream tooling for 2.0" with verified Agent-Reach/OpenCLI/Jina details.
  - `.ai_memory/active_task.md` → noted the completed Agent-Reach study and refined Phase-0 probe/doctor scope.
  - Code review pass → applied 5 minor fixes: §6.6 active_backend semantics clarified, handoff step 4 `# noqa: BLE001` note for the doctor isolation catch, `opencli-integration-plan.md` cross-reference to §6.8, §6.5 mcporter precedence wording, and §6.6 example consistency.
- **Next:** await user decision ("start Phase 0" vs "review doc"), then execute Phase 0 per `revamp/phase-0-handoff-prompt.txt`.

### 2026-08-06 — Session 3: Pre-implementation gap/blocker analysis (no code changes)

- **Step 1 — Verified live environment:** `opencli` 1.8.4 installed (`/opt/homebrew/bin/opencli`); `gh` installed; **`agent-reach` and `mcporter` NOT installed**; Chrome present; venv Python 3.14.6 (cloudscraper broken). `~/.opencli/` present.
- **Step 2 — Verified OpenCLI interfaces (v1.8.4, `~/Code/projects/OpenCLI`):** `opencli list` confirms `opencli <site> <command>` dispatch (≈130 adapters; linkedin search/job-detail, indeed search/job). `search.js` flags verified: `--limit/--start/--details/--location/--job-type/--remote/--experience-level/--date-posted` with exact value sets (date-posted: any|month|week|day/24h; experience-level: internship|entry|associate|mid-senior|director|executive). **`job-detail.js` returns NO salary field** (F-06). `-f json` flag unverified (lives in runner, not adapters) — F-07.
- **Step 3 — Read all scrapers** (linkedin/indeed/naukri/remoteok/web_search/serpapi/career_sites/utils) and recorded exact job-dict shapes for normalization design; read CI (runs ONLY tests.test_core — F-02; matrix 3.10–3.13 — F-03), Dockerfile (COPY . . / ENTRYPOINT python3 main.py), pyproject (target py39 — F-01), Makefile.
- **Step 4 — Wrote `revamp/matcha-2.0-implementation-analysis.md`** with: environment snapshot, OpenCLI verified interfaces, the 8-surface layout-migration gap + shim recommendation (F-04), per-phase (P0–P7) gap/blocker/bug analysis, findings register **F-01..F-23**, and understanding corrections.
- **Step 5 — Updated docs:** strategy → **Rev 4** (§6.3 flag sets + `-f json` caveat, §7.5 quality-gate nuance, §8 salary correction, §16.2 CI fixes, §18 Phase-0 expanded scope, §20 risk register +4 rows); phase-0 handoff → scope items 9–16 (shims, entry points, CI fixes, F-09 test fix, career_sites default-off, LinkedIn location decision, os._exit replacement); `.ai_memory` active_task/system_state/session_log.
- **Next:** user confirmed LinkedIn empty-location default = "India" (F-08); shims-first accepted. Ready to start Phase 0 per the expanded handoff prompt.

### 2026-08-06 — Session 4: Phase 0 implementation (COMPLETE)

- **Step 1 — Baseline:** 122 tests, 1 pre-existing failure (F-09 time-bomb). ruff 0.15.16 + pytest 9.1.0 present; mypy absent.
- **Step 2 — Layout migration (git mv):** `main/profile/ai/matcher/config/settings/models/actions.py` → `src/matcha/`; `scrapers/*` → `src/matcha/sources/` (career_sites via plain mv — was untracked). Rewrote all internal imports (`from models` → `from matcha.models`, `from scrapers.X` → `from matcha.sources.X`, etc.) — verified zero stale references.
- **Step 3 — New modules:** `src/matcha/{__init__,errors,utils,probe,doctor}.py` + `sources/{base,__init__}.py`. `probe.py`/`utils.py`/`doctor.py` ported from Agent-Reach v1.5.0 (English messages); fixed a transcription error in `_BARE_USERINFO_RE` (unclosed char class). Doctor result shape `{status,name,message,tier,backends,active_backend}`; isolation catch marked `# noqa: BLE001`.
- **Step 4 — Sources:** every source module gained a Source subclass (LinkedInSource/IndeedSource/NaukriSource/RemoteOKSource/WebSearchSource/SerpapiSource/CareerSitesSource) with real `check()` (HTTP probe via `probe_url` for linkedin/indeed/remoteok; DDGS-library check for ddgs-backed; key check for serpapi) and `search()` delegating to the legacy parser. `ScraperResult` gained `backend` + `data_quality` (full|partial|snippet), populated per source. **F-08:** LinkedIn blank location now defaults to `"India"`. Career Sites registered but default-off. Fixed a mis-indent in the LinkedIn card parser introduced during editing.
- **Step 5 — main.py:** `doctor [--json]` subcommand; F-05 `os._exit(0)` → `sys.exit(0)`; `import os` removed, `import json` added.
- **Step 6 — Shims:** root `main/profile/ai/matcher/config/settings/models/actions.py` + `scrapers/__init__.py` use the **sys.modules-alias pattern** (module replaced in sys.modules by its `matcha.*` twin) so `import main`, `from main import _normalize`, AND `mock.patch("main.SCRAPER_DEFS")`/`mock.patch("scrapers.indeed._fetch_indeed_page")` all hit the real module globals. Entry-point migration deferred to Phase 1 (item 16).
- **Step 7 — Config fixes:** CI `python -m unittest discover tests -v` (F-02) + matrix +3.14 (F-03); pyproject `target-version = "py310"` (F-01) + `ruff check --fix .` (69 auto-fixes: UP007 `Optional[X]`→`X|None` + isort; **verified behavior-neutral** — no utcnow/timezone rewrites); F-09 test rewritten time-relative + companion test.
- **Step 8 — New tests:** `tests/test_probe.py` (missing/ok/error/timeout/broken-shebang, scrub, utf8 env), `tests/test_doctor.py` (shape, crash isolation, scrubbing, career_sites off, format/json), `tests/test_source_contracts.py` (registry unique names, check status contract, ordered_backends permutation/override, search delegation).
- **Step 9 — Validation (all green):** **152/152 tests** (unittest + pytest); `ruff check .` clean; `ruff format --diff .` clean; **pre-commit --all-files all 7 hooks passed**; CI bandit command 0 issues; `venv/bin/python main.py --help` shows doctor; `main.py doctor` live: LinkedIn ok / Indeed warn (anti-bot) / Naukri ok / RemoteOK ok / Web Search ok / SerpAPI off / Career Sites off — 4/7 ready; `doctor --json` valid contract shape.
- **Step 10 — Review + memory:** code review passed (only nits: bandit now scans shims — **coverage gap deferred to Phase 1 per item 16**; mypy baseline documented). **mypy baseline: 24 errors, ALL pre-existing 1.x legacy debt** (DDGS `= None` fallbacks, prompt_loop/app annotations, dict reassignments) — new Phase-0 modules are clean; mypy pip-installed into venv for verification only, not a project dep/CI gate → Phase 7 cleanup. `.ai_memory/active_task.md` + `system_state.md` updated to Phase-0-done.
- **Next:** Phase 1 (Data quality) per strategy §18 — start with the entry-point migration (console script, `pip install -e .`, delete shims, update bandit/pyinstaller/Docker/README paths), then OpenCLI backends.

### 2026-08-06 — Session 5: Phase 1 part 1 — entry-point migration (DONE)

- **Step 1 — pyproject packaging:** added `[build-system]` (setuptools), `[project]` (name matcha, `requires-python >=3.10`, dynamic version via `matcha.__version__` attr, dependencies mirroring requirements.txt), `[project.scripts] matcha = "matcha.main:main"` (deviates from the plan's `matcha.cli:main` — no cli.py needed; strategy §18 + handoff updated to match), `[tool.setuptools]` src layout. Bandit `targets = ["src/matcha"]` + `skips` += B110/B311 (documented intentional: keyring/fernet availability, rate-limit jitter).
- **Step 2 — editable install:** `pip install -e .` → `matcha` console script live (`matcha --help`, `matcha doctor`, `matcha doctor --json` all verified).
- **Step 3 — tests rewritten:** all root-module imports/patch targets (`main`/`ai`/`matcher`/`models`/`scrapers.X`) → `matcha.*` / `matcha.sources.*` across 5 legacy test files (2-pass sed + blanket `"ai.`/`"main.`/`"scrapers.` fixes for multi-line mock targets; fixed a ruff-removed `import matcha.matcher`); added `../src` sys.path bootstrap to all 8 test files (kept after cleanup; removed the now-dead `..` root insert).
- **Step 4 — shims deleted:** root `main/profile/ai/matcher/config/settings/models/actions.py` (untracked Phase-0 artifacts → plain `rm`) + tracked `scrapers/__init__.py` (`git rm -f`) + `rm -rf scrapers/`. Zero stale references remain (grep-verified).
- **Step 5 — Makefile/CI/Docker/README:** `run*` targets → `$(VENV)/bin/matcha`; bandit `-c pyproject.toml -r src/matcha -lll` (config now actually applied — bandit 1.9.4 doesn't auto-discover pyproject); pyinstaller entry = console-script path (Makefile `$(VENV)/bin/matcha`, CI `$(command -v matcha)`); venv bootstrap + CI add `pip install -e .`; Dockerfile builder installs the package (`pip install --user .` from pyproject+README+src), `ENTRYPOINT ["python3", "-m", "matcha.main"]`; README quickstart/fresh-setup/architecture-diagram/file-tree updated; in-code `python3 main.py` strings → `matcha` (serpapi hint + configure completion message).
- **Step 6 — housekeeping (from review):** `.gitignore` += `*.egg-info/`, `.pytest_cache/`, `.mypy_cache/`, `build/`, `dist/`, `*.spec` (editable install had created untracked `src/matcha.egg-info/`); requirements.txt header notes pyproject is authoritative; strategy §18 + handoff + active_task updated for the `matcha.main:main` choice.
- **Step 7 — validation (all green):** **152/152 tests** (unittest + pytest); ruff check + format clean; pre-commit all 7 hooks passed; bandit (config honored) 0 issues exit 0; `matcha --help` / `matcha doctor` (live, 4/7 ready) / `matcha doctor --json` / `python3 -m matcha.main --help` all work; **pyinstaller onefile build succeeded and the 52MB binary runs `--help` and `doctor --json`** (build artifacts cleaned after). Code review passed; only nits raised and all addressed (egg-info, doc drift, dup deps, test path cleanup).
- **Next:** Phase 1 part 2 — **OpenCLI backends for LinkedIn/Indeed (+ consent flow)**, Exa web backend, Naukri job-page extraction, `agent_reach_io.py`. Before `agent_reach_io.py`, verify the exact `agent-reach doctor --json` shape + `agent-reach install --channels=opencli` flags in `~/Code/projects/Agent-Reach/agent_reach/cli.py`.

### 2026-08-06 — Session 6: Phase 1 part 2 — OpenCLI backends (DONE)

- **Step 0 — housekeeping:** committed the Phase-1 entry-point migration; untracked 19 stray `.pyc` files that had been tracked since before `.gitignore` (`chore: untrack stray .pyc files`).
- **Step 1 — interface locked (live + source):** `opencli --help` / `linkedin search --help` / `indeed search --help` confirmed flag sets and `-f json` (choices `table|plain|json|yaml|md|csv`) — **F-07 resolved**. Daemon live at `127.0.0.1:19825/status` (v1.8.4, `extensionConnected: false`). Row shapes locked from OpenCLI adapter sources: linkedin search `{rank,title,company,location,listed,salary,url}`; linkedin job-detail (no salary, F-06); indeed search `{rank,id,title,company,location,salary,tags,url}`; indeed job. Discovered **Indeed adapter is US-site** (`INDEED_ORIGIN = www.indeed.com`) — corrected strategy §6.2/§6.3.
- **Step 2 — `src/matcha/sources/backends/opencli.py`:** ported Agent-Reach probe (no `opencli doctor`, strip `OPENCLI_DAEMON_PORT`, loopback `/status` + `X-OpenCLI: 1`, `extensionConnected`=ready); `consent_granted()` (flat key + `scrapers` subsection, defaults False); `run_opencli()` tolerant runner (ANSI/noise stripping, `raw_decode`, `{rows:...}` unwrap, BROWSER_CONNECT YAML extraction).
- **Step 3 — sources:** `linkedin.py`/`indeed.py` search dispatchers (`opencli` when `_opencli_should_run` = consent+healthy, else guest-api/html; explicit `backend=` override documented as opt-in); row mapping keeps `salary`/`listed`/`apply_url`/`job_key`/`tags`; `--date-posted` (week/month/any) + `--fromage` (1/3/7/14) mappings. `check()` iterates `ordered_backends()` with consent gating; **dropped `ddgs` from LinkedIn** (never implemented in search — doctor honesty). `main.py configure_opencli()` consent flow gated on `ready`; ConfigSchema += `linkedin_consent`/`indeed_consent`.
- **Step 4 — tests:** `tests/test_opencli.py` (46): probe contract, daemon fetch, consent, JSON parsing, runner (live-caught indented-YAML message regex bug fixed + regression test), dispatch, mapping. Suite: 152 → **198 tests**.
- **Step 5 — validation (all green):** 198/198 (unittest + pytest); ruff/format clean; pre-commit all 7 hooks; bandit 0 issues; live `opencli_status()` correct; live BROWSER_CONNECT extraction clean; `matcha doctor` shows `guest-api` active (no consent); `matcha --configure` correctly gates the consent prompt when the bridge is down. Code review passed — nits all addressed (ddgs honesty, dead `_OPENCLI_INDEED_ORIGIN` const removed, explicit-backend comment, `json_output` param dropped).
- **Docs:** strategy → Rev 5 (§6.2/§6.3 corrections + F-07/F-130 resolutions); implementation-analysis §2 + risk rows updated. Memory bank synced.
- **Next:** top-N enrichment via `opencli linkedin job-detail` / `indeed job` (parallel ≤5, 30s, per-job isolation; no salary from detail), then Exa backend, Naukri job-page, `agent_reach_io.py`.

### 2026-08-06 — Session 7: Phase 1 part 3 — top-N enrichment (DONE)

- **Step 1 — backends/opencli.py:** added `linkedin_job_detail(url)` and
  `indeed_job_detail(jk)` helpers (wrappers over `run_opencli`, return the
  first row or None).
- **Step 2 — `src/matcha/sources/enrichment.py`:** `enrich_job` (in-place,
  returns bool) + `enrich_top_n` (`ThreadPoolExecutor min(max_workers,5)`,
  returns `(enriched_count, ranked)`, jobs mutated in place). LinkedIn merges
  description/apply_url/workplace_type/job_type/applicants/listed/company_url
  (**never salary — F-06**); Indeed merges description/job_type/salary/url
  (Indeed detail has salary). Per-job isolation: `enrich_error` on failure,
  worker raises swallowed. **Jina zero-config fallback** (bridge down) for
  LinkedIn only — deliberately NOT gated on OpenCLI consent (strategy §8
  "zero-config"), capped at `_JINA_MAX_JOBS = 10` for rate limits,
  `data_quality=partial` + `enrich_source=jina`.
- **Step 3 — settings/models:** `EnrichmentConfig` (enabled/top_n 30/timeout
  30/max_workers 5) + `_DEFAULTS["enrichment"]`.
- **Step 4 — main.py:** enrichment wired after `rank_jobs` (console.status +
  "Enriched N top jobs with details"); `show_job_detail` shows
  Salary/Workplace/Posted/Applicants/Apply URL; `o` opens `apply_url` when
  present.
- **Step 5 — tests:** `tests/test_enrichment.py` (17): merge contracts incl.
  F-06 no-salary assert, isolation (detail-None + raising worker), gates
  (no consent → skip opencli path; **jina runs without consent**), top-N
  selection/order, jina cap (15 jobs → 10 fetches), jina 429 failure.
  First pass had env-dependent consent tests + decorator-order bug (unmocked
  requests → real network); fixed to be hermetic. Suite: 198 → **215 tests**.
- **Step 6 — validation (all green):** 215/215 (unittest + pytest); ruff /
  format / bandit clean; live gate smoke: no-consent enrichment skips in
  0.06s, zero network. Code review passed — nits addressed (test
  hermeticity, jina cap, future.result guard, jina ungated by consent per
  §8, message wording).
- **Docs:** strategy → Rev 6 (§8 marked implemented + consent/cap notes);
  README config example + detail-view example updated. Memory bank synced.
- **Next:** Exa Web Search backend; Naukri job-page extraction;
  `agent_reach_io.py`. Phase 2 boundary: re-rank on enriched signals,
  saved-jobs enriched columns, filters module — do NOT start yet.

---

## Session 8 — Exa Web Search backend (2026-08-06)

**Goal:** Phase 1 Exa semantic search via mcporter, DDGS fallback (strategy
§6.2/§6.3, F-14).

- **Research:** mcporter CLI rewritten upstream — `wshobson/mcporter` 0.7.x
  DSL (`call 'exa.web_search_exa(query: "...", numResults: 5)'`) →
  `openclaw/mcporter` 0.8+ (`call exa.web_search_exa query="..."
  numResults=5`). Exa MCP tool is `web_search_exa` → `{results: [{title,
  url, publishedDate, author, text, score}]}`; no `job_listing` category →
  scoped via `includeDomains` (career-site ATS domains). Verified live:
  mcporter NOT installed on this machine.
- **Built:** `backends/mcporter.py` (read-only config inspection —
  `MCPORTER_CONFIG` → home → project layers; `server_names` +
  `imports_unchecked`; never starts mcporter, never expands editor imports —
  credential boundary) and `backends/exa.py` (`exa_status` off/warn/error
  semantics — configured is warn, never ok since remote unverified;
  `exa_search` with `startPublishedDate` recency; `run_mcporter_call` dual
  syntax with first-error reporting). Web Search dispatches exa-when-
  configured ▸ ddgs; check() honest.
- **Review fixes:** (1) `includeDomains` array literal may not parse in
  either mcporter syntax → retry once without it; (2) error envelopes
  (`success: false`/`error` key, no results) were reported as empty success
  → now failures with extracted messages; (3) `_extract_mcporter_error`
  only matched top-level `Error:` lines → JSON-tolerant extraction
  (`_find_error_message`); (4) first (most informative) syntax error kept;
  (5) latent earliest-`{`/`[` JSON parse bug ALSO fixed in
  `backends/opencli.py` (+ regression test).
- **Validation (all green):** 252/252 tests (unittest + pytest); ruff /
  format / bandit clean; live smoke: `exa_status()==off`,
  `exa_configured()==False`, `exa_search()==None`, web_search falls back to
  `ddgs` (11 jobs) — correct graceful degradation.
- **Docs:** strategy → Rev 7 (§6.3 dual-syntax + read-only probe verified,
  roadmap checkbox checked); analysis F-14 → RESOLVED (Exa part). Memory
  bank synced.
- **Next:** Naukri job-page extraction; `agent_reach_io.py` (verify
  `agent-reach doctor --json` shape in `~/Code/projects/Agent-Reach`
  first). Phase 2 boundary: do NOT start yet.

---

## Session 9 — `agent_reach_io.py` thin adapter (2026-08-06)

**Goal:** Phase 1 `agent_reach_io.py` — reuse `agent-reach doctor --json`
health when present, degrade to Matcha's own probes when absent (F-14),
per strategy §6.5.

- **Verified (Agent-Reach v1.5.0):** `agent-reach --version` exists
  (side-effect-free probe); `agent-reach doctor --json` emits
  `{channel: {status, name, message, tier, backends, active_backend}}` —
  same shape as Matcha's own doctor; OpenCLI channels report `backends:
  ["OpenCLI"]` and `warn` when bridge-connected; gh auth lives in
  `hosts.yml` (never `gh auth status` — writes device-id); `groq_api_key`
  lives in `~/.agent-reach/config.yaml`.
- **Built:** `agent_reach_io.py` (strategy §6.5, all six functions):
  `agent_reach_available()`; `doctor_snapshot()` (`agent-reach doctor
  --json`, TTL-cached 30s, credential-scrubbed messages, None on any
  failure); `opencli_ready()` snapshot-first (any OpenCLI channel ok/warn =
  ready) with own-probe fallback; `exa_search()` delegates to
  `backends/exa.py` (code reuse); `gh_profile()` read-only (GH_TOKEN/
  GITHUB_TOKEN env OR hosts.yml, then `gh api user` with read-only env);
  `seed_ai_config()` borrows groq_api_key → `{ai_key, ai_url, ai_model}`.
  One-time **warning**-level F-14 hint when agent-reach absent.
- **Review fixes:** gh env-token support (GH_TOKEN/GITHUB_TOKEN — reference
  parity), hint raised INFO→WARNING (visible in CLI), `_opencli_ready_from_
  snapshot` any-channel semantics, thread-safety comment on module globals,
  GROQ_MODEL documented as a seed default.
- **Validation (all green):** 283/283 tests (unittest + pytest); ruff /
  format / bandit clean. Live smoke: `agent_reach_available()==False` +
  one-time warning fired; `doctor_snapshot()==None`; `opencli_ready()==
  False` (own probe); **`gh_profile()` returned the real GitHub profile
  read-only from hosts.yml**; `seed_ai_config()==None` (no agent-reach
  config).
- **Docs:** strategy → Rev 8 (§6.5 marked IMPLEMENTED + adapter facts);
  analysis F-14 → fully RESOLVED (Exa part + agent_reach_io part). Memory
  bank synced.
- **Next:** Naukri job-page extraction (last Phase-1 item); Phase 2 boundary:
  re-rank on enriched signals, saved-jobs enriched columns, filters module
  — do NOT start yet.

---

## Session 10 — Naukri job-page extraction (2026-08-06)

**Goal:** Phase 1 last item — parse real `job-listings-*` posting pages so
Naukri yields genuine descriptions/salary/skills instead of snippet guesses
(strategy §6.2 row: `job-page ▸ ddgs`).

- **Research (live, 2026-08-06):** Naukri serves a **client-rendered Next.js
  RSC shell** — plain requests return a ~15–35KB page with empty
  `jobDetails:[]`, no JSON-LD, no meta/og tags; the internal `jobapi/v3`
  endpoints reject unauthenticated calls (404/405 without CSRF session).
  **Jina Reader (`r.jina.ai/<url>`) renders real content** (47KB markdown,
  browser-like) — the workable zero-config fetch (same pattern as
  enrichment.py). DDGS-indexed Naukri URLs are mostly **expired** (Feb–May
  2026 IDs vs Aug 2026) → they redirect to "Jobs In ... - N Job Vacancies"
  search pages — must be detected + skipped.
- **Built (`sources/naukri.py`):** backends `["job-page", "ddgs"]`;
  `search_naukri_jobs(..., backend=)` dispatch. job-page = DDGS discovery →
  parallel (≤4 workers) fetch of real postings (cap `_JOB_PAGE_MAX=8`,
  timeout 12s): direct GET with browser headers only when server-rendered
  (≥50KB or `__NEXT_DATA__`/`ld+json` markers), else Jina render. Parsers:
  `_parse_embedded` (schema.org JobPosting JSON-LD + `__NEXT_DATA__`
  recursive walk) and `_parse_rendered_text` (markdown: "About the job"
  description, `₹a-b LPA` salary, `X-Y Years` experience, Key Skills,
  posted date, Apply link, title/company/location with URL-slug fallbacks
  for company + Indian cities). `_is_search_page_render` catches expired
  redirects. Per-job isolation (`enrich_error`), provenance
  (`data_quality` full/partial, `enrich_source="job-page"`, result backend
  flips to job-page). `check()` stays hermetic (ok/library-based) so
  doctor + contract tests remain offline-safe. `limiter.set_rate("naukri.com", 6)`.
- **Review fixes:** (1) markdown `**bold**`/`## ATX` headings not matched by
  section regexes → `_plain()` strips emphasis before heading matches;
  (2) JSON-LD currency lives on `MonetaryAmount`, not the value block;
  (3) failed fetches explicitly tag `data_quality="snippet"`;
  (4) multi-word company slugs (`tata-consultancy-services`) → fold generic
  company words (services/solutions/consultancy...) up to 3 chunks;
  (5) title artifacts from odd renders (`## Job description`, numbered
  lists, "Employment Type:" lines) rejected by `_TITLE_ARTIFACTS` +
  `_is_usable_title` so the snippet title is kept.
- **Validation (all green):** 307/307 tests (unittest + pytest); ruff /
  format / bandit clean. Live smoke: `search_naukri_jobs("python
  developer", days=30)` → job-page backend, 8–9 jobs, real salaries
  (`₹7-12 Lacs`, `₹5-10 Lacs`), descriptions parsed (data_quality full),
  expired pages skipped, one failed fetch isolated as snippet. A second
  run hit DDGS junk results (no job-listings URLs) → correctly stayed on
  `ddgs`/snippet with zero fetches.
- **Docs:** strategy → Rev 9 (§6.2 Naukri row + verified-facts note,
  roadmap checkbox); analysis Naukri note → RESOLVED (Jina-render path,
  not direct curl). Memory bank synced.
- **Next:** **Phase 1 COMPLETE.** Phase 2 boundary: normalization + filters
  module (central `--days` enforcement, must-skills/location/salary/
  quality gates), re-rank on enriched signals, saved-jobs enriched columns
  — do NOT start yet.

---

## Session 11 — Phase 2: Normalize + central filters (2026-08-06)

**Goal:** Phase 2 — `normalization.py` + `filters.py` (quality → age →
must-skills → location → salary) with per-stage counts in the TUI (strategy §7).

- **Built (`src/matcha/normalization.py`):** `normalize_job` (in place,
  additive) sets `listed_epoch` (relative "X days ago", ISO-8601, month-name
  dates incl. "Posted:" prefix, RemoteOK `epoch` int, existing key),
  `salary_int` (upper-bound LPA: LPA ranges, Lacs, Crores, Indian annual
  "₹8,00,000 - ₹12,00,000", per-month ×12, "₹30-40K per month"; **bare
  numbers only count with a currency prefix** so "3-6 Years" never parses as
  salary), `city`/`region` synonym maps (Bangalore→Bengaluru, Gurgaon→
  Gurugram, Trivandrum→Thiruvananthapuram, remote/WFH→Remote; state/NCR
  region map), `remote_ok` (location/workplace/description; hybrid counts).
- **Built (`src/matcha/filters.py`):** `FilterReport` dataclass (name/kept/
  dropped/unknown/reason/tags) + the five fixed-order stages — **quality**
  (empty title, both-placeholder F-12 rule, unresolved tracking URLs, no
  URL; placeholder-company-alone tagged `partial`) → **age** (days window;
  unknown tagged `age:"unknown"` + kept, `strict_age` drops, `days=0` = today
  only) → **must-skills** (word-boundary + synonym map k8s↔kubernetes,
  aws↔amazon web services, ci/cd↔gitops; `min_must_matches`;
  `soft_must_skills` flags instead of dropping) → **location** (exact city ≥
  region fallback; remote acceptable per `remote_preference`; `remote: true`
  = remote-only; unknown location kept) → **salary** (LPA floor from profile
  or settings; unknown tagged `salary_tag:"unknown"` + kept,
  `drop_unknown_salary`). `apply_filters` returns `(kept, reports)` with
  per-stage exception isolation; `build_filter_summary` renders the counts.
- **Wiring:** `FilterConfig` pydantic + `Settings.filters` defaults + `Job`/
  `Profile` §14 fields; main.py inserts `normalize_jobs` → `apply_filters`
  between search and rank (the age filter is the FINAL freshness authority;
  scrapers keep passing the window only to fetch less), adds a `--days` CLI
  override, prints the "Filtered: N kept (…)" line in the results summary,
  and tags `[age?]`/`[salary?]` next to match scores.
- **Review fixes (self-caught via smoke + review):** stage dispatch passed 3
  args to 1-arg/2-arg filters → every stage crashed into the failure path
  (uniform `(jobs, profile, cfg)` signatures); `_MONTHLY_PAT` missed
  "a month"; K-unit math wrong (`×12/100`, not `/1000`) + ordering so
  "₹30-40K per month" wins the K path; hybrid → remote_ok; "Posted:" prefix
  stripped before ISO parse; `₹10L` shorthand unit; `days=0` today-only
  semantics (**self-review pass:** `--days 0` was silently ignored — `if
  args.days:` is falsy for 0, interactive clamped `max(1, …)`, and
  `default_days = last_days or 7` swallowed a saved 0; the age filter's
  `cutoff=now` for days=0 also dropped "today"-listed jobs whose epoch
  parses just before now → CLI now uses `is not None` + `max(0, …)`, and
  the filter uses a one-day window for days=0; regression test added).
- **Validation (all green):** 371/371 tests (unittest + pytest) — +64 new
  (`test_normalization.py` 26, `test_filters.py` 38); ruff / format / bandit
  clean. Live smoke of the full pipeline verified exact per-stage counts and
  the surviving-job set (quality −1 · age −1 · must −1 · loc −1 → 1 kept).
- **Docs:** strategy → Rev 10 (§7 marked implemented + settings YAML); README
  filters YAML example + Filters section. Memory bank synced.
- **Next:** Phase 4 boundary: ranking recalibration (confidence-weighted,
  AI verdict, `must_skills_soft` rank cap, `[full]`/`[snippet]` tags);
  saved-jobs enriched columns — do NOT start yet.

---

## Session 12 — Phase 4: Ranking recalibration (2026-08-06)

**Goal:** Phase 4 — confidence-weighted scoring on enriched data, recency /
workplace / must-skill signals, soft-mode rank cap, provenance tags (strategy §9).

- **Built (`src/matcha/matcher.py`):** `compute_relevance` keeps the base
  35/25/15/15/10 max weights but scales the text-derived skills + keyword
  dimensions by `_data_confidence` (data_quality `full` 1.0 · `partial` 0.85 ·
  `snippet` 0.7; description-length proxy only for unstamped rows) so a match
  on an empty field contributes ~0. New signals: `_recency_bonus` (+5/<3d,
  +3/<7d, +1/<14d; unknown age 0), `_workplace_bonus` (+3 when remote_ok /
  workplace agrees with `remote_preference`), `_must_skills_bonus` (+2 per
  matched must-have skill, cap +6, synonym-aware). Soft cap: `must_skills_soft`
  → ≤45. `detect_flatline` (top-decile spread < 5, needs ≥15 scores — the
  first version flagged everything on 10-score batches) + `normalize_scores`
  (monotonic stretch to [5,100]). `ai_eligible` (full/partial or ≥60-char
  description).
- **Wiring:** `main.py search_jobs` now stamps every row with its
  result-level `data_quality`/`backend` (provenance is data — only
  Naukri/enrichment set per-row flags before; without this the TUI tags and
  confidence scaling were dead for most sources). `rank_jobs` gates the AI
  pass to `ai_eligible` candidates and runs the flatline guard on FINAL
  (post-AI) scores with an optional `normalize_flatline`;
  `build_results_table` renders `[full]`/`[partial]`/`[snippet]` tags via new
  `filters.provenance_tags`. `matches_skill` made public for reuse.
  `RankingConfig(normalize_scores=False)` + `settings.ranking` defaults.
- **Review fixes:** (1) `_FULL_DESC` bar lowered 60→30 so a 47-char legacy
  description still counts as confident (test_core perfect-match asserts ≥70);
  the explicit data_quality flag carries the real enriched-vs-snippet signal
  and is now stamped at ingest; (2) flatline decile needed `max(3, len//10)`
  and a ≥15-score gate (10-score batches were always "flat"); (3) AI executor
  guarded with `if ai_idx:` (no empty progress bar); (4) flatline
  detect/normalize moved AFTER the AI pass so the presented distribution is
  judged; (5) test bug: `mock.patch.dict` ADDED to the real SCRAPER_DEFS →
  all 5 real scrapers ran (network! 48 jobs) → `clear=True` (hermetic,
  19s suite restored); (6) two merged-line syntax slips from editing fixed.
- **Validation (all green):** 401/401 tests (unittest + pytest) — +30 new
  (`tests/test_ranking.py`); ruff / format / bandit clean. Live smoke of
  `rank_jobs` verified ordering: full-data fresh job 86.2 > soft-mode 45.0
  (capped) > snippet 40.0, with correct provenance tags.
- **Docs:** strategy → Rev 11 (§9 marked implemented + weights table,
  Phase 4 ✅, §19 checklist += confidence-weighted scoring + verdict-pass
  deferred); README Ranking paragraph + heuristic table updated. Memory bank
  synced.
- **Next:** Phase 5 boundary: AI provider-agnostic REST client (presets,
  model tiers, disk cache, budget guard) + optional §9.5 verdict pass;
  saved-jobs enriched columns — do NOT start yet.

---

## Session 13 — Phase 5: Provider-agnostic AI client (2026-08-06)

**Goal:** Phase 5 — OpenAI-compatible REST client with provider presets
(Groq/Kilo/OpenRouter/local), model tiers, disk cache, budget guard
(strategy §10.2).

- **Research:** OpenRouter base `openrouter.ai/api/v1` with `:free` model IDs;
  Groq base `api.groq.com/openai/v1` — **`llama-3.3-70b-versatile` /
  `llama-3.1-8b-instant` are EOL 2026-08-16** → presets use the current
  `openai/gpt-oss-120b` (best) / `openai/gpt-oss-20b` (fast); Kilo's gateway
  base `api.kilo.ai/api/gateway` + `kilo-auto/small` confirmed OpenAI-
  compatible (in-repo kilo.md + web).
- **Built (`src/matcha/ai.py`):** `PROVIDERS` presets (incl. `local` with
  `requires_key: False`); `_get_provider()` (env `AI_PROVIDER` ▸ config
  `ai_provider`); `_normalize_chat_url()` — env/config may hold a base URL
  **or** a full `/chat/completions` endpoint, appended at call time (keeps
  legacy `_get_api_url` return values byte-identical for tests); model tiers
  `_get_model(tier)` best/fast with env → config → settings → preset
  resolution and fast→best fallback; `check_ai_available()` local-aware;
  **thread-safe budget guard** (`reset_budget`/`budget_used`/
  `budget_remaining`/`_consume_budget`, once-per-run exhaustion warning,
  cache hits never consume); 0.25s retry backoff. All 4 tasks rewire through
  `_run_with_cache`. `configure_provider()` (clears stale url/model on
  provider switch; unknown provider raises).
- **Built (`src/matcha/ai_cache.py`):** SQLite disk cache keyed
  `sha256(task + resolved model + exact messages)` — self-invalidating on
  provider/model/prompt changes and hashing the *truncated* prompt exactly;
  per-entry TTL; lazy prune every 32 puts; path `MATCHA_AI_CACHE` (tests) /
  `~/.matcha/ai_cache.sqlite`; every storage error degrades to a miss.
  **Opt-in via `settings.ai.cache_ttl` (default 0)** — keeps existing
  mock-based suites hermetic (they never enable it) and the tool predictable.
- **Wiring:** models `ConfigSchema.ai_provider` + `AIConfig`
  `model_best/model_fast/max_calls=60/cache_ttl=0`; settings defaults;
  `agent_reach_io.GROQ_MODEL` → `openai/gpt-oss-120b` (EOL-aware, test uses
  the constant so it stays green); `main.py configure_ai()` → provider
  wizard (label dict lookup, key prompted with `password=True`, optional
  url/model overrides); `run()` resets the budget per search and prints
  `AI budget: N/M used (R left)` after enrichment.
- **Review fixes:** (1) cache key originally `task+inputs` hashed the FULL
  untruncated job/profile dicts and omitted the model — switched to
  `task+model+messages` (exact + self-invalidating; added a model-in-key
  regression test); (2) fast-tier fallback order fixed so a provider's own
  fast preset wins over the best-model fallback; (3) wizard `next(...)` →
  label→provider dict lookup (no StopIteration path); (4) budget line now
  shows remaining; (5) my own test bugs: tuple-returning `_preset_env`
  helper wasn't a context manager (→ `ExitStack`) and a "ttl 1s" expiry
  assert expired before any time passed (→ time-mocked expiry test).
- **Validation (all green):** 430/430 tests (unittest + pytest) — +29 new
  (`tests/test_ai_client.py`); ruff / format / bandit clean. Live smoke:
  groq preset URL/models resolve; local provider available without a key;
  budget 2 → third call None with once-per-run warning, used/remaining 2/0;
  cache put/get/clear roundtrip; `_normalize_chat_url` appends correctly.
- **Docs:** strategy → Rev 12 (§10.2 marked IMPLEMENTED + cache-key /
  budget-guard corrections, Phase 5 ✅, §19 checklist AI item → [x]); README
  AI Integration section rewritten (preset table, env vars, tiers, budget,
  cache) + config YAML `ai:` block + project tree `ai_cache.py`. Memory
  bank synced.
- **Next:** Phase 6 boundary: `--json`, SKILL.md + installer, `matcha watch`
  + `track.py`, optional MCP server, optional §9.5 AI verdict pass — do NOT
  start yet.

---

## Session 14 — Phase 6: Agent + automation surface (2026-08-06)

**Goal:** Phase 6 — ranked `--json`, SKILL.md + installer, `matcha watch`
new-vs-seen, optional MCP server (strategy §13/§10.4).

- **Research:** read Agent-Reach's `integrations/mcp_server.py` (guarded
  `Server` + tool pattern, credential-scrubbed errors) and
  `skill/SKILL.md` (bilingual YAML-frontmatter structure). Confirmed `mcp`
  is NOT installed on this machine → the server must be a guarded optional
  extra.
- **Built (`main.py`):** `run_search()` — ONE shared headless pipeline
  (profile → AI query expansion → search_jobs → normalize → apply_filters →
  rank_jobs → enrich_top_n) used by the TUI loop AND the new subcommands;
  returns `{ranked, source_counts, source_errors, filter_summary,
  found_count, ai_used, ai_budget_used, enriched_count}`. `quiet` mode uses
  `_NullLive`/`_NullProgress` stand-ins so headless stdout stays JSON-clean
  (`search_jobs`/`rank_jobs` gained `quiet=False` kwargs — tests unaffected).
  New subcommands: `search` (`-q/-l/-d --json --output --top
  --no-ai-queries --no-enrich`), `watch` (+`--no-mark-seen`), `skill
  --install/--uninstall [--dest]`, `mcp`. `build_search_payload`/`_job_json`
  produce the JSON document; `_headless_credentials` guards (no profile / no
  query → error + exit 1). TUI `run()` now calls `run_search` — behavior and
  prints preserved (verified by the untouched TUI test surface).
- **Built (`track.py`):** `seen_urls` table in the SHARED jobs.db (reuses
  actions DB); `mark_seen` (upsert, `seen_count` bump, returns newly
  inserted), `partition_new` (new vs seen by URL), `stats`. Only `watch`
  consumes it — interactive runs never pollute the newness signal.
- **Built (`skill/`):** bilingual `SKILL.md` (en+zh, YAML frontmatter, agent
  workflow: doctor → search → summarize) bundled as package data; the
  installer lives in the `matcha.skill` PACKAGE `__init__.py` (a same-named
  `skill.py` module is shadowed by the package dir — caught by the test
  suite; installer + data merged into one namespace). `matcha skill
  --install` targets `~/.agents/skills/matcha` + `~/.claude/skills/matcha`
  (or `--dest`).
- **Built (`mcp_server.py`):** guarded FastMCP server (`mcp>=1.0` optional
  extra, `pip install -e '.[agent]'`); tools `matcha_status` (doctor JSON)
  and `matcha_search` (run_search → build_search_payload); errors
  credential-scrubbed; `matcha mcp` prints the hint + exit 1 when `mcp` is
  absent.
- **Packaging:** pyproject `[project.optional-dependencies] agent =
  ["mcp>=1.0"]` + `[tool.setuptools.package-data] matcha = ["skill/*.md"]`;
  requirements.txt header notes the extra.
- **Test bugs caught:** (1) location filter correctly dropped my "Remote"
  fixture job (profile has a concrete city + no remote preference) → fixed
  the fixture, not the filter; (2) `matcha.skill` name collision → installer
  merged into the package; (3) `mock.patch.object(FastMCP)` needs
  `create=True` when the name doesn't exist (mcp not installed).
- **Review fixes:** `--json` + `--output` together printed the "Wrote …"
  note to STDOUT **before** the JSON document — corrupting
  `matcha search --json --output x.json` and EVERY `matcha watch --json`
  (watch defaults `--output` to `~/.matcha/latest.json`) → the note now
  goes to a stderr console (`_err_console = Console(stderr=True)`);
  regression test asserts stdout stays a pure JSON stream, the file
  matches stdout, and "Wrote" never touches stdout.
- **Validation (all green):** 455/455 tests (unittest + pytest) — +25 new;
  ruff / format / bandit clean. Live smoke: `matcha search --json` (72
  found → 70 kept, full document incl. match_score/reasons/provenance),
  `matcha watch` (70 new / 0 seen, wrote latest.json), `matcha skill
  --install --dest /tmp/...` (SKILL.md with frontmatter), `matcha mcp`
  (hint + exit 1).
- **Docs:** strategy → Rev 13 (§13 IMPLEMENTED, Phase 6 ✅, §19 checklist);
  README Agent & Automation section + project tree; memory bank synced.
- **Next:** Phase 7 boundary: circuit breakers (`registry.py` + persisted
  `source_state.json`), config hardening (atomic writes, symlink
  rejection), GitHub profile enrichment, RSS source, coverage ≥80%, mypy
  debt cleanup — do NOT start yet.

---
