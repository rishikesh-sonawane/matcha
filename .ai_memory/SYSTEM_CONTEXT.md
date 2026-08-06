# Matcha — Core System Context
<!-- This file is the definitive structural context anchor for AI engineers working on Matcha. Read this before touching code. -->

## 1. Executive Mission & Identity

**Matcha** is a personal, India-focused **job-search CLI**. It aggregates job
listings from multiple sources (LinkedIn, Indeed, Naukri, RemoteOK, Web
Search, Career Sites, Google Jobs via SerpAPI), normalizes and centrally
filters them (quality → age → must-skills → location → salary), ranks them
against a user profile with a **confidence-weighted heuristic + optional AI**
pass, enriches the top-N with full posting details, and presents them in a
keyboard-driven TUI.

The **Matcha 2.0 rebuild is largely complete**: Phases 0 (foundation),
1 (data quality), 2 (normalize + filters), 4 (ranking recalibration),
5 (provider-agnostic AI client) and 6 (agent + automation) are DONE. The
source of truth for the rebuild is
`revamp/matcha-2.0-strategy.md` (**Rev 13**). The codebase runs from the
`src/matcha/` package layout with the `matcha` console script; root shims
and `scrapers/` were deleted in Phase 1.

Core promise: *"enter your profile once, get ranked, personalized job
matches"* — the original data-quality bottleneck is now addressed by
multi-backend sources, top-N enrichment, and a central filter pipeline.

## 2. Core Constraints & Environmental Anchors

- **Personal tool, local-only, single user.** No multi-tenant, no web UI, no data selling.
- **India-focused, region-configurable.** Naukri + India career sites stay; `indeed_domain` and city/region matching are configurable.
- **Enrichment-only automation.** Open the apply page; **never auto-submit applications.**
- **Human TUI and agent surface are equal front-ends.** Identical pipeline (`run_search`) drives the TUI and the headless surface — `matcha search --json`, `matcha watch` (new-vs-seen), `skill` installer, and the optional MCP server (all Phase 6).
- **Graceful degradation everywhere.** Removing AI keys, OpenCLI, Agent-Reach, mcporter, or the network each still produces a working (if degraded) run with clear messaging (verified live for all of these).
- **Robustness is a feature.** No silent failure; every source/backend/job failure is isolated, logged, and reported (doctor; circuit breakers are Phase 7).
- **AI is optional and provider-agnostic.** No API key required to run (heuristic-only mode); OpenAI-compatible REST only — **implemented (Phase 5)**: provider presets in `ai.py` (Groq/Kilo/OpenRouter/OpenAI/local), model tiers best/fast, per-run budget guard, opt-in disk cache (`ai_cache.py`, `ai.cache_ttl`); legacy `MINIMAX` env kept as an alias. MCP used solely for data plumbing (Exa via mcporter) and optional agent exposure.
- **Existing scrapers stay as named fallbacks, never deleted.** OpenCLI/Exa are premium backends; guest-api/html/ddgs remain zero-config fallbacks.
- **Provenance is data.** Every job carries `backend` + `data_quality` (`full|partial|snippet`) + `listed_epoch` + `salary_int`; the ranker and TUI tags use them.
- **Environment:** macOS (darwin) dev machine; project venv at `venv/` running **Python 3.14.6**; `matcha` console script installed editable (`pip install -e .`). Bash shell. Chrome installed (OpenCLI bridge prerequisite). `opencli` 1.8.4 + `gh` installed; **`agent-reach` and `mcporter` NOT installed** (everything degrades correctly).
- **No `AGENTS.md` exists** in the repo — the `.ai_memory/` directory is the sole persistent memory layer.

## 3. Strict Technical Stack Matrix

