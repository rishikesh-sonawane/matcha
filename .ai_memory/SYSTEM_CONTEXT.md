# Matcha — Core System Context
<!-- This file is the definitive structural context anchor for AI engineers working on Matcha. Read this before touching code. -->

## 1. Executive Mission & Identity

**Matcha** is a personal, India-focused **job-search CLI**. It aggregates job
listings from multiple sources (LinkedIn, Indeed India, Naukri, RemoteOK, Web
Search, Career Sites, Google Jobs via SerpAPI), ranks them against a user
profile with a two-pass relevance engine (heuristic + optional AI), and
presents them in a keyboard-driven TUI.

The project is mid-transition to **Matcha 2.0** — a full rebuild around a
robust, failproof multi-backend data layer. The source of truth for the rebuild
is `revamp/matcha-2.0-strategy.md` (rev 2, all 23 sections). Today the codebase
is still Matcha 1.x (flat layout, thin data), with 2.0 planning complete and
**Phase 0 not yet started**.

Core promise: *"enter your profile once, get ranked, personalized job matches"*
— currently bottlenecked by data quality, not ranking.

## 2. Core Constraints & Environmental Anchors

- **Personal tool, local-only, single user.** No multi-tenant, no web UI, no data selling.
- **India-focused, region-configurable.** Naukri + India career sites stay; `indeed_domain` and city/region matching are configurable.
- **Enrichment-only automation.** Open the apply page; **never auto-submit applications.**
- **Human TUI and agent surface are equal front-ends.** Identical pipeline; TUI and `--json`/SKILL.md both first-class (2.0 goal).
- **Graceful degradation everywhere.** Removing AI keys, OpenCLI, Agent-Reach, or the network each still produces a working (if degraded) run with clear messaging.
- **Robustness is a feature.** No silent failure; every source/backend/job failure is isolated, logged, and reported (doctor, circuit breakers).
- **AI is optional and provider-agnostic.** No API key required to run; OpenAI-compatible REST only; MCP used solely for data plumbing (Exa) and optional agent exposure.
- **Existing scrapers stay as named fallbacks, never deleted.**
- **Environment:** macOS (darwin) dev machine; project venv at `venv/` running **Python 3.14.6**. Bash shell. Chrome installed (OpenCLI prerequisite for Phase 1).
- **No `AGENTS.md` exists** in the repo — the `.ai_memory/` directory is the sole persistent memory layer.

## 3. Strict Technical Stack Matrix

| Layer | Technology | Status |
|---|---|---|
| Language | Python 3.9+ (target), venv on 3.14.6 | Active |
| TUI | `rich` (tables/panels/progress) + `prompt_toolkit` (key bindings, full-screen) | Active |
| HTTP | `requests` + `requests-cache` (SQLite) + per-domain token-bucket rate limiter (`scrapers/utils.py`) | Active |
| Scraping | `beautifulsoup4`, `cloudscraper` (Indeed, breaks on 3.14), `ddgs` (DuckDuckGo API) | Active |
| PDF | `pdfplumber` (resume → AI extraction) | Active |
| Matching | `rapidfuzz` (dedup + query validation) | Active |
| Models | `pydantic` v2 (partially wired at runtime; 2.0 goal: used at boundaries) | Active |
| Config | JSON (`~/.matcha/config.json`) + YAML (`matcha.yaml` / `~/.matcha/settings.yaml`) | Active |
| Secrets | `keyring` (macOS Keychain) with `cryptography.fernet` fallback | Active |
| Persistence | SQLite (`~/.matcha/jobs.db` job lifecycle) | Active |
| Logging | stdlib `logging` → rotating file `~/.matcha/logs/matcha.log` only (no stderr) | Active |
| Quality | `ruff` (E,F,W,I,N,UP, line-length 100, py39), `bandit`, `pre-commit`, `mypy` (planned for 2.0) | Active |
| CI/CD | GitHub Actions 4-stage (lint → typecheck → test → docker build/push GHCR) | Active |
| Container | Docker multi-stage `python:3.11-slim`, non-root (UID 10001), docker-compose | Active |

**Upstream tooling for 2.0 (not yet integrated):**
- **Agent-Reach** (`~/Code/projects/Agent-Reach`, v1.5.0, MIT) — the **design
  parent** of Matcha 2.0 (studied 2026-08-06; verified patterns folded into
  `revamp/matcha-2.0-strategy.md` §6.8). Philosophy: installer + doctor +
  config tool, NOT a wrapper. Patterns to port: `channels/base.py` Channel
  contract (check → (status, message) ok/warn/off/error, ordered_backends
  honoring `<channel>_backend` override, active_backend set by check),
  `probe.py` (ProbeResult; broken = exit 126/127 or exec FileNotFoundError;
  retry only transient failures; UTF-8 child env), `doctor.py` (check_all
  dict shape, per-channel isolation, tier-grouped format_report),
  `config.py` + `utils/paths.py` (component-wise symlink rejection, atomic
  writes + `O_DIRECTORY` fsync, read_only mode, FEATURE_REQUIREMENTS),
  `utils/text.py` `scrub_url_credentials`, `channels/mcporter.py` read-only
  inspection (never expand `imports`), `channels/github.py` read-only probing
  (never `gh auth status`), `skill/SKILL.md` frontmatter + `skill --install`,
  `integrations/mcp_server.py` get_status tool.
