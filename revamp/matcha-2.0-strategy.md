# Matcha 2.0 — Strategy & Architecture (rev 2)

> **Status:** Planning
> **Scope:** Personal job-search tool, India-focused, human TUI + agent surface (both equal), enrichment-only (no automated apply).
> **Date:** 2026-08-06 · Rev 2 (adds: robust pipeline, job-age filter, concrete AI integration, code-quality standards, gap closure)
> Rev 3 (adds: verified Agent-Reach reference — exact probe/doctor/channel contracts, side-effect-free OpenCLI probing, credential-boundary config reads)
> Rev 4 (adds: pre-implementation gap/blocker analysis — see `matcha-2.0-implementation-analysis.md`; OpenCLI flag + salary corrections, expanded Phase-0 scope, CI fixes)

---

## 1. Executive Summary

Matcha's core promise — "enter your profile once, get ranked, personalized job
matches" — fails today because of a **data-quality bottleneck**, not a ranking
problem. The scrapers return thin, stale, noisy data (LinkedIn guest API ~10
results with no descriptions; Indeed broken on Python 3.14; Naukri yielding
search-page links, not postings). The two-pass relevance engine then scores
that thin data, producing homogeneous, uncalibrated scores. A tool that can't
reliably fetch rich job data isn't better than searching LinkedIn/Indeed by
hand — it's worse.

Rev 2 adds three commitments:

1. **Robustness is a feature.** A resilient, failproof pipeline: per-source
   and per-job isolation, real command probing, circuit breakers, retries,
   timeouts, caching, offline-friendly, and a `doctor` that never lets a
   failure be silent.
2. **Filters are first-class.** Job age (`--days`), must-have skills,
   location/remote, salary floor, and data quality are enforced centrally as
   pipeline stages — you decide exactly how fresh and how relevant.
3. **AI is optional and provider-agnostic.** The AI "brain" (profile, query
   expansion, scoring) is plain OpenAI-compatible **REST** — no API key
   required to run, free-tier friendly, no lock-in. MCP is used only where it
   belongs: **data** plumbing (Exa via mcporter) and exposing Matcha to other
   agents. Tool works perfectly without any AI.

---

## 2. Problem Diagnosis (why Matcha 1.x is worthless)

### 2.1 The data layer is the bottleneck — and it's the weakest layer

| Source | Today | Reality |
|---|---|---|
| LinkedIn | guest API (`jobs-guest/jobs/api/...`) | ~10 results/job; HTTP 999 blocks; **no description, no apply_url** |
| Indeed India | `cloudscraper` HTML → DDGS fallback | `cloudscraper` segfaults on Python 3.14; DDGS returns snippets |
| Naukri | DDGS `site:naukri.com` | returns **search-page links**, not job postings |
| RemoteOK | public JSON API | works, but keyword-filtered local subset only |
| Web Search | DDGS `site:` queries on boards | snippets; company/location *guessed* via regex |
| Career Sites | DDGS `site:<200 domains>` | same snippet-guessing problem; low yield per query |

Consequences: **descriptions mostly empty** (skill matching scores noise),
**no salary / apply URL / workplace / posting date**, **shallow India-locked
coverage**, and **no per-source health signal** (when LinkedIn blocks you or
Indeed changes HTML, results just silently shrink).

### 2.2 The ranking engine can't rescue garbage data

Skill match (35%) runs on empty text; the AI pass re-scores a noisy top-N and
mostly re-confirms heuristic mistakes; the AI prompt weights fields (skills
40%, location 15%) that often don't exist ⇒ the "92% everywhere" flatline.

### 2.3 It stops at discovery

Saves jobs, opens URLs, but never enriches the job with the data that makes a
decision possible (salary, apply URL, full description), and never filters
aggressively enough to surface *only* what's worth the user's time.

### 2.4 Fragility & observability

No distinction between "missing / broken / healthy" for external tools; no
circuit breaking; one AI provider; sparse tests; Pydantic models defined but
unused at runtime.

### 2.5 What is actually good in Matcha (keep)

Profile model + three-way entry (PDF via AI, LinkedIn URL, manual) with
no-keyword-list extraction · AI query expansion with a validation gate ·
two-pass ranking concept and a well-written critical AI scoring prompt ·
token-bucket rate limiter + requests-cache + resilient retry ·
SQLite job-lifecycle DB · keyboard-driven TUI · Pydantic models + YAML
settings (partially wired).

---

## 3. Design Principles

1. **Data first, ranking second.** Acquisition is the product; ranking is a
   filter on top of good data.
2. **Multi-backend routing, richest-first.** Ordered backend lists per source
   (e.g. LinkedIn: `opencli ▸ guest-api ▸ ddgs`); real health probes; the
   active backend is always visible. (Ported from Agent-Reach `Channel`.)
3. **Doctor-first observability.** `matcha doctor` reports per-source status,
   active backend, and fix prescription. Never `shutil.which` alone — actually
   execute (Agent-Reach `probe.py`).
4. **Filters are a pipeline stage, enforced centrally.** Age, must-have
   skills, location/remote, salary, data quality — one module, one logging
   path, one report of what was dropped and why.
5. **Enrichment over listing count.** 30 enriched jobs beat 300 snippets.
6. **Both a human tool and an agent tool.** Identical pipeline; TUI and
   `--json`/SKILL.md are equal front-ends.
7. **Graceful degradation everywhere.** Premium backends (OpenCLI, Exa, gh)
   have zero-config fallbacks (guest API, DDGS, manual). Runs fully without
   Agent-Reach and fully without AI.
8. **Failproof by construction.** A single failing source/backend/job can
   never take the run down; every failure is isolated, logged, and reported.
9. **India-focused, region-configurable.** Naukri + India career sites stay;
   `indeed_domain` and city/region matching are configurable.
10. **Provenance is data.** Every job carries `backend` + `data_quality` +
    `listed_epoch`; the UI, filters, and scoring all use them.

---

## 4. Target Architecture

