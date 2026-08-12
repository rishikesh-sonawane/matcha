# Matcha 🍵

> **Your next role, perfectly brewed.**
>
> A multi-source job aggregator with AI-powered relevance ranking. Tell it
> about yourself **once** — it searches LinkedIn, Indeed, Naukri, RemoteOK,
> web search (and more) in parallel, then ranks every listing against your
> profile and shows you only the jobs actually worth your time.

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)]()
[![Rich TUI](https://img.shields.io/badge/built%20with-Rich-ffd700)]()
[![AI Matching](https://img.shields.io/badge/feature-AI%20Scoring-8a2be2)]()
[![License: MIT](https://img.shields.io/badge/license-MIT-green)]()

**No API keys required for core search.** AI ranking is a free optional
upgrade. 200–500+ unique listings per search, ~30 seconds.

- 📖 Full documentation: [wiki](https://github.com/rishikesh-sonawane/matcha/wiki)
- 🚀 Project site: [matcha site](https://rishikesh-sonawane.github.io/matcha/)
- ⚡ TL;DR: the [5-command quickstart](QUICKSTART.md) takes ~2 minutes.

---

## Table of Contents

1. [What Matcha does](#what-matcha-does)
2. [The 30-second version](#the-30-second-version)
3. [Step-by-step guide](#step-by-step-guide)
   - [1. Install](#1-install)
   - [2. Create your profile](#2-create-your-profile)
   - [3. Enable AI ranking (recommended)](#3-enable-ai-ranking-recommended)
   - [4. Check that everything works](#4-check-that-everything-works)
   - [5. Run your first search](#5-run-your-first-search)
   - [6. Use it headless (scripts, agents, cron)](#6-use-it-headless-scripts-agents-cron)
4. [Interactive TUI cheat-sheet](#interactive-tui-cheat-sheet)
5. [Command reference](#command-reference)
6. [Configuration](#configuration)
7. [Where Matcha keeps its files](#where-matcha-keeps-its-files)
8. [Data sources](#data-sources)
9. [How ranking works](#how-ranking-works)
10. [Project structure](#project-structure)
11. [FAQ & troubleshooting](#faq--troubleshooting)

---

## What Matcha does

Job boards show you **every** posting matching a keyword. Matcha shows you
only the ones that actually **fit your profile** — your skills, experience
level, location, and career trajectory.

```
profile.json ──► AI query expansion ──► 6 scrapers in parallel ──► 200-500 jobs
                    │                                                        │
                    ▼                                                        ▼
        heuristic + AI relevance scoring ◄──────────── normalize + filter ──┘
                    │
                    ▼
        ranked, color-coded terminal UI with apply links
```

**The two-pass ranking engine:**
1. **Heuristic pass** — every job scored on 5 dimensions (skills, title,
   seniority, location, keywords) with recency/remote/must-skill bonuses.
   Instant, even for 500+ jobs.
2. **AI pass** — the top ~30 jobs with real descriptions are re-scored by an
   LLM that understands role semantics, skill adjacency, and career
   trajectory (optional — free tier providers available).

---

## The 30-second version

```bash
python3 -m venv venv
venv/bin/pip install -r requirements.txt
venv/bin/pip install -e .
venv/bin/matcha                    # enter profile → search → browse
export MINIMAX="your-api-key"      # optional: turn on AI ranking
venv/bin/matcha doctor             # verify sources + AI are healthy
```

That's it. Everything after that is optional tuning.

---

## Step-by-step guide

### 1. Install

**Requirements:** Python 3.10+ (3.14 works in a venv), macOS or Linux,
~10 minutes.

```bash
git clone https://github.com/rishikesh-sonawane/matcha.git
cd matcha
python3 -m venv venv
venv/bin/pip install -r requirements.txt
venv/bin/pip install -e .
```

The `matcha` command is installed into the venv. **No environment variables
are required** to install or run.

> **Why a venv?** It avoids urllib3 v2 + macOS LibreSSL segfaults on
> Homebrew Python, and keeps dependencies in one place. If you see
> `Defaulting to user installation...`, recreate it:
> `rm -rf venv && python3 -m venv venv`.
>
> **Tip:** `make venv` does the above plus dev tooling (ruff, bandit,
> pre-commit); `make run` starts Matcha.

Verify the install:

```bash
venv/bin/matcha --help
```

### 2. Create your profile

```bash
venv/bin/matcha
```

The first run walks you through profile entry — pick **one** of:

| Method | How |
|---|---|
| **PDF resume** | Paste the path to your resume — AI extracts name, title, skills, experience |
| **LinkedIn URL** | Paste a public profile URL (DuckDuckGo fallback if LinkedIn blocks us) |
| **Manual** | Type every field yourself — always works, full control |

Your profile is saved to `~/.matcha/profile.json` and reused on every later
run. Change it any time with `venv/bin/matcha --new-profile`.

### 3. Enable AI ranking (recommended)

AI turns on the moment a key is available. Two ways:

**Fastest — set the env var** (put it in `~/.zshrc` / `~/.bashrc`):

```bash
export MINIMAX="your-api-key"
venv/bin/matcha        # banner now shows "(AI)"
```

**Or use the setup wizard** — stores the key encrypted at rest
(`~/.matcha/*.enc`, no OS keychain prompts) and walks through provider,
SerpAPI, and OpenCLI:

```bash
venv/bin/matcha --configure
```

**Free AI providers** (all work with no paid key):

| Provider | Set | Model (best / fast) |
|---|---|---|
| **Groq** | free API key | `openai/gpt-oss-120b` / `openai/gpt-oss-20b` |
| **Kilo Gateway** (default) | free API key | `kilo-auto/small` |
| **OpenRouter** | free-tier key | `llama-3.3-70b-instruct:free` / `llama-3.1-8b:free` |
| **Local** (Ollama / LM Studio) | **no key** | `AI_PROVIDER=local` |

Without AI, Matcha still works — ranking is heuristic-only.

### 4. Check that everything works

```bash
venv/bin/matcha doctor          # human-readable per-source health
venv/bin/matcha doctor --json   # machine-readable (for scripts)
```

A healthy report shows `ok` for the zero-config sources (RemoteOK, Naukri,
Web Search, …) **and** an **AI matching** line:

- `ok` — AI fully wired (provider + key set)
- `off` — heuristic-only (fine; add a key when you want AI)
- `warn` — partial setup (e.g. a key with no provider)

### 5. Run your first search

```bash
venv/bin/matcha
```

It asks for a query, location (blank = remote), and how many days back.
Then it searches all sources in parallel, filters, ranks, and opens the
interactive results table:

```
                  Matching Jobs (page 1/21) (AI)
 #     Title                    Company          Source      Match
───────────────────────────────────────────────────────────────────
 1     AWS Devops Engineer      Capgemini        LinkedIn    92.0%
 2     Software Engineer II     Microsoft        Indeed      92.0%
 3     DevOps Engineer-III      ADCI             Indeed      92.0%
...
↑↓ navigate  Enter detail  s save/unsave  o open  n/p page  l saved  r re-run  q quit
```

See the [TUI cheat-sheet](#interactive-tui-cheat-sheet) for every key.

### 6. Use it headless (scripts, agents, cron)

The exact same pipeline (`profile → search → filter → rank → enrich`) is
available without a terminal session:

```bash
# Ranked search as JSON (pipe to jq, feed an agent)
venv/bin/matcha search -q "Platform Engineer" -l Pune -d 7 --json

# Only-NEW jobs since the last watch (diffs against seen_urls)
venv/bin/matcha watch -q "Platform Engineer" -l Pune -d 7 --json

# Write the result document to a file
venv/bin/matcha search -q "Kubernetes SRE" --output ~/.matcha/latest.json

# Automate fully with a saved profile:
venv/bin/matcha --non-interactive
```

`search`/`watch` need a saved profile (run `matcha` once first). Each JSON
document carries `{command, query, location, days, ai_used, source_counts,
filter_summary, found_count, jobs[]}` — every job with `match_score`,
`reasons`, `apply_url`, salary, and provenance tags.

**Agent automation:** install the bundled skill so Claude / OpenCode can
drive Matcha:

```bash
venv/bin/matcha skill --install   # → ~/.agents/skills/matcha + ~/.claude/skills/matcha
venv/bin/matcha skill --uninstall # remove it again
```

Or run the optional MCP server (`pip install -e '.[agent]'`, then
`venv/bin/matcha mcp`) exposing `matcha_status` and `matcha_search`.

---

## Interactive TUI cheat-sheet

| Key | Action |
|---|---|
| `↑` / `↓` | Navigate results |
| `Enter` | Job detail panel (URL, match reasons, description) |
| `s` | Save / unsave the job (persisted in `~/.matcha/jobs.db`) |
| `o` | Open the apply URL in your browser |
| `n` / `p` | Next / previous page |
| `l` | View saved jobs |
| `h` | Toggle showing already-seen jobs |
| `r` | Re-run the search with different terms |
| `q` | Quit |

Already-seen jobs are hidden on later runs by default — saving a job
retires it from future lists. When everything was already seen, Matcha
tells you **"No new jobs"** instead of replaying the same list.

---

## Command reference

```text
matcha                                    # interactive TUI (profile → search → browse)
matcha --configure                        # setup wizard: AI provider+key, SerpAPI, OpenCLI
matcha --new-profile                      # re-enter your profile from scratch (-n)
matcha --non-interactive                  # skip all prompts (-b) — needs a saved profile
matcha --days N                           # age window for one run (also filters.days)
matcha --config PATH                      # load a specific YAML settings file

matcha doctor [--json]                    # per-source health + AI + backends + circuits
matcha search -q Q -l LOC -d N [--json] [--output FILE] [--top N] [--no-ai-queries] [--no-enrich]
matcha watch  -q Q -l LOC -d N [--json] [--output FILE] [--top N] [--no-ai-queries] [--no-enrich] [--no-mark-seen]
matcha skill --install [--dest PATH]      # install the agent skill (also --uninstall)
matcha mcp                                # optional MCP server (pip install -e '.[agent]')
matcha github enrich                      # merge GitHub signals into profile.json (needs gh)
```

`doctor`, `skill`, `mcp`, `github` work without a profile; `search`/`watch`
need one.

---

## Configuration

### Environment variables

**None are required.** Set these only to enable optional features:

| Variable | Purpose | Default |
|---|---|---|
| `MINIMAX` | **AI API key** — the single switch that turns AI on | unset → heuristic-only |
| `AI_PROVIDER` | `groq` \| `kilo` \| `openrouter` \| `openai` \| `local` | `kilo` |
| `AI_API_URL` | OpenAI-compatible base URL override | provider preset |
| `AI_MODEL` | Best-tier model (scoring, profile extraction) | provider preset |
| `AI_MODEL_FAST` | Fast-tier model (query expansion, titles) | provider preset |
| `GH_TOKEN` / `GITHUB_TOKEN` | Auth for `matcha github enrich` | `gh` hosts.yml |
| `<SOURCE>_BACKEND` | Force a backend, e.g. `LINKEDIN_BACKEND=guest` | ordered fallback |
| `MCPORTER_CONFIG` | mcporter config path (Exa web-search backend) | auto-discovered |
| `MATCHA_HTTP_CACHE_TTL` | HTTP cache TTL in seconds (0 = fresh every run) | `0` (off) |
| `MATCHA_AI_CACHE` | AI disk-cache SQLite path | `~/.matcha/ai_cache.sqlite` |

Resolution order for every AI slot: **env var → `~/.matcha/config.json` →
`~/.matcha/settings.yaml` → provider default**.

### YAML settings (optional)

Create `matcha.yaml` in the project directory and/or
`~/.matcha/settings.yaml` (or pass `--config PATH`). Files deep-merge in
precedence: **`~/.matcha/settings.yaml` > `./matcha.yaml` > `--config PATH`**.
You only need to write the keys you want to override:

```yaml
search:
  query: Platform Engineer
  location: Pune
  days: 7
  max_pages: 2
ai:
  enabled: true
  top_n: 30               # jobs considered for the AI re-scoring pass
  timeout: 60
  max_calls: 60           # AI budget guard per run
  cache_ttl: 0            # AI disk cache TTL (0 = off; 86400 = 24h)
scrapers:
  serpapi: false          # Google Jobs — key set via `matcha --configure`
  career_sites: false     # 200+ employer boards via DDGS (opt-in)
  indeed_domain: in.indeed.com
enrichment:
  enabled: true           # top-N detail enrichment after ranking
  top_n: 30
filters:
  days: 7
  strict_age: false       # drop unknown-age jobs instead of tagging [age?]
  remote: false           # remote-only mode
  min_salary: 0           # LPA floor (0 = off)
  strict_location: false  # drop no-location jobs instead of tagging [loc?]
ranking:
  normalize_scores: false # stretch a flat score distribution onto [5, 100]
sources:
  rss:
    feeds:                # optional RSS feeds as an extra source
      - https://remoteok.com/remote-jobs.rss
```

**Filter pipeline** (runs on every job, in order): quality → age →
must-have skills → location → salary. The TUI shows exactly how many jobs
each stage cut (`Filtered: 96 kept (age −142 · must −21 · loc −33 …)`) and
tags uncertain provenance (`[age?]` / `[salary?]` / `[loc?]`).

---

## Where Matcha keeps its files

All state lives under `~/.matcha/`:

| Path | Purpose |
|---|---|
| `profile.json` | Your profile (skills, title, experience, must_have_skills) |
| `config.json` | Non-secret config + last query/location/days |
| `settings.yaml` | Optional YAML overrides |
| `fernet.key` + `*.enc` | Secrets encrypted at rest (no OS keychain) |
| `source_state.json` | Per-source circuit-breaker state |
| `jobs.db` | Saved jobs + `seen_urls` (powers `matcha watch`) |
| `ai_cache.sqlite` | Opt-in AI disk cache |
| `logs/matcha.log` | Rotating debug log (5 MB × 3) |

---

## Data sources

| Source | Method | Requires |
|---|---|---|
| **LinkedIn** | OpenCLI (your logged-in Chrome) ▸ guest API | OpenCLI + consent (opt-in) |
| **Indeed** | OpenCLI ▸ DDGS fallback | OpenCLI + consent (opt-in) |
| **RemoteOK** | Public JSON API | nothing |
| **Naukri** | DDGS `site:` discovery → real `job-listings-*` pages | nothing |
| **Web Search** | Exa semantic (mcporter, optional) ▸ DDGS `site:` queries | nothing (mcporter optional) |
| **RSS** | `feedparser` over your configured feeds | nothing (add feeds in settings) |
| **Google Jobs** | SerpAPI `google_jobs` engine | SerpAPI key (free tier) |
| **Career Sites** | DDGS discovery over 200+ employer boards | nothing (opt-in) |

---

## How ranking works

**Heuristic pass (all jobs):**

| Dimension | Weight |
|---|---|
| Skills match | 35% |
| Title match | 25% |
| Seniority | 15% |
| Location | 15% |
| Keyword match | 10% |
| Recency / remote / must-skills | +11 bonus |

Text-derived dimensions scale by data confidence (`full` 1.0 · `partial`
0.85 · `snippet` 0.7) — full descriptions outrank snippet guesses.

**AI pass (top ~30 enriched jobs):** skills 40% · title/role 25% ·
experience 20% · location 15%. The prompt is tuned to be critical — 80+
is reserved for genuinely strong matches; nothing scores 100.

---

## Project structure

```
matcha/
├── pyproject.toml           # Packaging (console script `matcha`) + ruff/bandit config
├── requirements.txt         # Python dependencies
├── Makefile                 # Dev tasks (venv, test, lint, build)
└── src/
    └── matcha/
        ├── main.py          # CLI entry point, orchestration, TUI, doctor
        ├── profile.py       # Profile ingestion (PDF, LinkedIn, manual)
        ├── matcher.py       # Confidence-weighted relevance scoring
        ├── normalization.py # Canonical jobs: listed_epoch, salary_int, city
        ├── filters.py       # Central filter pipeline + provenance tags
        ├── ai.py            # AI provider client (presets, model tiers, budget guard)
        ├── ai_cache.py      # AI result disk cache (SQLite, opt-in TTL)
        ├── track.py         # New-vs-seen URL tracking (`matcha watch`)
        ├── mcp_server.py    # Optional MCP server (matcha_status, matcha_search)
        ├── skill/           # Bundled agent SKILL.md + installer
        ├── config.py        # Persistent config and profile storage
        ├── models.py        # Pydantic v2 data models
        ├── settings.py      # YAML config loader
        ├── actions.py       # Saved-job actions
        ├── doctor.py        # `matcha doctor` health reports
        ├── probe.py         # Upstream CLI probing
        └── sources/         # Job sources (one module + Source subclass each)
            ├── base.py      # Source base class (backends, check(), search())
            ├── breaker.py   # Circuit breakers (persisted state)
            ├── constants.py
            ├── utils.py     # Resilient HTTP client, rate limiter, cache
            ├── enrichment.py# Top-N detail enrichment (OpenCLI + Jina fallback)
            ├── rss.py       # RSS source
            ├── backends/    # opencli.py · mcporter.py · exa.py
            ├── indeed.py · linkedin.py · naukri.py · remoteok.py
            ├── serpapi_jobs.py · web_search.py · career_sites.py
```

---

## FAQ & troubleshooting

**Q: Do I need an API key to use Matcha?**
No. Core search works with zero keys. AI ranking and Google Jobs (SerpAPI)
are optional upgrades.

**Q: Matcha returned 0 jobs / a source errored.**
Run `matcha doctor` — it shows each source's health and active backend.
Sources fail independently; a failing source never blocks the others.
Retry with a simpler or adjacent query.

**Q: How do I start over?**
`venv/bin/matcha --new-profile` re-enters your profile.
`rm -rf ~/.matcha` wipes all state (profile, config, saved jobs).

**Q: AI is `warn` or `off` in doctor.**
Set `export MINIMAX="your-key"` or run `matcha --configure`. See
[Enable AI ranking](#3-enable-ai-ranking-recommended).

**Q: Jobs keep reappearing.**
Already-seen jobs are hidden by default; press `h` to see them. `watch`
tracks newness separately in `~/.matcha/jobs.db`.

**Q: Can Matcha apply to jobs for me?**
No — Matcha opens the apply page. It's search + enrichment, never
auto-apply.

**Q: Where's the log?**
`~/.matcha/logs/matcha.log` (rotating, 5 MB × 3). Check it when a source
misbehaves.

---

## License

MIT
