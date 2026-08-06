# Matcha 2.0 — Pre-Implementation Analysis (gap & blocker review)

> **Status:** Review complete · **Date:** 2026-08-06 · Complements
> `matcha-2.0-strategy.md` (Rev 3) — the strategy is the *what*, this is the
> *how-with-eyes-open*: verified environment facts, cross-cutting migration
> plan, per-phase gaps/blockers/bugs, and a findings register with resolutions.
> Every finding is cross-referenced by ID (F-nn). **Nothing here is implemented
> yet.**

---

## 1. Verified environment snapshot (this machine, 2026-08-06)

| Tool | Status | Impact |
|---|---|---|
| `opencli` **1.8.4** (`/opt/homebrew/bin/opencli`) | ✅ installed | Phase 1/3 OpenCLI backends usable NOW; `~/.opencli/` present (daemon state, adapters) |
| `gh` CLI | ✅ installed | Phase 1 `gh_profile()` + Phase 7 GitHub enrichment usable |
| `agent-reach` | ❌ **not installed** | `agent_reach_io.doctor_snapshot()` will return None → Matcha uses its own probes; `seed_ai_config()` (borrow Groq key) unavailable until installed |
| `mcporter` | ❌ **not installed** | Exa backend unavailable → Web Search stays on DDGS (zero-config fallback, per design) |
| Chrome | ✅ installed | OpenCLI browser bridge prerequisite satisfied (desktop) |
| venv | Python **3.14.6** | `cloudscraper` (Indeed html backend) known-broken here; OpenCLI indeed backend is the fix (Phase 1) |
| keyring | macOS Keychain | `config.py` secrets path works |

**Consequence:** Phase 1's LinkedIn/Indeed OpenCLI backends can be validated
against a **live daemon + real Chrome session** on this machine, and
`opencli_status()` (probe `--version` + loopback `/status`) can be smoke-tested
during Phase 0 even before the sources exist.

## 2. OpenCLI interface — verified (v1.8.4, `~/Code/projects/OpenCLI`)

Invocation shape `opencli <site> <command> ...` confirmed via `opencli list`
(≈130 adapters; `linkedin` has `search`/`job-detail`/…, `indeed` has
`search`/`job`).

`clis/linkedin/search.js` verified flags:

| Flag | Values (verified) |
|---|---|
| `--limit` | int (default 10) |
| `--start` | int (pagination) |
| `--details` | enrich rows inline during search (per-row failures don't abort the list) |
| `--location` | free text (e.g. "Pune") |
| `--date-posted` | `any` · `month`/`past-month` · `week`/`past-week` · `day`/`24h`/`past-24h` (help: "any, month, week, 24h") |
| `--experience-level` | `internship` · `entry`/`entry-level` · `associate` · `mid`/`senior`/`mid-senior` · `director` · `executive` |
| `--job-type` | `full-time, part-time, contract, temporary, volunteer, internship, other` |
| `--remote` | `on-site, hybrid, remote` |

`clis/linkedin/job-detail.js` verified keys: `url, title, company, company_url,
location, workplace_type, job_type, applicants, listed, apply_url, description`
— **NO `salary`** (see F-06). Search-result cards *may* include a salary column,
but do not depend on it.

**⚠️ `-f json` unverified.** The strategy examples assume `-f json`. The
adapters define `columns` for table output; the JSON/output-format flag lives in
the OpenCLI runner (`~/.opencli/node_modules/@jackwener/`), not the adapters.
**Action (Phase 1):** run `opencli linkedin search --help` once and lock the
exact output-format flag before writing the backend. Fall back to parsing the
default table output if no JSON flag exists.

## 3. Cross-cutting: the src/ layout migration (Phase 0/1 split)

The strategy §4.1 moves everything to `src/matcha/`. A **naive move**
(deleting the root modules) would break the surfaces below — but Phase 0 avoids
all of them with the **root-shim approach**, so the migration is deliberately
split across two phases:

| Surface | Naive-move failure | Phase |
|---|---|---|
| Test imports | 5 test files do `sys.path.insert(0, "..")` then `from main import …`, `from ai import …`, `from scrapers.indeed import …` | P0: shims keep green · P1: re-point to `matcha.*` |
| `make run` | `$(PYTHON) main.py` | P0: shims keep green · P1: `matcha` / `python -m matcha` |
| `make test` / CI unit tests | `unittest tests.test_core` module path | P0: shims keep green + switch CI to `discover` (F-02) |
| CI bandit / pyproject bandit | `bandit -r ai.py config.py main.py matcher.py profile.py scrapers` | P1: `bandit -r src/matcha` |
| CI pyinstaller | `pyinstaller --onefile --name matcha main.py` | P1: small entry module or installed console script (not `-m matcha`) |
| Dockerfile | `COPY . .` + `ENTRYPOINT ["python3","main.py"]` | P1: `COPY src ./src`, `ENTRYPOINT ["python3","-m","matcha"]` |
| README install/run | documents `python3 main.py` | P1: `pip install -e .` + `matcha` |

**Recommended approach (F-04) — shims first, entry-point migration in Phase 1:**
move real code to `src/matcha/`, then replace each root module (`main.py ai.py
matcher.py config.py settings.py models.py actions.py profile.py` and the
`scrapers/` package) with a **thin re-export shim** (e.g. `main.py` →
`from matcha.main import *` + explicit `_normalize`, `deduplicate`,
`search_jobs`; `scrapers/` → `from matcha.sources import *`). With shims,
`python3 main.py`, all tests, Makefile, CI, Docker and pyinstaller keep
working **unchanged** — the move breaks nothing, preserving the
behavior-neutral constraint and yielding a clean Phase-0 checkpoint.

**Phase 1 (start) then does the entry-point migration and deletes the shims:**
1. `pyproject.toml` gains `[project]` + `[project.scripts] matcha = "matcha.cli:main"`; `pip install -e .` in `Makefile venv` + CI.
2. Tests re-point to `matcha.*`; bandit/pyinstaller/Docker/README paths updated (pyinstaller builds from a small entry module or the installed console script — not `-m matcha`).
3. Delete root shims; verify `matcha doctor --json` + `matcha search --json`.

**Phase 0 green-keeping fixes that stand alone (independent of the move):**
CI full-suite + 3.14 matrix (F-02/F-03), pyproject target py310 (F-01), the
F-09 test fix, `career_sites` default-off (F-11), LinkedIn location default
(F-08), `os._exit` → `sys.exit` (F-05).

## 4. Phase-by-phase analysis

### Phase 0 — Foundation (expand scope)
**Tasks:** src/ layout (+ shims), `errors.py`, `probe.py`, `doctor.py`,
`sources/base.py` + `registry.py`, provenance fields, `matcha doctor` subcommand.

**Verified facts:** `probe_command`/`ProbeResult`/`_BROKEN_EXIT_CODES` and the
Channel contract in Agent-Reach match §6.8 exactly; `opencli --version` +
`http://127.0.0.1:19825/status` probe is live-verifiable here.

**Gaps / bugs found:**
- F-04 (High): a naive migration breaks the surfaces in §3. **Fix:** shims-first — with root shims the move breaks nothing in Phase 0; the entry-point migration (console script, `pip install -e .`, path updates) is deferred to Phase 1 with shim deletion.
- F-02 (High): CI only runs `tests.test_core` — 4 test files (incl. the failing one) never run in CI. **Fix:** `unittest discover`.
- F-09 (Medium): `test_days_filter.py::test_date_string_within` asserts `"Posted: June 6, 2026"` is within 7 days — **fails on any run date after ~June 13, 2026** (it is failing now). The function is correct; the test is a time-bomb. **Fix:** rewrite the test with dates relative to `time.time()` (e.g. `datetime.now() - timedelta(days=2)` formatted as "Posted: <Month D, YYYY>") or mock `time.time`.
- F-03 (Medium): CI matrix `3.10–3.13` misses 3.14 (dev venv = 3.14.6). **Fix:** add `"3.14"` to the matrix.
- F-01 (Medium): `pyproject.toml` `target-version = "py39"` but the code uses `str | None` (3.10+); strategy says Python 3.10+. **Fix:** `target-version = "py310"`; run `ruff check --fix .` once to normalize (and decide on `from __future__ import annotations` policy).
- F-11 (Medium): `scrapers/career_sites.py` is untracked and **not wired** (empty `scrapers/__init__.py`, absent from `SCRAPER_DEFS`). **Fix:** register it as a Source (with `check()`) but keep it **out of default dispatch** via `scrapers.career_sites: false` in settings (default off) → preserves "no behavior change"; flip on in Phase 1.
- F-17 (Low): `search_jobs` uses `as_completed(..., timeout=45)` — with the registry, keep per-source timeout semantics and make sure partial-result reporting is explicit in the TUI.
- F-08 (Medium, **resolved**): LinkedIn scraper defaults `location = "United States"` when blank. **Decision (user-confirmed 2026-08-06):** default to `"India"`. Intentional, minimal behavior change — do it in Phase 0; Phase 2 normalization still maps city/region.

**Blockers:** none hard; the shim approach is the main design decision.

**Acceptance deltas:** add "full test suite green (after F-09 fix)", "`python3 main.py doctor --json` works AND `python3 main.py --help` still works", "CI green".

### Phase 1 — Data quality
**Tasks:** OpenCLI LinkedIn/Indeed backends + consent flow; Exa backend; Naukri job-page; `agent_reach_io`.

**Verified facts:** OpenCLI installed; flags verified (§2); LinkedIn search tagged `[cookie]` in `opencli list` → browser login required → consent flow correct. `agent-reach`/`mcporter` absent → fallbacks active (F-14).

**Gaps / bugs found:**
- F-07 (Low): `-f json` unverified (see §2) — lock the flag before coding the backend; parse default output if needed.
- F-14 (Low): no agent-reach → `doctor_snapshot()` None; **make sure `agent_reach_io` degrades to Matcha's own probes and logs a one-time hint** (`npm install -g @jackwener/opencli` already satisfied; `pip install agent-reach` optional).
- F-06 (Medium): job-detail has **no salary** — do not claim salary from enrichment (see §5).
- **Consent flow design gap:** strategy says "use your logged-in Chrome for LinkedIn? (y/n)" remembered in config — needs a config key (e.g. `linkedin_consent: bool`); **opencli_status() ready-check must gate the prompt** (don't ask if the bridge is down).
- **Indeed backend caution:** `clis/indeed/` exists but its output shape is unverified — treat like F-07 (verify `opencli indeed search --help` first). Naukri job-page extraction: the real posting page must be fetched via OpenCLI `web` adapter or `curl`; verify Naukri blocks headless.
- **Timeout discipline:** OpenCLI is browser-driven → slow (seconds per call). Keep per-call timeouts (search 30s, detail 30s) and the parallel ≤5 workers.
- F-15 (Low): RemoteOK has `epoch` + `tags` but drops them from the output dict — keep `listed_epoch` and `tags` so normalization (P2) can use them.

**Acceptance deltas:** "LinkedIn ≥25 results with descriptions (consented)" — verify against the live daemon; "doctor shows active backends".

### Phase 2 — Normalize + filters
**Tasks:** `normalization.py`, `filters.py`, filter report.

**Gaps / bugs found:**
- F-13 (Medium): **no UX to set the new profile fields** (`must_have_skills`, `min_salary`, `remote_preference`). Strategy mentions `matcha filter set-must-skills` but no subcommand design. **Fix:** Phase 2 scope adds a `matcha profile edit` / `matcha filter set-*` subcommand set + `settings.yaml` `filters:` defaults (already specified) + profile wizard extension.
- F-16 (Low): Indeed concatenates `snippet | salary` into `description` — normalization must parse `salary_int` from description text too (₹/LPA patterns), and dedup must not treat the `|` fragment as boilerplate.
- F-21 (Low): `--days 0` = today only → store `listed_epoch` as UTC epoch, compare against `time.time()`; document IST behavior (epoch is timezone-free).
- **Age parsing:** central `listed_epoch` parser must handle: RemoteOK `epoch` int; OpenCLI LinkedIn `listed` ("5 days ago" etc. — job-detail regex verified); DDGS snippet "X days/months/years ago"; Naukri page date. Reuse the existing regexes from `scrapers/web_search.py` + `career_sites.py` **without the date-string bug pattern that F-09 exposed** (date-string handling must be tested with time-relative fixtures).
- F-12 (Medium): quality gate "placeholder company → drop" (Naukri yields company="Naukri") over-drops good jobs. **Fix:** drop only when **title AND company both** placeholder/empty; else keep and tag `partial`.
- **Must-have-skills matching:** needs synonym map (k8s↔kubernetes, aws↔amazon web services, ci/cd↔gitops) + word-boundary matching — reuse `matcher._word_boundary_match`; add `soft` mode ranking cap.
- **City synonyms (India):** Pune/Poona, Mumbai/Bombay, Bengaluru/Bangalore, Chennai/Madras, Kolkata/Calcutta, Hyderabad; plus "Remote/Anywhere/Distributed" → remote_ok; normalize "United States" oddity from F-08.

**Acceptance deltas:** filter counts in TUI + JSON; unknown-age tagging; `--strict-age` drops unknown-age.

### Phase 3 — Enrichment
**Tasks:** `sources/enrichment.py`, model + DB columns, TUI detail fields, apply_url-aware `o`.

**Gaps / bugs found:**
- F-06 (Medium): **job-detail has no salary** — §8's merged-key list and the Job model must stop claiming salary from enrichment. LinkedIn salary is best-effort from search cards only. **Fix strategy §8/§14** (see §5); salary filter will legitimately tag `[salary?]`.
- F-20 (Medium): enrichment only fires for `linkedin.com/jobs` URLs (verified §8 snippet). Guest-API results carry `/jobs/view/…` URLs ✓; Google Jobs/Naukri/WebSearch URLs will not enrich → Jina Reader fallback (already in §8) + `data_quality="partial"` tagging. **Add:** enrichment skip-list with a reason logged per job.
- **DB migration:** `actions.py` needs idempotent `ALTER TABLE` for new columns (apply_url, salary, salary_int, workplace_type, company_url, listed_epoch) + `seen_urls` table — guard with `PRAGMA table_info` checks; WAL mode already on.
- **`o` key:** open `apply_url` when present else `url` (strategy correct); update `_do_save` to persist enriched fields.

### Phase 4 — Ranking recalibration
**Tasks:** confidence-weighted scoring, recency/workplace signals, AI on enriched candidates, flatline detection, verdict pass, provenance tags.

**Gaps / bugs found:**
- F-10 (Medium): `deduplicate()` is O(n²) (loops all seen). Blueprint ADR-11 promised hybrid exact-first but wasn't implemented. Phase 4 (or P2 dedup.py) must do: canonical-URL pass (O(n)) then fuzzy only on collisions, keep-best by `data_quality`.
- **Confidence weighting:** a match on an empty field must contribute ~0 — implement per-dimension confidence multipliers derived from `data_quality` + field presence; reuse `matcher.compute_relevance` internals without breaking the 35/25/15/15/10 balance tests (`tests/test_matcher_skill_focused.py`).
- **Flatline detection:** compute score distribution post-pass; if top-decile spread < ε, set a `doctor --json` flag and (if configured) normalize. Cheap, isolated.
- **Verdict pass:** gated, cached (ai/cache.py), top K ≤ 5; ensure it never blocks the TUI (run after presentation or asynchronously).
- **Provenance tags in TUI:** `[full]/[snippet]/[salary?]/[age?]` — requires `data_quality` + `salary_int`/`listed_epoch` presence, which P2/P3 supply.

### Phase 5 — AI provider-agnostic
**Tasks:** `ai/client.py`, presets, model tiers, cache, budget guard, `matcha configure ai`.

**Gaps / bugs found:**
- F-19 (Low): legacy `MINIMAX` env name — Phase 5 should introduce `MATCHA_AI_API_KEY` (or similar) with `MINIMAX` as a deprecated alias; keep `check_ai_available()` semantics so heuristic-only mode is unchanged.
- **Provider quirks:** `response_format` support varies (Groq/Ollama OK; some OpenAI-compatible endpoints ignore it) — the existing `_extract_json` fallback must stay; test the presets against Groq free tier (needs a key — user action) and Ollama (optional).
- **Cache keying:** task + hash(input); SQLite TTL 24h; must be thread-safe (AI calls run in ThreadPoolExecutor) — use a per-process lock or SQLite WAL.
- **Budget guard:** `max_calls: 60` per run; when exhausted, remaining jobs keep heuristic scores + run-summary note (strategy correct).
- **`matcha configure ai` wizard:** prompts url/key/model or preset selection; store via keyring (config.py already does); do **not** store key in settings.yaml.

### Phase 6 — Agent + automation
**Tasks:** `--json`, SKILL.md + installer, `matcha watch` + new-vs-seen, optional MCP.

**Gaps / bugs found:**
- **`--json` stability:** output must be deterministic (stable key order, sorted results by score desc, then title) and include `data_quality`, `listed_epoch`, `salary_int`, `apply_url` so agents don't need the TUI. Define the schema in the strategy (add to §13) and keep `--json` + TUI on the identical pipeline.
- F-22 (Low): `seen_urls` table + `track.py` diffing; watch writes `~/.matcha/latest.json`; cron-safe (one-shot, no daemon).
- **SKILL.md:** frontmatter pattern + `references/` from Agent-Reach §6.8; installer target dirs `~/.agents/skills/matcha` + `~/.claude/skills/matcha`; `matcha skill --install/--uninstall` (mirror `agent-reach skill`).
- **MCP server:** optional; expose `matcha_search`/`matcha_status` reusing `--json` code path (Agent-Reach `get_status` pattern); graceful if `mcp` not installed.

### Phase 7 — Hardening
**Tasks:** circuit breakers, config hardening, GitHub enrichment, RSS source, coverage ≥80%, docs.

**Gaps / bugs found:**
- **Circuit breakers:** per-source state in `~/.matcha/source_state.json`; 3 strikes → cooldown 30min; doctor reports circuit state; success resets. Guard: state file writes must use the config-hardening discipline (atomic, 0600).
- **Config hardening:** port `ensure_no_symlink_path` (component-wise), atomic writes + `O_DIRECTORY` fsync, `read_only` mode, `FEATURE_REQUIREMENTS` (already in §17/§6.8).
- **RSS source:** mirror Agent-Reach `RSSChannel` (feedparser import check + force-reinstall prescription); feedparser is **not yet a dependency** — add to requirements.
- **Coverage ≥80%:** add `coverage` + gate in CI (new stage) — note the CI matrix currently has "Stage 3/4 (TBD)" placeholders.
- **README/docs:** final install/run docs for the `matcha` console script.

## 5. Findings register (summary)

| ID | Sev | Phase | Finding | Resolution |
|---|---|---|---|---|
| F-01 | Med | P0 | `pyproject` target py39 vs 3.10+ syntax | bump py310 + ruff fix |
| F-02 | High | P0 | CI runs only `tests.test_core` | `unittest discover tests` |
| F-03 | Med | P0 | CI matrix misses 3.14 | add `"3.14"` |
| F-04 | High | P0/P1 | naive src/ migration breaks 9 surfaces | shims-first (§3); entry-point migration in P1 |
| F-05 | Med | P0+ | `os._exit(0)` skips cleanup (SQLite WAL) | `sys.exit(0)` + daemon-thread handling; explicit commits |
| F-06 | Med | P1/P3 | job-detail has **no salary** | fix §8/§14; salary best-effort; tag `[salary?]` |
| F-07 | Low | P1 | `-f json` unverified; flag lists partially stale | verify `--help` at implementation; lock format flag |
| F-08 | Med | P0 | LinkedIn default location "United States" | **resolved:** default to `"India"` (user-confirmed 2026-08-06); normalize in P2 |
| F-09 | Med | P0 | `test_date_string_within` time-bomb (fails now) | time-relative fixtures |
| F-10 | Med | P2/P4 | dedup O(n²) | canonical-URL pass + fuzzy collisions, keep-best |
| F-11 | Med | P0 | career_sites untracked & unwired | register + flag off (default), enable P1 |
| F-12 | Med | P2 | placeholder-company drop over-drops | drop only if title+company both placeholder |
| F-13 | Med | P2 | no UX for must_have_skills/min_salary/remote | `matcha profile edit` / `matcha filter set-*` |
| F-14 | Low | P1 | agent-reach/mcporter absent | own probes + one-time hint; DDGS/own fallbacks |
| F-15 | Low | P1/P2 | RemoteOK epoch/tags dropped | keep `listed_epoch` + `tags` in output |
| F-16 | Low | P2 | Indeed salary embedded in description | parse salary_int from description |
| F-17 | Low | P0 | 45s batch timeout semantics | explicit partial-result reporting |
| F-18 | Low | P0 | ruff UP/N cleanup after target bump | `ruff check --fix` once |
| F-19 | Low | P5 | legacy `MINIMAX` env | new name + deprecated alias |
| F-20 | Med | P3 | enrichment URL precondition | skip-list + Jina fallback + partial tagging |
| F-21 | Low | P2 | `--days 0` / epoch semantics | UTC epoch vs `time.time()` |
| F-22 | Low | P6 | seen_urls migration | idempotent ALTER TABLE + table |
| F-23 | Low | P0 | Shims vs console-script timing | shims in P0; delete in P1 after entry-point migration |

## 6. Understanding corrections (applied to the strategy doc)

1. **§8 / §14 / Phase-3 acceptance:** LinkedIn enrichment does **not** provide salary (F-06) — merged keys updated; salary stays best-effort + `[salary?]` tag.
2. **§6.3:** `--date-posted` value set and `--experience-level` value set refined to the verified lists; `-f json` flagged for verification (F-07).
3. **§7.5:** quality gate wording adjusted — placeholder company alone no longer hard-drops (F-12).
4. **§16.2 / §18:** CI must run the full suite (F-02) and the matrix gains 3.14 (F-03); Phase 0 scope expanded with shims + the green-keeping fixes (F-04, shims-first; entry-point migration deferred to Phase 1) and the F-09 test fix.
5. **Phase 0:** `career_sites` registered but default-off (F-11); LinkedIn default-location decision called out (F-08).

## 7. Doc updates produced by this analysis

- `revamp/matcha-2.0-implementation-analysis.md` — **this document** (source of truth for gaps/blockers).
- `revamp/matcha-2.0-strategy.md` → **Rev 4**: §1 header note; §6.3 flag refinements; §7.5 quality-gate nuance; §8 salary correction; §16.2 CI fixes; §18 Phase-0 expanded scope (shims + green-keeping) with the entry-point migration deferred to Phase 1; §20 risk register +3 rows (F-06/F-07/F-20).
- `revamp/phase-0-handoff-prompt.txt` → Phase-0 scope now includes shims, CI fixes (full suite + 3.14), pyproject target py310, the F-09 test fix, career_sites default-off, LinkedIn location decision, `os._exit` replacement — and explicitly defers the entry-point migration to Phase 1 (item 16).
- `.ai_memory/` → active_task/system_state/session_log updated (session 3).

---

*Implementation can begin on Phase 0. Decisions resolved: **LinkedIn
empty-location default = `"India"`** (F-08, user-confirmed 2026-08-06); the
layout approach is settled — shims-first, with the entry-point migration
deferred to Phase 1 (F-04, §3).*