```
                    ┌────────────────────────────────────────────────┐
                    │            front-ends (equal)                  │
                    │  TUI (prompt_toolkit)  |  Agent/JSON surface   │
                    └───────────────────────┬────────────────────────┘
                                            │
        ┌───────────────────────────────────▼───────────────────────────────────┐
        │            orchestrator (main.py)                                     │
        │  profile → queries → search → NORMALIZE → DEDUP → FILTER → rank      │
        │  → enrich(top N) → re-rank → present                                  │
        └───────┬──────────────────────────────────┬───────────────────────────┘
                │                                  │
   ┌────────────▼────────────┐        ┌────────────▼───────────────────┐
   │      sources/ layer     │        │  filters.py  + ranking layer    │
   │  registry + backends    │        │  age/must-skills/location/      │
   │  doctor + probe         │        │  salary/quality + heuristic+AI  │
   └──────┬─────────┬────────┘        └────────────────────────────────┘
          │         │
  ┌───────▼─────┐  ┌─▼───────────────────┐
  │ agent_reach │  │ OpenCLI bridge       │
  │ io (doctor, │  │ opencli linkedin     │
  │  exa, gh)   │  │   search/job-detail  │
  └─────────────┘  │ opencli indeed       │
                  └───────────────────────┘
```

### 4.1 Module layout

```
matcha/
├── src/matcha/
│   ├── __init__.py
│   ├── main.py                 # orchestrator + CLI (refactored from root)
│   ├── cli.py                  # argparse surface (thin; delegates to main)
│   ├── profile.py              # kept; + GitHub enrichment (optional)
│   ├── ai/
│   │   ├── __init__.py
│   │   ├── client.py           # OpenAI-compatible REST client (provider-agnostic)
│   │   ├── prompts.py          # all prompts, versioned
│   │   ├── tasks.py            # extract_profile / suggest_titles / gen_queries / score_job / verdict
│   │   └── cache.py            # AI result cache (disk, TTL)
│   ├── matcher.py              # confidence-weighted scoring on enriched data
│   ├── filters.py              # NEW — centralized filter pipeline + age filter
│   ├── normalization.py        # NEW — canonical Job normalization (epoch, salary, city)
│   ├── config.py / settings.py # hardened
│   ├── models.py               # Pydantic models used at runtime
│   ├── actions.py              # kept (+ new columns)
│   ├── doctor.py               # NEW — per-source health report
│   ├── probe.py                # NEW — real command probing (ported)
│   ├── errors.py               # NEW — typed exception hierarchy
│   ├── sources/
│   │   ├── base.py             # Source base class (Channel pattern)
│   │   ├── registry.py         # ALL_SOURCES, dispatch, circuit breakers
│   │   ├── linkedin.py         # opencli ▸ guest-api ▸ ddgs
│   │   ├── indeed.py           # opencli ▸ html ▸ ddgs
│   │   ├── naukri.py           # job-page ▸ ddgs
│   │   ├── remoteok.py         # api
│   │   ├── web_search.py       # exa ▸ ddgs
│   │   ├── career_sites.py     # ddgs ▸ exa
│   │   ├── rss.py              # NEW — company/job-board RSS
│   │   └── enrichment.py       # NEW — OpenCLI job-detail enrichment
│   ├── agent_reach_io.py       # NEW — thin adapter to `agent-reach`
│   ├── dedup.py                # NEW — canonical + fuzzy multi-key keep-best
│   ├── track.py                # NEW — seen/new diffing over SQLite
│   └── skill/                  # NEW — SKILL.md for agent-driven Matcha
├── tests/                      # unit / integration / e2e with fixtures
├── pyproject.toml              # ruff + mypy + pytest + bandit config
├── Makefile
└── revamp/matcha-2.0-strategy.md
```

---

## 5. The Search Pipeline (rev 2)

This is the canonical data flow. **Every** mode (TUI, `--json`, `watch`) goes
through it.

```
 1. query expansion            AI, validated (semantic dedup, min-token, seniority, location)
 2. source dispatch            parallel; per-source timeout; circuit breaker checked
 3. normalize                  → canonical Job (listed_epoch, salary_int, city, remote_ok, workplace)
 4. dedup                      canonical-URL pass + fuzzy (title, company); keep-best by data_quality
 5. FILTER (central)           age → must-have skills → location/remote → salary → data quality
 6. rank                       heuristic over all; AI over top N (on enriched fields)
 7. enrich top N               OpenCLI job-detail (parallel, per-job isolated)
 8. re-rank                    enriched signals + final AI verdict (optional, top K)
 9. present                    TUI / JSON / watch file
10. track                      mark seen/new in SQLite
```

Every stage logs counts: `ingest=412 normalize=412 dedup→287 filter→96
age_dropped=142 must_skill_dropped=21 …`. The user always sees *why* results
were cut.

---

## 6. Data Acquisition Layer

### 6.1 `Source` base class (ported from Agent-Reach `Channel`)

```python
class Source(ABC):
    name: str                      # "linkedin"
    description: str               # "LinkedIn 职位"
    backends: list[str]            # ordered, richest-first: ["opencli", "guest-api", "ddgs"]
    tier: int                      # 0=zero-config, 1=free key, 2=login/browser
    active_backend: str | None     # set by check()

    def can_handle(self, url) -> bool: ...
    def ordered_backends(self, config) -> list[str]:   # honors <source>_backend override
    def check(self, config) -> tuple[str, str]:        # real probe, sets active_backend
    def search(self, query, location, days, **kw) -> ScraperResult:  # dispatch to active backend
```

- `check()` must **execute** a side-effect-free probe (`probe.probe_command`)
  and set `active_backend`. `shutil.which` alone is never trusted.
- A source with a broken backend tries the next backend in order
  (`opencli` dead → `guest-api` → `ddgs`) instead of returning empty.

### 6.2 Source / backend matrix

| Source | Preferred | Fallbacks | Data richness |
|---|---|---|---|
| **LinkedIn** | `opencli` (authenticated, 25–100/job, details) | `guest-api` (~10, no desc) ▸ `ddgs` | apply_url, salary, workplace_type, full description, applicants, listed |
| **Indeed India** | `opencli` (browser, bypasses Cloudflare) | `html` (cloudscraper, py≤3.11) ▸ `ddgs` | full description, salary, apply link |
| **Naukri** | `job-page` (parse real `job-listings-*` pages) | `ddgs` (link discovery → enrich) | real description from posting page |
| **RemoteOK** | `api` | — | structured, full description |
| **Web Search** | `exa` (semantic, via mcporter) | `ddgs` | clean results, no regex-guessing |
| **Career Sites** | `ddgs` (batched) | `exa` | snippet-level (enrichable when URL is a real posting) |
| **RSS** (NEW) | `feedparser` | — | company ATS/blog feeds, continuous |