- **OpenCLI** (`npm install -g @jackwener/opencli`, cloned at
  `~/Code/projects/OpenCLI`) — drives real Chrome; LinkedIn/Indeed search +
  job-detail. Probing (verified): never `opencli doctor` (auto-starts
  daemon); probe `--version` + loopback `http://127.0.0.1:19825/status`
  (header `X-OpenCLI: 1`); readiness = `extension_connected`.
- **Exa** — semantic web search via `mcporter` (MCP).
- **Jina Reader** (`https://r.jina.ai/URL`) — zero-config web reading;
  planned as the enrichment fallback backend (verified in Agent-Reach
  `channels/web.py`).

## 4. Mandatory AI Operation Rules

- **Stateless Defiance:** Read the files in `.ai_memory/` at the start of every session/message to maintain contextual alignment. Do not rely on chat memory.
- **Repo is the source of truth:** code + `.ai_memory/` beat chat history. When memory conflicts with code, **the code wins** — then fix the memory file.
- **Memory Sync Protocol:** Sync continuously, not only at session end. After every turn where files are modified or task state shifts, update `.ai_memory/system_state.md` and `.ai_memory/active_task.md`.
- **Session Journal (Crash-Safe):** Append one short timestamped line to `.ai_memory/session_log.md` after every completed step. If a session dies before the final sync, the next session reconstructs state from `git status`/`git diff` plus the journal tail.
- **Root Cause Engineering Triage:** On failure, follow: `Symptoms → Root Cause Verification → Systematic Investigation → Mitigation Strategy → Permanent Prevention Execution`. Never guess.
- **No Compromise on Security:** Zero hardcoded secrets; secrets via keyring/fernet; 0600 on sensitive files; credential masking in all output; symlink rejection.
- **Behavior-neutral refactors:** Matcha 2.0 Phase 0 must not change existing scraping/search/ranking behavior; capture test baseline before and after.

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
│   ├── matcha-2.0-strategy.md           # ★ THE plan (rev 2, 23 sections, 8 phases)
│   ├── phase-0-handoff-prompt.txt       # ready-to-use prompt for starting Phase 0
│   ├── initial-session-prompt.txt       # initial session record
│   ├── opencli-integration-plan.md      # 3-phase OpenCLI plan (superseded-but-adopted)
│   ├── blueprint.md                     # older Phase 2 blueprint (mostly implemented)
│   ├── restore_manifest.json            # 1.x state manifest
│   └── system_instructions.md           # 1.x structural breakdown
├── main.py                              # orchestrator + CLI + TUI (~630 lines, flat layout)
├── profile.py                           # profile ingestion: PDF / LinkedIn / manual
├── ai.py                                # AI client (OpenAI-compatible REST, legacy MINIMAX env)
├── matcher.py                           # heuristic scoring (35/25/15/15/10, floor=5) + AI wrapper
├── config.py                            # JSON config + keyring/fernet secrets
├── settings.py                          # YAML settings loader (Pydantic validated)
├── models.py                            # Pydantic models + ScraperResult dataclass
├── actions.py                           # SQLite job lifecycle (saved/applied/dismissed…)
├── scrapers/                            # ← 2.0 will move to src/matcha/sources/
│   ├── __init__.py (empty)   constants.py   utils.py
│   ├── linkedin.py   indeed.py   naukri.py   remoteok.py
│   └── web_search.py   serpapi_jobs.py   career_sites.py
├── tests/                               # 122 tests (unittest), 1 known failure
│   ├── test_core.py test_ai_provider.py test_comprehensive.py
│   ├── test_days_filter.py test_matcher_skill_focused.py
├── docs/superpowers/plans/              # older implementation plans (implemented)
├── kilo.md                              # older AI-agent project context (keep, may supersede)
├── pyproject.toml Makefile Dockerfile docker-compose.yml
├── .github/workflows/ci.yml             # 4-stage CI
└── venv/                                # Python 3.14.6
```

**User-data directory (`~/.matcha/`):**
`config.json` · `profile.json` · `settings.yaml` · `jobs.db` · `fernet.key` ·
`ai_cache.sqlite` (2.0) · `http_cache.sqlite` (requests-cache) ·
`source_state.json` (2.0 circuit breakers) · `latest.json` (2.0 watch) · `logs/`
