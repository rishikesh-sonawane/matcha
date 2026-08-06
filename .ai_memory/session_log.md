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

---