### 6.3 The OpenCLI integration (the single biggest win)

OpenCLI (`npm install -g @jackwener/opencli`, cloned at
`~/Code/projects/OpenCLI`) drives the user's real Chrome session with mature,
JSON-emitting commands:

```
opencli linkedin search "<query>" --location "Pune" --date-posted week \
  --experience-level mid-senior --job-type full-time --limit 25 -f json
opencli linkedin job-detail "<job-url>" -f json
opencli indeed search "<query>" --location "Pune" --limit 25 -f json
opencli indeed job "<job-key>" -f json
```

Verified flag sets (OpenCLI 1.8.4, 2026-08-06): `--date-posted` ∈
`any|month|week|day(24h)` · `--experience-level` ∈ `internship|entry|associate|
mid-senior|director|executive` · `--job-type` ∈ `full-time|part-time|contract|
temporary|volunteer|internship|other` · `--remote` ∈ `on-site|hybrid|remote` ·
`--limit/--start/--details` (details enriches rows inline, per-row failures
don't abort). ⚠️ `-f json` is assumed but **unverified** — lock the exact
output-format flag via `opencli linkedin search --help` before implementing
(see F-07 in the implementation-analysis doc).

`job-detail` returns `title, company, location, workplace_type, job_type,
applicants, listed, apply_url, company_url, description` — **no `salary`**
(LinkedIn DOM rarely exposes it; salary is best-effort from search cards only,
see F-06). Agent-Reach already installs/probes OpenCLI (`backends/opencli.py`,
`agent-reach install --channels=opencli`); Matcha reuses that health signal
(see §6.5).

Rules:
- Existing scrapers stay as **named fallbacks, never deleted**.
- OpenCLI is used only when **consented + healthy**. LinkedIn needs the user's
  Chrome login: one-time "use your logged-in Chrome for LinkedIn?" prompt,
  remembered in config.
- Desktop-only (OpenCLI rides a real browser session) — skip on headless
  servers (Agent-Reach already detects env; Matcha checks the same).
- **Probe without side effects (verified against Agent-Reach v1.5.0):** never
  run `opencli doctor` for health checks — it **auto-starts the daemon**. Probe
  `opencli --version` (strip stale `OPENCLI_DAEMON_PORT` from the child env),
  read live daemon state from the loopback endpoint
  `http://127.0.0.1:19825/status` (header `X-OpenCLI: 1`), and treat
  **extension-connected** (not disk files) as the readiness signal. See §6.8.

### 6.4 `probe.py` (ported from Agent-Reach)

```python
@dataclass
class ProbeResult:
    status: str      # "ok" | "missing" | "broken" | "timeout" | "error"
    output: str = ""
    hint: str = ""

def probe_command(cmd, args=("--version",), timeout=10, retries=0,
                  package=None, env=None, remove_env=()) -> ProbeResult
```

- `broken` (exit 126/127, exec `FileNotFoundError`) ⇒ stale-venv shebang;
  hint: `uv tool install --force <pkg>` / `pipx reinstall <pkg>`.
- Probes are **side-effect-free only** (version/status commands); retries
  re-run verbatim, so retry only transient failures (`timeout`/`error`), never
  `missing`/`broken`. Child runs get UTF-8 env
  (`PYTHONUTF8=1`, `PYTHONIOENCODING=utf-8`); `remove_env` strips hostile vars
  (e.g. stale `OPENCLI_DAEMON_PORT`). See §6.8.
- Used by every `Source.check()` and by `agent_reach_io`.

### 6.5 `agent_reach_io.py` (thin adapter)

```python
def agent_reach_available() -> bool           # shutil.which("agent-reach")
def doctor_snapshot() -> dict | None           # `agent-reach doctor --json`
def opencli_ready() -> bool                    # parsed from snapshot
def exa_search(query, num=5) -> list[dict]     # `mcporter call 'exa.web_search_exa(...)'`
def gh_profile() -> dict | None                # `gh api user/repos` (optional)
def seed_ai_config() -> dict | None            # borrow groq_api_key if present
```

- If Agent-Reach is installed, `check()` and enrichment read health from
  `agent-reach doctor --json`. If not, Matcha uses its own probes. Standalone
  always.
- **Credential-boundary rule (verified):** when Agent-Reach is absent, inspect
  `mcporter` config **read-only** (`MCPORTER_CONFIG` if set, else
  `~/.mcporter/mcporter.json{,c}` then `<cwd>/config/mcporter.json`) — never
  start `mcporter` just to check. Deliberately do **not** expand `imports`
  (editor configs) — that widens the credential-read boundary. `gh` probes
  pass `GH_TELEMETRY=false DO_NOT_TRACK=true GH_NO_UPDATE_NOTIFIER=1` and
  doctor never runs `gh auth status` (it writes a device-id).

### 6.6 `doctor.py` (ported from Agent-Reach)

`matcha doctor [--json]` runs every `Source.check()`, renders per-source
status + active backend + fix, never lets one source crash the report
(per-channel exception → `status="error"`), scrubs credentials. Adopted as a
**quiet pre-flight** in `main.py` so the TUI always shows which backend served
each source.

`--json` emits one record per source (shape verified from Agent-Reach
`doctor.check_all`):

```json
{"linkedin": {"status": "warn", "name": "LinkedIn 职位", "message": "...",
              "tier": 2, "backends": ["opencli", "guest-api", "ddgs"],
              "active_backend": "opencli"}}
```

Statuses: `ok` (zero-config, proven) · `warn` (installed but login/bridge not
live-verified) · `off` (not installed / declined) · `error` (crashed). For
browser-session backends (OpenCLI) doctor verifies the **bridge**, not the
platform login — so a healthy-but-not-logged-in LinkedIn reports `warn`, never
`ok`. `active_backend` reports the backend being attempted when its bridge is
healthy, even if the platform login is unverified. Per-channel errors must not
leak a stale `active_backend` (reset to `None` on exception).

### 6.7 `registry.py` — circuit breakers

Per-source state persisted to `~/.matcha/source_state.json`:

```python
{"linkedin": {"ok_streak": 12, "fail_streak": 0, "last_ok": 1690000000,
              "cooldown_until": 0}}
```

- A source that fails ≥3 consecutive searches enters a cooldown (e.g. 30 min)
  and is skipped with a visible note; success resets the streak.
- The doctor reports circuit state. Failproofing without operator effort.

### 6.8 Verified Agent-Reach reference (v1.5.0, MIT — the design parent)

Matcha 2.0's probe/doctor/channel/config layers are direct ports of
Agent-Reach (`~/Code/projects/Agent-Reach`, verified 2026-08-06). Exact
patterns and their source files:

| Pattern | Source file (Agent-Reach) | What Matcha ports |
|---|---|---|
| Channel contract | `channels/base.py` | `name/description/backends/tier/active_backend`; `check(config) -> (status, message)` with statuses `ok/warn/off/error`; `ordered_backends()` honoring `<source>_backend` override (env `<SOURCE>_BACKEND`), unknown override ignored; "`shutil.which()` alone is NOT proof of health" |
| Registry | `channels/__init__.py` | `ALL_SOURCES` list + `get_source(name)`; unique names; one file per source |
| Probing | `probe.py` | `ProbeResult(status: ok\|missing\|broken\|timeout\|error, output, hint)` with `.ok`; `probe_command(cmd, args=("--version",), timeout=10, retries=0, package, env, remove_env)`; broken = exit 126/127 or exec `FileNotFoundError` → `reinstall_hint` (`uv tool install --force <pkg>` / `pipx reinstall`); retry only transient failures; UTF-8 child env |
| Doctor | `doctor.py` | `check_all(config) -> {name: {status, name, message, tier, backends, active_backend}}`; per-channel try/except → `status="error"` + `active_backend=None`; `scrub_url_credentials()` on every message; tier-grouped `format_report()` (zero-config → optional → one-line inactive summary + ok/total) + config-permission security note |
| OpenCLI backend | `backends/opencli.py` + `channels/_opencli_site.py` | `opencli_status()`: `--version` probe (never `opencli doctor` — auto-starts daemon), loopback `http://127.0.0.1:19825/status` (`X-OpenCLI: 1`), extension-on-disk scan (Chrome/Chromium/Edge roots + `~/.opencli/extension`); `ready = installed and not broken and extension_connected`; thin `OpenCLISiteChannel` returns `off/error/warn` (never `ok` without a live bridge) |
| Config hardening | `config.py`, `utils/paths.py` | `ConfigError > ConfigReadOnlyError/ConfigSecurityError`; **component-wise symlink rejection** (`ensure_no_symlink_path` on every path part); atomic writes (mkstemp beside target, `fchmod` 0600, `fsync`, `os.replace`, dir fsync via `O_DIRECTORY`); reads never create files/dirs; `read_only` mode; `FEATURE_REQUIREMENTS` (feature → required keys); max-size caps |
| Credential scrubbing | `utils/text.py` | `scrub_url_credentials()` — 3 regexes: URL userinfo `scheme://***@`, bare userinfo, sensitive query params (`token|api_key|secret|signature|session|cookie|credential…`) |
| mcporter (read-only) | `channels/mcporter.py` | `inspect_mcporter_config()` — reads `mcpServers` names from config layers without starting mcporter; never opens `imports` (credential boundary); `McporterConfigError` on untrustworthy config |
| MCP server | `integrations/mcp_server.py` | `create_server()` exposing a `get_status` tool → doctor report JSON; graceful `HAS_MCP` guard; read-only config; errors scrubbed |
| Skill | `skill/SKILL.md` + `cli.py skill` | YAML frontmatter (`name/description/triggers/metadata`) + `references/*.md` per category; resident rules ("run doctor --json first", declare active backend, failure retry chains); `agent-reach skill --install/--uninstall` |
| gh probing | `channels/github.py` | probe `gh --version` with read-only env (`GH_TELEMETRY=false DO_NOT_TRACK=true GH_NO_UPDATE_NOTIFIER=1`); inspect `hosts.yml` for auth instead of `gh auth status` (writes device-id) |
| Contract tests | `tests/test_channel_contracts.py`, `tests/test_doctor.py` | registry non-empty/unique names; `check()` returns valid status + non-empty message; `active_backend` is `None` or `str` after `check()`; `ordered_backends()` is a permutation; doctor dict shape |

Philosophy to keep: Agent-Reach is an **installer + doctor + config tool, not a
wrapper** — after install, agents call upstream tools directly and Matcha
reuses that health signal rather than re-implementing it.

---

## 7. Filters — the first-class pipeline (rev 2)

All filters live in `filters.py` and run centrally on normalized jobs. Every
filter is: `(job, filter_spec) → (keep, reason)`. Counts are logged and shown.

### 7.1 Job-age filter (explicit requirement)

- CLI: `--days N` (default 7) or `--since 2026-07-01`; `--days 0` = today only.
- **Central enforcement**: every job carries a normalized `listed_epoch`
  (`normalization.py` parses: RemoteOK `epoch`, LinkedIn `listed`, DDGS
  "posted X ago" heuristics, Naukri page date). Job is kept iff
  `listed_epoch >= now - days`.
- **Unknown age**: kept but tagged `age:"unknown"`, ranked below known-age
  jobs, and shown as `[age?]`. `--strict-age` drops unknown-age jobs entirely.
- Report: `age_dropped=142 · age_unknown=12`.
- Backends also pass the window (LinkedIn `--date-posted week`) so we *fetch*
  fewer old jobs, but the filter is the final authority — a source lying about
  age can't leak old jobs in.

### 7.2 Must-have-skills gate

- `Profile.must_have_skills` — a strict subset of skills the user marks as
  dealbreakers (`matcha filter set-must-skills kubernetes,terraform`).
- Gate: job text (title + description) must match ≥ `min_must_matches`
  (default 1) must-have skills, word-boundary, with synonym/abbreviation map
  (`k8s↔kubernetes`, `aws↔amazon web services`, `ci/cd↔gitops`…).
- `soft` mode: below threshold jobs are kept but capped at a lower rank.
- Report: `must_skill_dropped=21`.

### 7.3 Location / remote filter

- Normalize city (`Pune`, `Poona`), region, country via a small synonym table
  (`normalization.py`).
- Profile `remote_preference: remote | hybrid | onsite`; CLI `--remote`.
- Semantics: exact city ≥ region ≥ remote-friendly; `remote` jobs always kept
  if remote is acceptable; otherwise dropped with reason.
- Report: `location_dropped=33`.

### 7.4 Salary floor

- Profile `min_salary` (LPA int). If a job has a parseable salary
  (`salary_int` normalized from "₹28-35 LPA", "28-35 LPA") and it's below the
  floor → dropped. Unknown-salary jobs are kept but tagged `[salary?]`.
- Report: `salary_dropped=7 · salary_unknown=19`.

### 7.5 Data-quality gate

- Drop: empty title · **title AND company both** placeholder (`Unknown`,
  `Naukri`) · unresolved tracking URLs (`rc/clk`, `pagead/clk` with no `jk`) ·
  obviously truncated snippets with no URL. (Placeholder company **alone** is
  kept but tagged `partial` — Naukri yields `company="Naukri"` for otherwise
  good jobs, see F-12.)
- Report: `quality_dropped=9`.

### 7.6 Ordering & configuration

Filters run in a fixed order (quality → age → must-skills → location →
salary), each enabled by default with sensible values, all overridable in
`settings.yaml`:

```yaml
filters:
  days: 7
  strict_age: false
  min_must_matches: 1
  soft_must_skills: false
  remote: false
  min_salary: 0          # 0 = off
  drop_unknown_salary: false
```

---

## 8. Enrichment Layer (scope = enrichment only)

After `rank_jobs`, enrich the top N (default 30) with a real LinkedIn posting
URL via `opencli linkedin job-detail`:

```python
# sources/enrichment.py
def enrich_job(job, timeout=30) -> dict:
    if "linkedin.com/jobs" not in job["url"]: return job
    out = subprocess.run(["opencli", "linkedin", "job-detail", job["url"], "-f", "json"], ...)
    detail = json.loads(out.stdout)[0]
    job.update({k: detail.get(k) for k in
                ("description","apply_url","workplace_type",
                 "job_type","applicants","listed","company_url")})
    # NOTE (F-06): OpenCLI job-detail returns NO salary — LinkedIn salary is
    # best-effort from search cards only. Enrichment never claims salary;
    # the salary filter tags [salary?] instead.
    job["data_quality"] = "full"
    return job
```

- Parallel (`ThreadPoolExecutor(min(top_n, 5))`), per-job isolation, per-job
  timeout, graceful failure (job keeps its search data).
- **Zero-config fallback backend:** when OpenCLI is absent/unhealthy, fall back
  to Jina Reader (`curl -s https://r.jina.ai/<job-url>`) for markdown detail
  (verified pattern from Agent-Reach `channels/web.py`); data_quality then
  stays `partial` and is tagged accordingly.
- TUI detail panel shows Salary / Workplace / Posted / Applicants / **Apply
  URL**; `o` opens `apply_url` when present, else the job URL.
- Saved jobs persist enriched fields (`actions.py` new columns).
- **No automated submission** (scope decision) — we open the apply page.

---

## 9. Ranking — calibrated to "good relevant jobs"

1. **Score enriched descriptions** when `data_quality=="full"`, snippets
   otherwise; dimensions weighted by confidence (a match on an empty field
   contributes ~0).
2. **New signals:** posting recency (favor fresh within the window), remote /
   workplace match vs `remote_preference`, must-have-skill coverage as a bonus.
3. **AI pass only on enriched candidates** — the prompt's skills/location
   weights finally have real inputs.
4. **Calibration guard:** after scoring, compute the score distribution; if
   the top-decile spread is near zero (flatline detection), flag it in
   `doctor --json` and, if configured, normalize scores.
5. **Optional final verdict (AI, top K ≤ 5):** one extra prompt — "would you
   actually recommend applying, and why?" — rendered as a short line in the
   detail panel. Gated, cached, budget-limited.
6. **Provenance tag in TUI:** `[full]` / `[snippet]` / `[salary?]` / `[age?]`
   next to the score, so low-confidence matches are obvious.

---

## 10. AI Integration — exactly how it works (rev 2)

### 10.1 Decision: REST for the AI brain, MCP for data plumbing

| Concern | Transport | Why |
|---|---|---|
| AI reasoning (profile, query gen, scoring, verdict) | **REST** — OpenAI-compatible `POST {base_url}/chat/completions` | Universal, stateless, works with any provider incl. local (Ollama), zero infra, free tiers |
| Semantic web search (Exa) | **MCP** via `mcporter` (`exa.web_search_exa`) | Agent-Reach already installs/configures it; data tool, not the AI brain |
| Exposing Matcha to other agents | **MCP server** (optional) — `matcha_search`, `matcha_status` | Mirror Agent-Reach `integrations/mcp_server.py` |

### 10.2 The AI brain (`src/matcha/ai/client.py`)

- Universal client: `base_url + api_key + model` (OpenAI-compatible).
- **No API key required to run the tool.** Missing key ⇒ heuristic-only mode,
  everything still works. AI is additive.
- Config via `matcha configure ai` wizard or `settings.yaml`:

```yaml
ai:
  enabled: true
  url: ""            # defaults per provider (see below)
  key: ""            # stored in keyring/fernet, never plaintext
  model_best: ""     # scoring / verdict (default: provider's best free)
  model_fast: ""     # query gen / title (default: same, or cheaper)
  top_n: 30
  verdict_k: 5
  max_calls: 60      # budget guard per run
  cache_ttl: 86400
```

- **Provider presets** (no lock-in; `matcha configure ai` offers them):
  - **Groq** — `https://api.groq.com/openai/v1` — strong free tier; ideal for
    `model_fast`. Agent-Reach already has a `groq-key` configure path; Matcha
    can seed from it (`agent_reach_io.seed_ai_config`).
  - **Kilo Gateway** — current default (`api.kilo.ai`, `kilo-auto/small`).
  - **OpenRouter** — free models; good `model_best` option.
  - **OpenAI / any compatible endpoint** — full key.
  - **Ollama / LM Studio** — local, no key, `url=http://localhost:11434/v1`.
- **Robustness:** timeout per call (60s scoring, 15s fast), 2 retries with
  backoff on 5xx/timeout only, `response_format` JSON where supported +
  regex-JSON fallback (existing `_extract_json`), per-task error isolation.
- **Model tiering:** `model_fast` for high-volume low-stakes tasks (query
  generation, title suggestion); `model_best` for scoring/verdicts. Defaults
  documented per provider; overridable.
- **AI result cache** (`ai/cache.py`): disk SQLite keyed by `task + hash(input)`
  with `cache_ttl` (default 24h). Re-runs and `watch` don't re-pay.
- **Budget guard:** `max_calls` per run caps spend/latency; once exhausted,
  remaining jobs keep heuristic scores. Reported in the run summary.

### 10.3 Prompts (`ai/prompts.py`)

All prompts versioned and single-sourced; prompts already tuned (profile
extraction, query generation, critical job scoring) are moved here verbatim,
plus a new **verdict** prompt (top-K recommendation) and a **query validation**
pass. Prompt changes are diff-reviewable.

### 10.4 MCP usage

- **Exa** — `agent_reach_io.exa_search` shells `mcporter call
  'exa.web_search_exa(query: "...", numResults: 5)'`; used as Web Search
  backend when the server is configured, DDGS otherwise.
- **Matcha MCP server** (optional) — expose `matcha_search`, `matcha_status`
  to any MCP-aware agent; same code path as `--json`, wrapped as MCP tools.
- Never required to run; purely additive.

---

## 11. Profile & Query Layer

- Keep PDF/LinkedIn/manual entry + supplement flow.
- **Optional GitHub enrichment** via `gh` (repos/languages → suggested skills).
- `Profile` gains `must_have_skills`, `min_salary`, `remote_preference`,
  `github_username` (see §14).
- Query expansion stays AI + validation gate; add **location-aware** and
  **seniority-aware** variant generation (already in plan), and a location
  term injected into ≥1 query.

---

## 12. Human TUI

- Startup line per source from `doctor`: `LinkedIn (OpenCLI) · Indeed (html) ·
  Naukri (ddgs) · Web (Exa) …`.
- Filter summary before results: `96 kept (age −142 · must-skill −21 · loc −33 …)`.
- Detail panel: enriched fields + verdict line + provenance tags.
- Status table: live per-source counts/errors (exists).
- Keys: `s` save / `o` open (apply_url-aware) / `l` saved / `r` re-run / `q`.

---

## 13. Agent & Automation Surface

- **`--json`** — ranked, enriched, filtered jobs as structured JSON on stdout.
- **SKILL.md** (`skill/SKILL.md`, zh+en) installed to `~/.agents/skills/matcha`
  / `~/.claude/skills/matcha`: run `matcha doctor --json` → `matcha search
  --query … --location … --days 7 --json` → summarize top matches.
- **`matcha watch`** — one-shot, cron-able; writes `~/.matcha/latest.json`;
  plus **new-vs-seen** diffing (`track.py`) so `watch` surfaces only jobs not
  already seen (SQLite `seen_urls`).
- **Optional MCP server** — see §10.4.

---

## 14. Data Model Changes

```python
class Job(BaseModel):
    title: str = ""
    company: str = ""
    location: str = ""
    description: str = ""
    url: str = ""
    source: str = ""
    # enrichment:
    apply_url: str = ""
    salary: str = ""
    salary_int: int | None = None      # normalized LPA
    workplace_type: str = ""           # Remote / Hybrid / On-site
    job_type: str = ""
    listed: str = ""
    listed_epoch: int | None = None    # normalized posting time (filters/rank use this)
    applicants: str = ""
    company_url: str = ""
    # provenance:
    backend: str = ""
    data_quality: str = "partial"      # full | partial | snippet
    city: str = ""                     # normalized
    remote_ok: bool = False

class Profile(BaseModel):
    ...existing...
    must_have_skills: list[str] = []
    min_salary: int = 0
    remote_preference: str = ""        # remote | hybrid | onsite
    github_username: str = ""

class FilterReport(BaseModel):          # one per filter stage
    name: str
    kept: int
    dropped: int
    reason: str
```

`actions.py` SQLite: add `apply_url, salary, salary_int, workplace_type,
company_url, listed_epoch` (idempotent `ALTER TABLE` migration) + `seen_urls`
table.

---

## 15. Robustness & Failproofing (rev 2)

| Concern | Mechanism |
|---|---|
| Tool missing/broken vs healthy | `probe.probe_command` (real execution, stale-venv detection) |
| One source dies | Per-source isolation; `ScraperResult.errors` surfaced in TUI; others unaffected |
| One backend dies | Ordered fallback within source (`opencli` → `guest-api` → `ddgs`) |
| Repeated source failure | **Circuit breaker** in `registry.py` (3 strikes → cooldown, visible) |
| Network blips | Retry w/ exponential backoff (2s→4s→8s) on 5xx/timeout only; per-domain token buckets |
| Slow/hung scrapers | Per-source timeout (default 45s), `ThreadPoolExecutor` bounded (≤12) |
| Repeat searches cost | requests-cache SQLite (TTL 30m for search, 6h for detail), offline-friendly |
| AI down/slow | 2 retries, timeout, per-task isolation, heuristic-only fallback, budget guard |
| One bad job | Per-job try/except in parse + enrichment; garbage dropped by quality gate |
| Old jobs leak in | Central age filter (§7.1) — final authority over scrapers |
| API key leak | keyring + fernet; config masking; 0600; symlink rejection |
| Partial results lost | None — counts always shown (`ingest → … → present`) |
| Determinism | Stable sort keys, pinned deps, seeded random |

### 15.1 Error taxonomy (`errors.py`)

```
MatchaError
├── ConfigError
├── SourceError
│   └── BackendError (missing/broken/timeout)
├── ParseError
├── FilterError
└── EnrichmentError
```

No bare `except:`. Every catch is typed and logged with context. User-facing
messages are scrubbed of URLs/credentials (`scrub_url_credentials`).

### 15.2 Logging

Rotating file (`~/.matcha/logs/matcha.log`, 5 MB × 3) + stderr; TUI on stdout.
Levels: INFO per stage counts, WARNING per source/backend failure, ERROR per
crash. Debug holds raw responses.

---

## 16. Code Quality & Testing (rev 2)

### 16.1 Standards

- **Package layout:** move to `src/matcha/` (clean imports, no root-path hacks).
- **Type hints everywhere**; `mypy` strict-mode-ish (`pyproject.toml`), run in
  CI.
- **ruff** (lint + format): `E,F,I,UP,B,SIM,BLE`; `line-length=100`.
- **bandit** for security (already configured).
- **Pydantic models used at runtime** — jobs, profiles, filters, settings are
  validated at boundaries, not raw dicts.
- **Typed exceptions** (§15.1), no silent swallow, deterministic ordering.
- **Pre-commit** (already present) + CI gate on lint/type/test.

### 16.2 Test matrix

| Layer | What | Approach |
|---|---|---|
| Unit | `matcher`, `dedup`, `filters`, `normalization` (age parsing, salary parse, city mapping), `probe` | pure functions, known in/out |
| Contract | `sources/registry`, `Source.check()`, `ordered_backends()`, doctor result shape (ported from Agent-Reach `test_channel_contracts.py`) | status ∈ {ok,warn,off,error}, non-empty message, `active_backend` None\|str, permutation invariant, unique names |
| Integration | Each source parser with **HTML/JSON fixtures** (snapshots of LinkedIn/Indeed/Naukri/RemoteOK pages); OpenCLI wrappers with mocked subprocess | responses/snapshots in `tests/fixtures/` |
| E2E | Full pipeline with mocked network (requests-cache + stub responses) | deterministic, offline |
| Degradation | No OpenCLI · no Agent-Reach · no AI · no network | each must still work or report clearly |

CI (existing 4-stage workflow) extended: `lint → typecheck → test → coverage
(≥80%)`. **Fixes required up-front (F-02/F-03):** CI must run the **full**
suite (`python -m unittest discover tests -v`), not just `tests.test_core`,
and the matrix gains Python 3.14 (dev venv is 3.14.6).

---

## 17. Config & Security

- Port Agent-Reach discipline: atomic writes (`mkstemp` beside target,
  `fchmod` 0600, `fsync`, `os.replace`, dir fsync via `O_DIRECTORY`), **0600**
  on `config.json` / `profile.json` / encrypted blobs, **component-wise
  symlink rejection** (`ensure_no_symlink_path` on every path part — not just
  the final file), **credential masking** in all output, `read_only` config
  mode, and reads that never create files/dirs (see §6.8).
- Secrets (AI key, SerpAPI key) via `keyring` with `fernet` fallback (already
  present).
- Feature gating mirrors `FEATURE_REQUIREMENTS` (feature → required config
  keys), so doctor can say *exactly* which key to set to unlock a source.
- `~/.matcha/` layout:
  `config.json`, `profile.json`, `settings.yaml`, `jobs.db`, `ai_cache.sqlite`,
  `http_cache.sqlite`, `source_state.json`, `latest.json`, `logs/`.
- Optional **proxy** support (export to upstream tools) — matches Agent-Reach's
  `configure proxy`.

---

## 18. Implementation Phases (with acceptance criteria)

### Phase 0 — Foundation (2–3 days, scope expanded by the implementation-analysis)
`src/` layout, `errors.py`, `probe.py`, `doctor.py`, `sources/` registry +
`base.py`, provenance fields on `ScraperResult`. Existing scrapers refactored
into `sources/*` with **no behavior change**.

**Expanded scope (F-01…F-05, F-08, F-09, F-11, F-18):**
- **Root shims** (`main.py ai.py matcher.py config.py settings.py models.py
  actions.py profile.py scrapers/` re-export from `matcha.*`) so `python3
  main.py`, tests, Makefile, CI, Docker and pyinstaller stay green with ZERO
  downstream change — the layout move itself breaks nothing (F-04).
- CI fixes (F-02/F-03): run the **full** suite
  (`python -m unittest discover tests -v`); add Python `"3.14"` to the matrix.
- Fix `target-version = "py310"` in pyproject (was py39; code uses 3.10+
  syntax) + one-time `ruff check --fix`.
- Fix the time-dependent test `test_days_filter.py::test_date_string_within`
  (F-09) with time-relative fixtures so CI is green.
- `career_sites` registered as a Source but **default-off** via
  `scrapers.career_sites: false` (preserves "no behavior change"; enable in
  Phase 1).
- LinkedIn empty-location default (F-08, **user-confirmed**): default to
  `"India"` instead of `"United States"`.
- Replace `os._exit(0)` in `main()` with `sys.exit(0)` + explicit DB commits
  (F-05).

**Deferred to Phase 1 (start):** the entry-point migration — `pyproject.toml`
`[project]` + console script `matcha = matcha.main:main` (implemented; no cli.py needed), `pip install -e .` in
Makefile/CI, bandit/pyinstaller/Dockerfile/README path updates for
`src/matcha` (pyinstaller builds from a small entry module or the installed
console script — not `-m matcha`), then **delete the root shims**.

**Accept:** `matcha doctor [--json]` lists all sources with real status; the
**full** test suite passes; `python3 main.py --help` and `python3 main.py
doctor` both work; CI green.

### Phase 1 — Data quality (the big lever, 3–5 days)
OpenCLI backends for LinkedIn/Indeed (+ consent flow), Exa Web Search backend,
Naukri job-page extraction, `agent_reach_io`. **Also (start):** the
entry-point migration deferred from Phase 0 — `[project]` + console script
`matcha`, `pip install -e .`, bandit/pyinstaller/Dockerfile/README path
updates, then **delete the root shims**.
**Accept:** LinkedIn ≥25 results with descriptions (consented); Indeed works on
py3.14; doctor shows active backends; `matcha doctor --json` runs via the
installed console script.

### Phase 2 — Normalize + filters (2–3 days)
`normalization.py`, `filters.py` (age/must-skills/location/salary/quality),
filter report in TUI and JSON.
**Accept:** `--days` is enforced centrally; unknown-age jobs tagged; filter
counts shown; garbage jobs dropped.

### Phase 3 — Enrichment (2–3 days)
`enrichment.py`, model + DB columns, TUI detail fields, apply_url-aware `o`.
**Accept:** top-30 LinkedIn jobs enriched ≤60s parallel; per-job failures
graceful.

### Phase 4 — Ranking recalibration (2–3 days)
Confidence-weighted heuristic, recency/workplace signals, AI on enriched
candidates, flatline detection, verdict pass, provenance tags.
**Accept:** score distribution spreads; full-data jobs outrank snippet-guesses.

### Phase 5 — AI provider-agnostic + cache + budget (2–3 days)
`ai/client.py`, presets (Groq/Kilo/OpenRouter/local), model tiers, disk cache,
budget guard, `matcha configure ai` wizard.
**Accept:** works with Groq free tier and with zero config (heuristic-only);
no key leak; cache hits on re-run.

### Phase 6 — Agent + automation (2–3 days)
`--json`, SKILL.md + installer, `matcha watch` + new-vs-seen, optional MCP.
**Accept:** an agent drives a full search via the skill; `watch` surfaces only
new jobs.

### Phase 7 — Hardening (1–2 days)
Circuit breakers, config hardening, GitHub profile enrichment, RSS source,
coverage ≥80%, README + docs.

---

## 19. Gaps Closed (rev 2 checklist)

- [ ] Job-age filter enforced **centrally** with normalized `listed_epoch` + unknown-age tagging
- [ ] Must-have-skills dealbreaker gate (with synonym map, soft mode)
- [ ] Location/remote filter with city synonym normalization
- [ ] Salary-floor filter + `[salary?]` tagging
- [ ] Data-quality gate (placeholder/tracking-URL/garbage rejection)
- [ ] Canonical URL + fuzzy dedup with **keep-best by data_quality**
- [ ] New-vs-seen tracking for `watch`
- [ ] Circuit breakers per source
- [ ] Typed error taxonomy; zero bare `except`
- [ ] AI: provider-agnostic REST client, free-tier presets, model tiers, disk cache, budget guard, heuristic-only fallback
- [ ] MCP: Exa via mcporter; optional Matcha MCP server; never required
- [ ] `src/` package layout; mypy strict; ruff; coverage gate
- [ ] Pydantic models used at runtime (jobs/profile/filters/settings)
- [ ] Config hardening: atomic writes, 0600, symlink rejection, masking
- [ ] Filter/pipeline stage counts surfaced in TUI + JSON
- [ ] RSS source + GitHub profile enrichment (optional)

---

## 20. Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| OpenCLI not installed / bridge down | Medium | High | doctor detects; fallback chain; `agent-reach install --channels=opencli` |
| LinkedIn consent declined | Medium | Medium | guest API remains; one-time prompt, remembered |
| LinkedIn rate-limits OpenCLI | Medium | Medium | token buckets + circuit breaker; doctor surfaces |
| Exa free tier limits | Low | Medium | DDGS fallback |
| `opencli` DOM drift | Medium | Medium | OpenCLI retry/matching; doctor reports; keep fallbacks |
| Naukri structure changes | Medium | Medium | ddgs discovery + enrichment; isolated parser |
| cloudscraper breaks on 3.14 | High | Medium | OpenCLI preferred backend removes dependency |
| AI provider limits | Low | Medium | budget guard, cache, heuristic fallback |
| Age parsing wrong for one source | Medium | Low | per-source parsers + tests; unknown-age tagging never falsely drops |
| OpenCLI JSON output shape drifts (`-f json` unverified, DOM changes) | Medium | Medium | lock flag at implementation (F-07); parser with tolerant fallback; keep html/DDGS backends |
| Enrichment yields no salary (LinkedIn DOM) | High | Low | salary stays best-effort + `[salary?]` tag (F-06); never claim salary from job-detail |
| Enrichment can't enrich non-LinkedIn URLs | Medium | Medium | Jina Reader fallback + `data_quality=partial` tagging (F-20) |

---

## 21. Scope Cuts

- **No automated application submission** — enrich + open apply page only.
- **No multi-user / web / multi-tenant** — personal tool.
- **No general scraping platform / data selling.**
- **No TUI framework rewrite** — incremental changes only.
- **No background daemon** — `watch` is one-shot cron-friendly.

---

## 22. File Change Summary

| File | Change |
|---|---|
| `src/matcha/sources/` (new) | Registry + per-source backends replacing `scrapers/*` |
| `src/matcha/probe.py` (new) | Real-command probing (ported) |
| `src/matcha/doctor.py` (new) | Per-source health report (ported) |
| `src/matcha/filters.py` (new) | Centralized filter pipeline incl. age filter |
| `src/matcha/normalization.py` (new) | Canonical Job (epoch, salary, city, remote) |
| `src/matcha/dedup.py` (new) | Canonical + fuzzy keep-best |
| `src/matcha/track.py` (new) | New-vs-seen diffing |
| `src/matcha/errors.py` (new) | Typed exception hierarchy |
| `src/matcha/sources/enrichment.py` (new) | OpenCLI job-detail enrichment |
| `src/matcha/agent_reach_io.py` (new) | Adapter to `agent-reach` / mcporter / gh |
| `src/matcha/ai/` (new) | client.py (REST), prompts.py, tasks.py, cache.py |
| `src/matcha/skill/` (new) | SKILL.md + installer |
| `src/matcha/main.py`, `cli.py` | Orchestrator, dispatch, `--json`, `--days`, `watch` |
| `src/matcha/matcher.py` | Confidence-weighted scoring + flatline detection |
| `src/matcha/models.py` | Extended Job/Profile/FilterReport |
| `src/matcha/actions.py` | New columns + seen_urls table |
| `src/matcha/config.py` / `settings.py` | Hardened; filter + ai sections |
| `scrapers/*` | Move into `sources/` (keep parsers as backends) |
| `tests/` | Unit/integration/e2e + fixtures |
| `pyproject.toml`, `Makefile`, CI | ruff/mypy/pytest/bandit/coverage gate |
| `revamp/matcha-2.0-strategy.md` | This document |

---

## 23. Success Criteria

Matcha 2.0 is worth using when, in one terminal session:

1. `matcha doctor` shows which backend serves each source and why.
2. A Pune/India DevOps search returns dozens of **enriched** jobs — real
   descriptions, salary, workplace, posting date, and an **apply URL**.
3. `--days 2` keeps only jobs from the last 2 days; older ones are dropped and
   counted, not silently included.
4. Must-have-skills + salary + location filters visibly cut the list to jobs
   actually worth the user's time.
5. Scores are calibrated: good matches rank top; snippet-guesses are visibly
   tagged low-confidence.
6. The same pipeline is drivable by an AI agent via SKILL.md + `--json`.
7. No source failure is silent — doctor or the TUI always says what broke and
   how to fix it.
8. Removing AI keys, OpenCLI, Agent-Reach, or the network each still produces
   a working (if degraded) run with clear messaging.
