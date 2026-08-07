# Matcha 🍵

> **Matcha! Your next role, perfectly brewed.**
>
> Multi-source job aggregator with AI-powered relevance ranking. Enter your profile once — get ranked, personalized job matches from across the web.

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)]()
[![Rich TUI](https://img.shields.io/badge/built%20with-Rich-ffd700)]()
[![AI Matching](https://img.shields.io/badge/feature-AI%20Scoring-8a2be2)]()

> **New here?** Start with the [**5-Command Quickstart**](QUICKSTART.md) —
> install, run, AI, doctor, and headless search in under two minutes.

---

## Why This Exists

Job boards show you **every** posting matching a keyword. This tool shows you only the ones that actually **fit your profile** — your skills, experience level, location, and career trajectory. It aggregates jobs from 5+ sources in parallel, scores them against your profile using a two-pass heuristic + AI engine, and presents them in a beautiful terminal UI with ranked relevance.

---

## Features

**Multi-Source Aggregation** — Searches LinkedIn, Indeed, Naukri, RemoteOK, and web search results simultaneously. Optionally integrates Google Jobs via SerpAPI. 30+ parallel requests across diverse queries yield **200–500+ unique listings** per search.

**Two-Pass Relevance Engine**
1. **Heuristic pass** — Confidence-weighted scoring across 5 dimensions (skills, title, seniority, location, keywords) on every job — text-derived dimensions scale by data richness, so full descriptions outrank snippet guesses. Plus recency, remote-workplace, and must-have-skill bonuses. Completes instantly even for 500+ listings.
2. **AI pass** — Top N (default 30) **enriched candidates** re-scored by an LLM that understands role semantics, skill adjacency, and career trajectory. Critical prompt tuning ensures honest, discriminating scores.

**Central Filter Pipeline** — every job is normalized (listed date, salary, city/region, remote) then filtered in a fixed order: data quality → age → must-have skills → location → salary, each reporting exactly how many jobs it cut (`Filtered: 96 kept (age −142 · must −21 …)`). Provenance tags (`[full]` / `[snippet]` / `[age?]` / `[salary?]`) make low-confidence matches obvious.

**Three-Way Profile Entry**
- **PDF Resume** — Extracts name, title, skills, experience, and summary via AI (no fallback keyword matching). All skill detection is LLM-driven.
- **LinkedIn URL** — Fetches public profile data with DuckDuckGo fallback when LinkedIn blocks direct access (HTTP 999). Supplement mode lets you fill gaps.
- **Manual Entry** — Full control over every field. Always works.

**AI Query Expansion** — Generates 3–5 diverse search queries from your profile (e.g., "Platform Engineer" → "Site Reliability Engineer", "Cloud Infrastructure Engineer", "DevOps Automation", "Developer Productivity Engineer"), dramatically expanding the search surface.

**Intelligent URL Resolution** — Indeed tracking URLs (`/rc/clk`, `/pagead/clk`) are transparently resolved to clean `viewjob` URLs using job key extraction and fallback HEAD redirect following.

**Rich Terminal UI**
- Color-coded match scores (green ≥ 60, yellow ≥ 25, red < 25)
- Paginated results table (10 per page)
- Interactive job detail panel with full URL, match reasons, and description
- Live progress status for search and AI scoring phases
- Persisted profile and config across sessions

**Zero Paid API Requirements** — All core sources work without API keys. SerpAPI (Google Jobs) and AI scoring are optional enhancements.

---

## Architecture

```
                         ┌──────────────────────────────────────┐
                         │           matcha (CLI)               │
                         │  Profile → Query Expansion → Search  │
                         │  → Two-Pass Ranking → Display        │
                         └───────┬──────────┬──────────┬────────┘
                                 │          │          │
                    ┌────────────┘          │          └────────────┐
                    ▼                       ▼                      ▼
           ┌────────────────┐    ┌──────────────────┐    ┌──────────────────┐
           │  Profile Layer │    │  Relevance Layer  │    │  Scraper Layer   │
           │  profile.py    │    │  matcher.py       │    │  sources/        │
           │  ai.py         │    │  ai.py            │    │                  │
           │                │    │                  │    │  • LinkedIn      │
           │  • PDF (AI)    │    │  • Heuristic (5  │    │  • Indeed        │
           │  • LinkedIn    │    │    dimensions)   │    │  • Naukri        │
           │  • Manual      │    │  • AI re-scoring │    │  • RemoteOK      │
           │                │    │  • Query gen     │    │  • Web Search    │
           └────────────────┘    │  • Title suggest │    │  • SerpAPI (opt) │
                                 └──────────────────┘    └──────────────────┘
```

### Data Flow

1. **Profile Ingestion** — Resume PDF, LinkedIn URL, or manual input → AI-extracted profile (name, title, skills, experience, summary). No fallback keyword lists or hardcoded mappings.
2. **Query Expansion** — Base query + AI-generated variant queries targeting adjacent roles
3. **Parallel Scraping** — `ThreadPoolExecutor` dispatches all queries × all scrapers concurrently (up to 30 tasks)
4. **Deduplication** — Title+company hash eliminates cross-source duplicates
5. **Normalize + Filter** — `normalization.py` derives `listed_epoch` / `salary_int` / `city` / `remote_ok`; `filters.py` enforces quality → age → must-skills → location → salary centrally (age filter is the final authority on freshness)
6. **First-Pass Ranking** — Confidence-weighted heuristic (data-richness × dimensions) with recency/workplace/must-skill signals
7. **Second-Pass Ranking** — Top N (default 30) **enriched candidates** re-scored by LLM with structured JSON output; flatline guard warns on homogeneous scores
8. **Enrichment** — Top N ranked jobs get full descriptions + apply URLs (OpenCLI job-detail, Jina fallback)
9. **Display** — Paginated table with color-coded match scores + provenance tags → interactive detail view

---

## Installation

### System Requirements

- **Python 3.10+** required for all scrapers (`ddgs` dependency). On Python 3.9 only Indeed works (via `cloudscraper`).
- **Python 3.14** — Supported inside a virtual environment (see below)
- **macOS only** — Not tested on Linux/Windows

### Quick Start (from existing clone)

```bash
python3 -m venv venv
venv/bin/pip install -r requirements.txt
venv/bin/pip install -e .
venv/bin/matcha
```

This creates a virtual environment, installs dependencies, installs the
`matcha` console script, and runs the app — without needing to manually
activate the venv. `venv/bin/matcha doctor --json` prints a per-source
health report.

### Fresh Setup

```bash
git clone https://github.com/yourusername/matcha.git
cd matcha
python3 -m venv venv
venv/bin/pip install -r requirements.txt
venv/bin/pip install -e .
venv/bin/matcha
```

> **Note:** A virtual environment is required — it avoids urllib3 v2 + macOS LibreSSL segfaults on Homebrew Python, and ensures dependencies install into the correct location. If you see `Defaulting to user installation because normal site-packages is not writeable`, the venv is not activated or the symlinks are broken — recreate it with `rm -rf venv && python3 -m venv venv`.

> **Tip:** `make venv` bootstraps the venv, dependencies, and dev tooling
> (ruff, bandit, pre-commit) in one step; `make run` then starts Matcha.

### Docker (optional)

A container image is provided — note it runs the interactive TUI, so use `-it`:

```bash
docker build -t matcha:latest .
docker run -it --rm -v "$HOME/.matcha:/home/app/.matcha" matcha:latest
```

The image runs as a non-root `app` user and keeps all state in
`/home/app/.matcha` — mount that volume to persist your profile/config across
runs.

### Dependencies

| Package | Purpose |
|---------|---------|
| `requests` | HTTP client for all scrapers |
| `requests-cache` | SQLite-backed HTTP cache (30-min TTL, 200-only) |
| `beautifulsoup4` | HTML parsing for all scrapers |
| `rich` | Terminal UI (tables, panels, progress bars, prompts) |
| `cloudscraper` | Cloudflare bypass for Indeed India (Python 3.9 only; 403s on 3.14) |
| `ddgs` | DuckDuckGo API — powers Web Search, Naukri, and Indeed fallback scrapers |
| `pdfplumber` | PDF resume text extraction |
| `prompt_toolkit` | Interactive keyboard-driven UI for job browsing |
| `rapidfuzz` | Fuzzy string matching for deduplication |
| `pydantic` | Data models for profile, jobs, and settings |
| `pyyaml` | YAML config file support |
| `python-dotenv` | Installed but not loaded — export env vars in your shell |
| `urllib3<2` | Pinned to v1 to prevent LibreSSL segfault on macOS |

---

## Before You Run — Exact Setup Steps

**No environment variables are required** — every source works out of the box
and AI is an optional enhancement (zero config = heuristic-only ranking). Do
these once, in order:

1. **Install** (Python 3.10+, venv required on macOS):
   ```bash
   python3 -m venv venv
   venv/bin/pip install -r requirements.txt
   venv/bin/pip install -e .
   ```
2. **Create your profile** — the first `matcha` run asks how (PDF resume,
   LinkedIn URL, or manual entry). Your profile is saved to
   `~/.matcha/profile.json` and reused on later runs:
   ```bash
   venv/bin/matcha
   ```
3. **Enable AI matching (recommended)** — set the key directly (fastest):
   ```bash
   export MINIMAX="your-api-key"
   venv/bin/matcha        # AI is on — the results banner shows "(AI)"
   ```
   …or run the interactive wizard, which stores the key encrypted at rest
   (fernet, `~/.matcha/*.enc` — no OS keychain prompts) and walks through
   provider selection plus optional SerpAPI / OpenCLI setup:
   ```bash
   venv/bin/matcha --configure
   ```
   The wizard auto-skips any step already configured (e.g. if `MINIMAX` is
   exported). With no key/provider the tool still works — it just runs
   heuristic-only. See [Environment Variables](#environment-variables) for
   every knob (`AI_PROVIDER`, `AI_API_URL`, `AI_MODEL`, `AI_MODEL_FAST`).
4. **(Optional) Google Jobs** — add a SerpAPI key via `matcha --configure`
   (free tier: 100 searches/month).
5. **(Optional) Richer LinkedIn/Indeed** — connect OpenCLI so searches run
   through your logged-in Chrome and return real descriptions, salaries and
   posting dates:
   ```bash
   npm install -g @jackwener/opencli
   # enable the OpenCLI Chrome extension, then:
   venv/bin/matcha --configure    # answer yes to the OpenCLI consent prompts
   ```
6. **(Optional) GitHub skill suggestions** — `matcha github enrich` (needs
   `gh` installed + authenticated, or `GH_TOKEN`).
7. **Verify everything is healthy:**
   ```bash
   venv/bin/matcha doctor         # per-source health + active backends
   venv/bin/matcha doctor --json  # machine-readable report
   ```
   A healthy report shows `ok` for the zero-config sources (RemoteOK, Naukri,
   Web Search, …) **and** an **AI matching** line: `ok` when the provider,
   models, and key are all wired — `off` when untouched (heuristic-only),
   `warn` when partially configured (e.g. a key with no provider). The line
   shows provider, best/fast models, and whether a key is set — never the
   key itself. In `doctor --json` this is the `ai` entry (`provider`,
   `provider_label`, `key_set`, `model_best`, `model_fast`, `available`,
   scrubbed `url`).
8. **Run:**
   ```bash
   venv/bin/matcha
   ```

### Where Matcha keeps its files

All state lives under `~/.matcha/` (plus an optional `matcha.yaml` in the
directory you run from):

| Path | Purpose |
|---|---|
| `~/.matcha/profile.json` | Your profile (skills, title, experience, `must_have_skills`, …) |
| `~/.matcha/config.json` | Non-secret config + `last_query` / `last_location` / `last_days` |
| `~/.matcha/settings.yaml` | Optional YAML overrides (see the Config File section) |
| `~/.matcha/fernet.key` + `.ai_key.enc` / `.serpapi_key.enc` | Secrets encrypted at rest — the secret store (no OS keychain dependency) |
| `~/.matcha/source_state.json` | Per-source circuit-breaker state |
| `~/.matcha/jobs.db` | Saved jobs + `seen_urls` (the new-vs-seen store for `matcha watch`) |
| `~/.matcha/ai_cache.sqlite` | Opt-in AI disk cache |
| `~/.matcha/logs/matcha.log` | Rotating debug log (5 MB × 3) |

## Environment Variables

**None are required** — the tool is fully usable with zero env vars. Set
these only to enable the optional AI / GitHub features or force a source
backend.

### AI — the only ones you usually need

| Variable | Purpose | Default |
|---|---|---|
| `MINIMAX` | **AI API key** — the single switch that turns AI on (legacy name kept; the key sent to the provider) | unset → heuristic-only mode |
| `AI_PROVIDER` | Provider preset: `groq` \| `kilo` \| `openrouter` \| `openai` \| `local` | `kilo` (wizard default) |
| `AI_API_URL` | OpenAI-compatible base URL override (wins over the preset) | provider preset |
| `AI_MODEL` | Best-tier model (AI scoring, verdicts, profile extraction) | provider preset |
| `AI_MODEL_FAST` | Fast-tier model (query expansion, title suggestion) | provider preset |

Every slot resolves in the same order: **env var → `~/.matcha/config.json`
→ `~/.matcha/settings.yaml` → provider preset default** — so env vars
override the wizard, which overrides YAML, which overrides the default.

### GitHub enrichment

| Variable | Purpose | Default |
|---|---|---|
| `GH_TOKEN` / `GITHUB_TOKEN` | Read-only auth for `matcha github enrich` (else uses `gh` hosts.yml) | — |
| `GH_CONFIG_DIR` | `gh` config directory override | `~/.config/gh` |
| `XDG_CONFIG_HOME` | Also honored when locating `gh`'s `hosts.yml` | OS default |

### Advanced / power-user

| Variable | Purpose | Default |
|---|---|---|
| `<SOURCE>_BACKEND` | Force a backend for one source — e.g. `LINKEDIN_BACKEND=guest`, `INDEED_BACKEND=ddgs`, `NAUKRI_BACKEND=job-page`. Valid values are that source's backend names (see `matcha doctor`); unknown values are ignored so a stale override can never hide working backends. Equivalent YAML: `scrapers.<source>_backend` | ordered fallback list |
| `MCPORTER_CONFIG` | mcporter config path for the Exa web-search backend | auto-discovered |
| `MATCHA_AI_CACHE` | Path for the AI disk-cache SQLite file | `~/.matcha/ai_cache.sqlite` |
| `MATCHA_HTTP_CACHE_TTL` | HTTP response-cache TTL in seconds — **0 = off**, every run fetches fresh pages (set e.g. `300` if repeat runs hammer a source) | `0` (off) |

Example (any shell):

```bash
export MINIMAX="your-key-here"   # the one switch that enables AI
export AI_PROVIDER=kilo          # optional — kilo is already the default
venv/bin/matcha
```

Notes:

- `MINIMAX` is read **in addition to** a key stored via `matcha --configure`
  (the encrypted fernet store, `~/.matcha/*.enc`) — the env var wins when
  both exist.
- **SerpAPI** and **OpenCLI** have **no env vars** — both are configured
  interactively via `matcha --configure` (the SerpAPI key is stored as a
  secret via the encrypted fernet store, never in YAML).
- `AI_PROVIDER=local` (Ollama / LM Studio) needs **no API key** — just set
  `AI_PROVIDER=local` and optionally `AI_API_URL` / `AI_MODEL`.
- There is **no `.env` file support** — `python-dotenv` is a dependency but
  is never loaded. Export variables in your shell, or put non-secret
  settings in `~/.matcha/settings.yaml`.

---

## Usage

### Command Reference

```
matcha                                    # interactive TUI (profile → search → browse)
matcha --configure                        # setup wizard: SerpAPI key, AI provider+key, OpenCLI consent
matcha --new-profile                      # re-enter your profile from scratch (-n)
matcha --non-interactive                  # skip all prompts (-b) — needs a saved profile / YAML config
matcha --days N                           # age-window override for one run (also: filters.days)
matcha --config PATH                      # load a specific YAML settings file

matcha doctor [--json]                    # per-source health + AI availability + backends + circuits
matcha search -q "Platform Engineer" -l Pune -d 7 [--json] [--output FILE] [--top N] [--no-ai-queries] [--no-enrich]
matcha watch -q "Platform Engineer" -l Pune -d 7 [--json] [--output FILE] [--top N] [--no-ai-queries] [--no-enrich] [--no-mark-seen]
matcha skill --install [--dest PATH]      # install the agent skill (also: --uninstall)
matcha mcp                                # optional MCP server (pip install -e '.[agent]')
matcha github enrich                      # merge GitHub signals into profile.json (needs gh)
```

`search`/`watch` need a saved profile — create one with a first interactive
`matcha` run (or `matcha --new-profile`). `doctor`, `skill`, `mcp`, and
`github` work without one.

### 1. Complete Flow

```
╭────────────────────────────────────────────────╮
│ Matcha                                     │
│ Multi-source job search with relevance ranking │
╰────────────────────────────────────────────────╯

Profile: Rishikesh Vijay Sonawane — CI/CD Infrastructure | DevOps (36 skills, ~4y exp)
Use existing profile? [y/n] (y): n

How would you like to enter your profile?
  1. Enter details manually
  2. Upload a resume PDF
  3. Provide a LinkedIn profile URL
Choose [1/2/3] (1): 2
Path to resume PDF: /path/to/resume.pdf
Extracting profile with AI...

Resume parsed:
  Name          Rishikesh Vijay Sonawane
  Title         CI/CD Infrastructure | DevOps
  Skills        37 detected: AWS, EC2, IAM, VPC, Auto Scaling Groups, ECR, Terraform, GitOps, Atlantis, Bash Scripting, GitHub Actions, Self-Hosted Runners, GitHub Enterprise Cloud, CI/CD Platform Engineering, Docker, Amazon ECR, Docker Image Optimization, Pull-Through Cache, Datadog, Infrastructure Monitoring, Alerting, Incident Response, Linux, Git, Access Management, Developer Tooling, ChatGPT, Claude, Cursor, LibreChat, LLM-CLI, CI/CD Infrastructure Engineering, GitHub Actions & Self-Hosted Runners, Developer Productivity Engineering, AWS Platform Automation, Infrastructure Cost Optimization, Internal Developer Platforms
  Experience    ~4 years

Does this look correct? You can supplement it. [y/n] (y): y
Additional skills (comma-separated, or leave blank) ():

Job search query (CI/CD Infrastructure | DevOps): Platform Engineering
Location (or blank for remote) (Pune bengaluru hyderabad):
Show jobs posted within how many days? (7): 2

AI queries: Platform Engineering, Platform Engineer Terraform, DevOps Engineer AWS, CI/CD Engineer GitHub, Infrastructure Engineer Datadog, DevOps Engineer Bengaluru
  OK     Indeed                   83
  OK     LinkedIn                  1
  OK     Naukri                   44
  OK     RemoteOK                 31
  OK     Web Search               64

Found 207 total jobs (AI)
  83 from Indeed | 1 from LinkedIn | 44 from Naukri | 31 from RemoteOK | 64 from Web Search


                  Matching Jobs (page 1/21) (AI)
 #     Title                    Company          Source      Match
───────────────────────────────────────────────────────────────────
 1     AWS Devops Engineer      Capgemini        LinkedIn    92.0%
 2     Software Engineer II     Microsoft        Indeed      92.0%
 3     DevOps Engineer-III      ADCI             Indeed      92.0%
 4     DevOps Engineer II       ADCI             Indeed      92.0%
 5     DevOps Engineer-III      ADCI             Indeed      92.0%
 6     devOps engineer          Redbytes         Indeed      85.0%
                                Software
 7     NTT Data AWS Cloud       NTT Data         LinkedIn    82.0%
       DevOps engineer
 8     Software Development     ADCI             Indeed      55.0%
       Engineer II



↑↓ navigate  Enter detail  s save/unsave  o open  n/p page  l saved  r re-run  q quit
```

### 2. Profile Entry

Three methods:
- **PDF Resume** — Extracts structured data via `pdfplumber`, then AI handles all skill/title/experience extraction. No keyword lists or fallback patterns.
- **LinkedIn URL** — Scrapes public profile with DuckDuckGo fallback (when LinkedIn blocks with HTTP 999)
- **Manual** — Full control over every field; always works

If AI is unavailable, the tool prints an error and offers manual entry only — no silent fallback to keyword matching.

### 3. Search & Results

```
Job search query (CI/CD Infrastructure | DevOps):
Location (or leave blank for remote): Pune
```

Jobs are searched across all configured sources in parallel using the base query plus AI-generated variants.

Interactive features:
- **Paginated browsing** — `↑↓` navigate, `n/p` page, `Enter` for details
- **Already-seen hiding** — every run records what it showed; next run hides those jobs by default (`h` toggles all), and saving a job (`s`) retires it from future lists. When everything was already seen, you get a clear **"No new jobs"** state (`h` to view them anyway, `r` to search again) instead of the same list replayed — no more caching-like repeat results
- **Job details** — Full URL, match reasons, and description
- **Save jobs** — Press `s` to save/unsave; `l` to view saved. Saved rows persist the enriched/normalized fields (salary, apply_url, workplace, company_url, posted date) via an idempotent SQLite migration, and the Saved screen shows Salary + Posted columns
- **Open in browser** — Press `o` to open job URL
- **Re-run** — Press `r` to search again with different terms
- **Non-interactive mode** — Use `-b` or `--non-interactive` flag to skip all prompts and auto-search

### 4. Config File (Optional)

Create `matcha.yaml` in the project directory and/or `~/.matcha/settings.yaml`
(and optionally pass `--config PATH` for one specific file). Files are
deep-merged in order of precedence — **`~/.matcha/settings.yaml` >
`./matcha.yaml` > `--config PATH`** — so the user-level file always wins and
you only need to write the keys you want to override:

```yaml
search:
  query: Platform Engineer
  location: Pune
  days: 7
  max_pages: 2            # search-result pages per query (default 2)
ai:
  enabled: true
  top_n: 30               # jobs considered for the AI re-scoring pass
  timeout: 60             # seconds per AI call
  model_best: ""          # scoring / profile extraction (default per provider)
  model_fast: ""          # query gen / title suggestion (default per provider)
  max_calls: 60           # AI budget guard per run
  cache_ttl: 0            # AI disk cache TTL in seconds (0 = off; 86400 = 24h)
  verdict_k: 5            # top-K AI go/no-go verdicts (0 = off)
scrapers:
  serpapi: false          # Google Jobs — the key itself is set via `matcha --configure`
  indeed_domain: in.indeed.com
  career_sites: false     # 200+ employer career boards via DDGS (opt-in)
  linkedin_backend: guest # optional: force a source backend (see env vars)
enrichment:
  enabled: true           # top-N detail enrichment after ranking
  top_n: 30               # how many ranked jobs to enrich
  timeout: 30             # seconds per job-detail call
  max_workers: 5          # parallel detail fetches (capped at 5)
filters:
  days: 7                 # job-age window — the central filter is the FINAL authority
  strict_age: false       # drop unknown-age jobs instead of tagging [age?]
  min_must_matches: 1     # must-have skills required in title+description
  soft_must_skills: false # keep below-threshold jobs, flagged for a rank cap
  remote: false           # remote-only mode
  min_salary: 0           # LPA floor (0 = off)
  drop_unknown_salary: false  # drop jobs without a parseable salary
ranking:
  normalize_scores: false # stretch a flat score distribution onto [5, 100]
sources:
  rss:
    feeds:                # optional RSS feeds as an extra source
      - https://remoteok.com/remote-jobs.rss
```

**Filters** (Phase 2): after dedup, every job is normalized (`listed_epoch`,
`salary_int` LPA, synonym-canonicalized `city`/`region`, `remote_ok`) and then
run through a **central filter pipeline** in a fixed order — quality → age →
must-skills → location → salary — each reporting exactly how many jobs it
cut. The TUI shows the filter summary before results
(`Filtered: 96 kept (age −142 · must −21 · loc −33 …)`) and tags uncertain
provenance (`[age?]` / `[salary?]`). The quality gate also drops
listing-page/nav noise leaked by snippet fallbacks ("Link to naukri.com",
"It Jobs", "Developer Tcs Jobs" — titles ending in "Jobs" or matching
boilerplate), and when the location stage excludes remote jobs it prints an
actionable hint (`set filters.remote: true or remote_preference: remote`).
Must-have skills, a salary floor, and a remote preference can be set in
`~/.matcha/profile.json` (`must_have_skills`, `min_salary`,
`remote_preference`) or via `filters:` above; `matcha --days N` overrides
the age window for one run.

**Ranking** (Phase 4): the heuristic scorer is now **confidence-weighted** —
the skills/keyword dimensions scale by data richness (`data_quality`:
`full` 1.0 · `partial` 0.85 · `snippet` 0.7), so a match on an empty field
contributes ~0 and **full-data jobs outrank snippet-guesses**. Fresh postings
(`listed_epoch`) earn up to +5, remote/hybrid jobs matching your
`remote_preference` earn +3, and each matched must-have skill earns +2 (cap
+6). Soft-mode jobs (`soft_must_skills: true` that missed the must-skill
bar) are capped at 45 so they never outrank hard matches. The **AI pass runs
only on enriched candidates** (`data_quality` full/partial or a substantial
description), and a flatline guard warns when the top-decile score spread is
near zero (`ranking.normalize_scores: true` stretches it onto [5, 100]). The
results table shows provenance tags next to each score: `[full]` / `[partial]`
/ `[snippet]` plus `[age?]` / `[salary?]`. **Calibration:** the skill ratio
saturates (a job covering ~10 distinct skills earns full marks even with a
50+ skill profile) and the title dimension scores how much of the *job
title* the profile covers — so a strong title match is never diluted by a
long headline. With AI on, the top `verdict_k` (default 5) enriched jobs
also get a go/no-go verdict ("would you actually apply?") rendered in the
detail panel and surfaced in `search --json` as a per-job `verdict` object.

**Enrichment** (Phase 1): after ranking, the top `top_n` jobs get full
descriptions + apply URLs via OpenCLI job-detail (`opencli linkedin
job-detail` / `opencli indeed job`), when you've opted in via `matcha
--configure` and the browser bridge is healthy. When the bridge is down,
LinkedIn postings fall back to the zero-config Jina Reader
(`https://r.jina.ai/`, capped at 10 jobs/batch); `data_quality` stays
`partial` and is tagged `enrich_source: jina`.

### 5b. Hardening & Reliability (Phase 7)

**Circuit breakers** — per-source state lives in `~/.matcha/source_state.json`
(`ok_streak` / `fail_streak` / `last_ok` / `cooldown_until`). Three
consecutive search failures open a **30-minute cooldown**: the source is
skipped with a visible note instead of retried every run; any success resets
it. `matcha doctor --json` reports a `circuit` key per source plus an `ai`
entry (`provider`, `key_set`, `model_best`, `model_fast`, `available`) so
AI setup is verifiable in the same report.

**GitHub profile enrichment** — `matcha github enrich` reads `gh api user` +
`user/repos` (read-only; never `gh auth status`) and appends language- and
topic-derived skill suggestions plus `github_username` to `profile.json`.
Requires `gh` installed + authenticated; degrades gracefully otherwise.

**RSS feeds** — `sources.rss.feeds` (in `matcha.yaml` or
`~/.matcha/settings.yaml`) adds company/job-board feeds as an extra source:

```yaml
sources:
  rss:
    feeds:
      - https://careers.example.com/jobs.rss
      - https://weworkremotely.com/categories/remote-devops-sysadmin-jobs.rss
```

**Career sites** — `scrapers.career_sites: true` adds the 200+ employer-board
source (DDGS `site:` discovery) to searches. Off by default so zero-config
runs stay fast; `matcha doctor` reports `off` until you enable it.

**Private-file discipline** — all config/profile/secret writes are atomic +
owner-only (0600 files, 0700 dirs), reads refuse symlinks component-wise and
never create files, and config reads are size-capped (1MB).

### 5. Agent & Automation Surface (Phase 6)

The same pipeline (profile → search → filter → rank → enrich) that drives
the TUI is available headlessly — the identical `run_search` path — so
agents, cron, and scripts can drive Matcha without a terminal session.

```bash
# Ranked search as structured JSON (pipe to jq, feed an agent)
matcha search -q "Platform Engineer" -l "Pune" -d 7 --json

# Only-NEW jobs since the last watch (diff vs seen_urls, marks seen)
matcha watch -q "Platform Engineer" -l "Pune" -d 7 --json

# Write the result document to a file (watch defaults to ~/.matcha/latest.json)
matcha search -q "Kubernetes SRE" --output ~/.matcha/latest.json

# Install the bilingual agent skill (SKILL.md) so Claude/OpenCode can drive Matcha
matcha skill --install          # → ~/.agents/skills/matcha + ~/.claude/skills/matcha
matcha skill --uninstall

# Optional MCP server (requires: pip install -e '.[agent]')
matcha mcp
```

Each JSON document carries `{command, generated_at, query, location, days,
ai_used, ai_budget_used, source_counts, source_errors, filter_summary,
filter_notes, found_count, enriched_count, verdict_count, jobs[]}` — every
job is its full search row plus `match_score` and `reasons` (and a `verdict`
`{recommend, line}` object for verdict-scored jobs). `watch` adds `new_count`, `seen_count`,
`new_jobs`, and `seen_urls_total` (new-vs-seen tracked in
`~/.matcha/jobs.db` → `seen_urls`; only `watch` consumes it, so interactive
runs never pollute the newness signal). `search`/`watch` need a saved profile
(run `matcha` once interactively first); `--no-enrich`/`--no-ai-queries`
trim the pipeline for fast scripted runs.

### Example Detail View

```
╭─────────────────────────── Job Details ───────────────────────────╮
│ Platform Engineer @ Barclays                                      │
│ Company: Barclays                                                 │
│ Salary: ₹28–40L                                                   │
│ Workplace: Hybrid                                                 │
│ Posted: 3 days ago                                                │
│ Applicants: 25 applicants                                         │
│ Location: Pune, India                                             │
│ Source: Indeed                                                    │
│ Apply URL: https://in.indeed.com/viewjob?jk=b52083124e35dc8d      │
│ Match Score: 82%                                                  │
│ Verdict: ✓ Recommend — strong skills overlap, right seniority     │
│                                                                   │
│ Why this matches:                                                 │
│   • Job title matches profile: platform, engineer                 │
│   • Skill match: AWS, Docker, Terraform, CI/CD, Linux             │
│   • Seniority match: mid                                          │
│   • Location match                                                │
│                                                                   │
│ Description:                                                      │
│ Barclays is hiring a Platform Engineer for our Pune office...     │
╰───────────────────────────────────────────────────────────────────╯
```

---

## Data Sources

| Source | Method | Results | Requires |
|--------|--------|---------|----------|
| **LinkedIn** | `opencli` (your logged-in Chrome, richest) ▸ guest API fallback | 25–100 (OpenCLI) / ~10 (guest) | OpenCLI + consent (opt-in) |
| **Indeed** | `opencli` (browser; US index) ▸ `ddgs` fallback on py3.14 | 5–25 listings | OpenCLI + consent (opt-in) |
| **RemoteOK** | Public JSON API filtered by keyword matching | ~8 listings | Nothing |
| **Naukri** | DDGS `site:naukri.com` discovery → real `job-listings-*` pages parsed for description/salary/skills (embedded JSON first, Jina render fallback); `ddgs` snippet fallback | 6–44 listings | Nothing |
| **Web Search** | Exa semantic search (via mcporter, when configured) ▸ `ddgs` API with targeted `site:` queries | 10–30 listings | mcporter (optional) |
| **RSS** | `feedparser` over your configured company/job-board feeds | feed-dependent | Nothing (add feeds in settings) |
| **Google Jobs** | SerpAPI `google_jobs` engine (optional) | Rich listings | SerpAPI key |
| **Career Sites** | DDGS `site:` discovery over 200+ employer career boards | variable | Nothing (opt-in: `scrapers.career_sites: true`) |

---

## Relevance Scoring

### Heuristic Pass (all jobs)

| Dimension | Max | Method |
|-----------|-----|--------|
| Skills Match | 35% | Ratio of profile skills found in job title + description |
| Title Match | 25% | Token overlap between job title and profile title/headline |
| Seniority | 15% | Level alignment (entry/mid/senior) based on experience |
| Location | 15% | City/region match; remote bonus |
| Keyword Match | 10% | Profile keywords found in job posting text |
| Recency / workplace / must-skills | +11 | Fresh posting, remote-preference agreement, must-have coverage |

Text-derived dimensions (skills, keywords) are scaled by **data confidence**
(`full` 1.0 · `partial` 0.85 · `snippet` 0.7), so empty fields contribute ~0;
soft-mode must-skill misses are capped at 45. Score clamped to 0–100 (floor 5).

### AI Pass (top N = 30, enriched candidates only)

Only jobs with real descriptions (`data_quality` full/partial or a substantial
text) are re-scored by an LLM using a structured prompt covering:
- **Skills match (40%)** — Honest assessment of skill overlap and missing requirements
- **Title/role alignment (25%)** — Career trajectory fit, not just keyword match
- **Experience fit (20%)** — Appropriate seniority level
- **Location fit (15%)** — Geography preference

The prompt is tuned to be **critical** — scores of 80+ are reserved for strong alignment. No job receives a perfect 100.

---

## Optional: AI Integration

Matcha's AI brain is a **provider-agnostic OpenAI-compatible REST client**
(`POST {base_url}/chat/completions`) — run `matcha --configure` to pick a
provider preset, or set env vars directly (see the [Environment
Variables](#environment-variables) table: `MINIMAX` key · `AI_API_URL` ·
`AI_MODEL` best-tier · `AI_MODEL_FAST` fast-tier · `AI_PROVIDER`). Keys are
stored encrypted at rest via fernet (`~/.matcha/*.enc`), never plaintext
and never in the OS keychain.

| Preset | Default base URL | Default best / fast model |
|---|---|---|
| **Groq** (free tier) | `https://api.groq.com/openai/v1` | `openai/gpt-oss-120b` / `openai/gpt-oss-20b` |
| **Kilo Gateway** (default) | `https://api.kilo.ai/api/gateway` | `kilo-auto/small` (both tiers) |
| **OpenRouter** | `https://openrouter.ai/api/v1` | `meta-llama/llama-3.3-70b-instruct:free` / `meta-llama/llama-3.1-8b-instruct:free` |
| **OpenAI / compatible** | `https://api.openai.com/v1` | `gpt-4o-mini` (both tiers) |
| **Local** (Ollama / LM Studio) | `http://localhost:11434/v1` | **no API key needed** |

Every slot resolves **env var → config.json → settings.yaml → preset
default** (the wizard writes config.json; the `MINIMAX` env var wins over
everything else).

**Model tiers** — `model_fast` runs cheap high-volume tasks (query expansion,
title suggestion); `model_best` runs scoring and resume extraction. **Budget
guard** — `ai.max_calls` (default 60) caps AI calls per run; when exhausted,
remaining jobs keep heuristic scores and the TUI prints
`AI budget: N/M used (R left)`. **Disk cache** — set `ai.cache_ttl` (e.g.
`86400`) to cache AI results in `~/.matcha/ai_cache.sqlite`, keyed by
task + model + prompt, so re-runs and `matcha watch` don't re-pay.

With AI enabled:
- Resume PDFs are parsed entirely by AI — extracts name, skills (30+), title, experience, and summary in one pass
- Search queries are expanded to 3–5 diverse variants targeting adjacent roles
- Top N (default 30) **enriched** jobs are re-scored by AI for more accurate relevance ranking
- Job titles are suggested from your skill set (no hardcoded mappings)

---

## Project Structure

```
matcha/
├── pyproject.toml           # Packaging (console script `matcha`) + ruff/bandit config
├── requirements.txt         # Python dependencies
├── Makefile                 # Dev tasks (venv, test, lint, build)
├── kilo.md                  # Dev session log / architecture notes
└── src/
    └── matcha/
        ├── __init__.py
        ├── main.py          # CLI entry point, orchestration, UI, `doctor`, `--days`
        ├── profile.py       # Profile ingestion (PDF, LinkedIn, manual)
        ├── matcher.py       # Confidence-weighted relevance scoring + AI wrapper
        ├── normalization.py # Canonical jobs: listed_epoch, salary_int, city, remote_ok
        ├── filters.py       # Central filter pipeline + provenance tags
        ├── agent_reach_io.py  # Thin adapter to `agent-reach` (doctor snapshot, gh)
        ├── ai.py            # AI provider client (presets, model tiers, budget guard)
        ├── ai_cache.py      # AI result disk cache (SQLite, opt-in TTL)
        ├── track.py         # New-vs-seen URL tracking (`matcha watch`)
        ├── mcp_server.py    # Optional MCP server (matcha_status, matcha_search)
        ├── skill/           # Bundled agent SKILL.md (bilingual) + installer
        ├── config.py        # Persistent config and profile storage
        ├── models.py        # Pydantic v2 data models + ScraperResult
        ├── settings.py      # YAML config loader
        ├── actions.py       # Saved-job actions
        ├── errors.py        # Typed exception hierarchy (ConfigSecurityError)
        ├── probe.py         # Upstream CLI probing (used by doctor)
        ├── doctor.py        # `matcha doctor` health reports
        ├── utils.py         # Credential scrubbing, atomic writes, symlink rejection
        └── sources/         # Job sources (one module + Source subclass each)
            ├── __init__.py  # ALL_SOURCES registry (8 sources incl. rss)
            ├── base.py      # Source base class (backends, check(), search())
            ├── breaker.py   # Circuit breakers (persisted source_state.json)
            ├── constants.py
            ├── utils.py     # Resilient HTTP client, rate limiter, cache
            ├── enrichment.py  # Top-N detail enrichment (OpenCLI + Jina fallback)
            ├── rss.py       # RSS source (feedparser, sources.rss.feeds)
            ├── backends/    # opencli.py · mcporter.py · exa.py (browser/MCP backends)
            ├── indeed.py    # Indeed: opencli ▸ html ▸ ddgs
            ├── linkedin.py  # LinkedIn: opencli ▸ guest-api
            ├── naukri.py    # Naukri job-page parse (job-page ▸ ddgs)
            ├── remoteok.py  # RemoteOK public JSON API
            ├── serpapi_jobs.py  # Google Jobs via SerpAPI (optional)
            ├── web_search.py    # Exa ▸ ddgs with targeted site: queries
            └── career_sites.py  # 200+ employer boards via ddgs (default off)
```

---

## Engineering Highlights

- **AI-native profile extraction** — No keyword lists, no hardcoded patterns, no fallback parsing. AI handles all skill/title extraction from resumes.
- **Parallel execution** — `ThreadPoolExecutor` dispatches 30+ scraper tasks concurrently, reducing total search time to ~30 seconds
- **Resilient scrapers** — Each scraper is isolated in a try/except block; a single source failure never blocks others
- **Smart deduplication** — Cross-source duplicate detection using normalized title+company keys
- **Tracking URL resolution** — Indeed `rc/clk` and `pagead/clk` URLs decoded to clean `viewjob` URLs via job key extraction or HTTP redirect following
- **AI prompt engineering** — Structured JSON output with temperature 0.1 for reliable parsing; fallback regex extraction for malformed responses
- **Zero API key lock-in** — Core functionality works without any paid API keys
- **HTTP caching** — requests-cache with SQLite backend, 30-min TTL, avoids re-scraping identical queries
- **Rate limiting** — Per-domain token bucket limits prevent IP bans
- **Circuit breakers** — a repeatedly failing source is skipped during its 30-min cooldown instead of retried every run
- **Private-file discipline** — atomic owner-only writes, component-wise symlink rejection, reads that never create files

---

## License

MIT