| Layer | Technology | Status |
|---|---|---|
| Language | Python 3.10+ (pyproject `requires-python`), venv on 3.14.6 | Active |
| Packaging | setuptools `src/` layout; console script `matcha = matcha.main:main` | Active |
| TUI | `rich` (tables/panels/progress) + `prompt_toolkit` (key bindings, full-screen) | Active |
| HTTP | `requests` + `requests-cache` (SQLite) + per-domain token-bucket rate limiter (`sources/utils.py`) | Active |
| Scraping | `beautifulsoup4`, `ddgs` (DuckDuckGo API), Jina Reader (`r.jina.ai`, zero-config render) | Active |
| Browser bridge | OpenCLI (`opencli linkedin/indeed … -f json`) — consent-gated, probe `--version` + loopback `/status`, never `opencli doctor` | Active (Phase 1) |
| Semantic search | Exa via `mcporter` MCP (read-only config probe; dual-syntax call) — DDGS fallback when absent | Active (Phase 1) |
| PDF | `pdfplumber` (resume → AI extraction) | Active |
| Matching | `rapidfuzz` (dedup + query validation) | Active |
| Models | `pydantic` v2 (partially wired at runtime; full boundary use is Phase 7) | Active |
| Config | JSON (`~/.matcha/config.json`) + YAML (`matcha.yaml` / `~/.matcha/settings.yaml`) | Active |
| Secrets | `keyring` (macOS Keychain) with `cryptography.fernet` fallback | Active |
| Persistence | SQLite (`~/.matcha/jobs.db` job lifecycle) | Active |
| Logging | stdlib `logging` → rotating file `~/.matcha/logs/matcha.log` (file only; TUI on stdout) | Active |
| Quality | `ruff` (py310 target, line-length 100), `bandit` (pyproject targets `src/matcha`), `pre-commit` (7 hooks), `mypy` (24 pre-existing legacy errors, NOT a gate — Phase 7) | Active |
| CI/CD | GitHub Actions 4-stage (lint → typecheck → test → docker build/push GHCR), full `unittest discover` + pytest, matrix incl. 3.14 | Active |
| Container | Docker multi-stage `python:3.11-slim`, non-root (UID 10001), installs the package, `ENTRYPOINT ["python3","-m","matcha.main"]` | Active |

**Integrated upstream tooling (all Phase 1, verified 2026-08-06):**
- **OpenCLI** (`@jackwener/opencli`, v1.8.4) — drives the user's real Chrome;
  `opencli linkedin search/job-detail`, `opencli indeed search/job`, `-f json`
  locked. Probing (verified): never `opencli doctor` (auto-starts daemon);
  probe `--version` + loopback `http://127.0.0.1:19825/status` (header
  `X-OpenCLI: 1`); readiness = `extension_connected`. Consent keys
  `linkedin_consent`/`indeed_consent` via `matcha --configure`, gated on
  `opencli_status().ready`. **Bridge currently disconnected on this machine**
  → sources fall back to guest-api/html/ddgs and enrichment to Jina.
- **Agent-Reach** (`~/Code/projects/Agent-Reach`, v1.5.0, MIT) — the **design
  parent** (patterns ported in Phase 0: `probe.py`, `doctor.py`, `base.py`
  Channel contract, `utils.py` scrubbing, `errors.py`). `agent_reach_io.py`
  reuses `agent-reach doctor --json` when installed (snapshot-first health,
  TTL-cached, credential-scrubbed) and degrades to Matcha's own probes when
  absent. **Not installed here** → degradation path verified live.
- **mcporter** (MCP client, `openclaw/mcporter` 0.8+) — read-only config
  inspection (`backends/mcporter.py`; never starts mcporter, never expands
  `imports` — credential boundary) + dual-syntax `mcporter call`
  (`backends/exa.py`: current `key=value` first, legacy 0.7 DSL retry,
  `includeDomains` retry guard, error-envelope detection). **Not installed
  here** → `exa_status()==off`, Web Search stays on DDGS.
- **Jina Reader** (`https://r.jina.ai/URL`) — zero-config web rendering; the
  enrichment fallback backend (LinkedIn) AND the Naukri job-page fetcher
  (Naukri serves a client-rendered Next.js shell; the internal `jobapi`
  rejects unauthenticated calls — verified live).

## 4. Mandatory AI Operation Rules

- **Stateless Defiance:** Read the files in `.ai_memory/` at the start of every session/message to maintain contextual alignment. Do not rely on chat memory.
- **Repo is the source of truth:** code + `.ai_memory/` beat chat history. When memory conflicts with code, **the code wins** — then fix the memory file.
- **Memory Sync Protocol:** Sync continuously, not only at session end. After every turn where files are modified or task state shifts, update `.ai_memory/system_state.md` and `.ai_memory/active_task.md`.
- **Session Journal (Crash-Safe):** Append one short timestamped line to `.ai_memory/session_log.md` after every completed step. If a session dies before the final sync, the next session reconstructs state from `git status`/`git diff` plus the journal tail.
- **Root Cause Engineering Triage:** On failure, follow: `Symptoms → Root Cause Verification → Systematic Investigation → Mitigation Strategy → Permanent Prevention Execution`. Never guess.
- **No Compromise on Security:** Zero hardcoded secrets; secrets via keyring/fernet; 0600 on sensitive files; credential masking in all output; symlink rejection; read-only config probes that never widen the credential boundary.
- **Behavior-preserving refactors:** refactors must not change existing behavior; capture the test baseline before and after (455 tests today).

## 5. Directory Mapping Blueprint

```
matcha/                                  # project root (git, branch main)
├── .ai_memory/                          # persistent AI memory bank (this directory)
│   ├── README.md                        # how to use the memory bank
│   ├── SYSTEM_CONTEXT.md                # this file — structural anchor
│   ├── system_state.md                  # what has been built (checkboxes) + 2.0 roadmap
│   ├── active_task.md                   # what is being worked on right now + next steps
│   ├── session_log.md                   # append-only activity journal
│   └── architectural_decisions.md       # ADRs — why decisions were made
├── revamp/                              # Matcha 2.0 planning (source of truth)
│   ├── matcha-2.0-strategy.md           # ★ THE plan (Rev 13; Phases 0/1/2/4/5/6 marked done)
│   ├── matcha-2.0-implementation-analysis.md  # findings register F-01..F-23 (mostly resolved)
│   ├── phase-0-handoff-prompt.txt       # Phase 0 spec (implemented 2026-08-06)
│   ├── opencli-integration-plan.md      # superseded-but-adopted background
│   ├── blueprint.md                     # older 1.x-phase planning (historical)
│   └── restore_manifest.json            # 1.x state manifest
├── src/matcha/                          # ★ real package (installed editable)
│   ├── main.py                          # orchestrator + CLI + TUI + `doctor` + `--days`
│   ├── profile.py                       # profile ingestion: PDF / LinkedIn / manual
│   ├── ai.py                            # provider-agnostic AI client: presets, model tiers, budget guard (Phase 5)
│   ├── ai_cache.py                      # AI result disk cache (SQLite, opt-in TTL) (Phase 5)
│   ├── track.py                         # new-vs-seen URL tracking for `watch` (Phase 6)
│   ├── mcp_server.py                    # optional MCP server: matcha_status / matcha_search (Phase 6)
│   ├── skill/                           # bundled bilingual SKILL.md + installer (Phase 6)
│   ├── matcher.py                       # confidence-weighted ranking (Phase 4) + AI wrapper
│   ├── normalization.py                 # canonical Job: listed_epoch, salary_int, city/region, remote_ok (Phase 2)
│   ├── filters.py                       # central pipeline: quality→age→must-skills→location→salary + provenance_tags (Phases 2/4)
│   ├── agent_reach_io.py                # thin adapter to `agent-reach` (doctor snapshot, gh_profile, seed_ai_config) (Phase 1)
│   ├── config.py settings.py models.py actions.py errors.py probe.py doctor.py utils.py
│   └── sources/
│       ├── __init__.py                  # ALL_SOURCES registry
│       ├── base.py                      # Source ABC (backends, check(), search())
│       ├── constants.py  utils.py  enrichment.py
│       ├── linkedin.py   indeed.py   naukri.py   remoteok.py
│       ├── web_search.py serpapi_jobs.py  career_sites.py
│       └── backends/                    # opencli.py · mcporter.py · exa.py (Phase 1)
├── tests/                               # 455 tests (unittest + pytest)
│   ├── test_core.py test_ai_provider.py test_ai_client.py test_comprehensive.py test_probe.py
│   ├── test_doctor.py test_source_contracts.py test_days_filter.py test_matcher_skill_focused.py
│   ├── test_opencli.py test_enrichment.py test_exa_backend.py test_agent_reach_io.py
│   ├── test_track.py test_skill.py test_agent_surface.py (Phase 6)
│   ├── test_naukri_job_page.py test_normalization.py test_filters.py test_ranking.py
├── README.md  kilo.md  FuturePlan.txt  pyproject.toml  Makefile
├── Dockerfile  docker-compose.yml  .github/workflows/ci.yml
└── venv/                                # Python 3.14.6
```

**User-data directory (`~/.matcha/`):**
`config.json` · `profile.json` · `settings.yaml` · `jobs.db` · `fernet.key` ·
`http_cache.sqlite` (requests-cache) · `logs/` (matcha.log, rotating 5MB × 3)
· `ai_cache.sqlite` (AI disk cache, created when `ai.cache_ttl` is enabled)
· planned (2.0, not yet): `source_state.json` (circuit breakers),
`latest.json` (watch).
