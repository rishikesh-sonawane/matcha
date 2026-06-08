# Matcha 🍵

> **Matcha! Your next role, perfectly brewed.**
>
> Multi-source job aggregator with AI-powered relevance ranking. Enter your profile once — get ranked, personalized job matches from across the web.

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)]()
[![Rich TUI](https://img.shields.io/badge/built%20with-Rich-ffd700)]()
[![AI Matching](https://img.shields.io/badge/feature-AI%20Scoring-8a2be2)]()

---

## Why This Exists

Job boards show you **every** posting matching a keyword. This tool shows you only the ones that actually **fit your profile** — your skills, experience level, location, and career trajectory. It aggregates jobs from 5+ sources in parallel, scores them against your profile using a two-pass heuristic + AI engine, and presents them in a beautiful terminal UI with ranked relevance.

---

## Features

**Multi-Source Aggregation** — Searches LinkedIn, Indeed, Naukri, RemoteOK, and web search results simultaneously. Optionally integrates Google Jobs via SerpAPI. 30+ parallel requests across diverse queries yield **200–500+ unique listings** per search.

**Two-Pass Relevance Engine**
1. **Heuristic pass** — Fast token-based scoring across 5 dimensions (title, skills, keywords, seniority, location) on every job — completes instantly even for 500+ listings.
2. **AI pass** — Top candidates re-scored by an LLM that understands role semantics, skill adjacency, and career trajectory. Critical prompt tuning ensures honest, discriminating scores.

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
                         │           main.py (CLI)              │
                         │  Profile → Query Expansion → Search  │
                         │  → Two-Pass Ranking → Display        │
                         └───────┬──────────┬──────────┬────────┘
                                 │          │          │
                    ┌────────────┘          │          └────────────┐
                    ▼                       ▼                      ▼
           ┌────────────────┐    ┌──────────────────┐    ┌──────────────────┐
           │  Profile Layer │    │  Relevance Layer  │    │  Scraper Layer   │
           │  profile.py    │    │  matcher.py       │    │  scrapers/       │
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
5. **First-Pass Ranking** — Heuristic scorer evaluates all jobs in O(n) using token overlap matching
6. **Second-Pass Ranking** — Top 15 candidates re-scored by LLM with structured JSON output
7. **Display** — Paginated table with color-coded match scores → interactive detail view

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
venv/bin/python3 main.py
```

This creates a virtual environment, installs dependencies, and runs the app — without needing to manually activate the venv.

### Fresh Setup

```bash
git clone https://github.com/yourusername/matcha.git
cd matcha
python3 -m venv venv
venv/bin/pip install -r requirements.txt
venv/bin/python3 main.py
```

> **Note:** A virtual environment is required — it avoids urllib3 v2 + macOS LibreSSL segfaults on Homebrew Python, and ensures dependencies install into the correct location. If you see `Defaulting to user installation because normal site-packages is not writeable`, the venv is not activated or the symlinks are broken — recreate it with `rm -rf venv && python3 -m venv venv`.

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
| `python-dotenv` | Environment variable management |
| `urllib3<2` | Pinned to v1 to prevent LibreSSL segfault on macOS |

---

## Usage

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
- **Job details** — Full URL, match reasons, and description
- **Save jobs** — Press `s` to save/unsave; `l` to view saved
- **Open in browser** — Press `o` to open job URL
- **Re-run** — Press `r` to search again with different terms
- **Non-interactive mode** — Use `-b` or `--non-interactive` flag to skip all prompts and auto-search

### 4. Config File (Optional)

Create `matcha.yaml` in the project directory or `~/.matcha/settings.yaml`:

```yaml
search:
  query: Platform Engineer
  location: Pune
  days: 7
ai:
  enabled: true
scrapers:
  serpapi:
    key: your_serpapi_key
```

### Example Detail View

```
╭─────────────────────────── Job Details ───────────────────────────╮
│ Platform Engineer @ Barclays                                      │
│ Company: Barclays                                                 │
│ Location: Pune, India                                             │
│ Source: Indeed                                                    │
│ URL: https://in.indeed.com/viewjob?jk=b52083124e35dc8d            │
│ Match Score: 82%                                                  │
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
| **LinkedIn** | Guest API endpoint (`/jobs-guest/api/seeMoreJobPostings`) | ~10 listings | Nothing |
| **Indeed India** | `cloudscraper`-based HTML parsing on Python 3.9; falls back to `ddgs` (`site:in.indeed.com/viewjob`) on Python 3.14 | 5–25 listings | Nothing |
| **RemoteOK** | Public JSON API filtered by keyword matching | ~8 listings | Nothing |
| **Naukri** | `ddgs` API with `site:naukri.com` search, non-job content filtered out | 6–44 listings | Nothing |
| **Web Search** | `ddgs` API with targeted `site:` queries on known job boards (LinkedIn, Greenhouse, Lever, Ashby) | 10–30 listings | Nothing |
| **Google Jobs** | SerpAPI `google_jobs` engine (optional) | Rich listings | SerpAPI key |

---

## Relevance Scoring

### Heuristic Pass (all jobs)

| Dimension | Weight | Method |
|-----------|--------|--------|
| Title Match | 20% | Token overlap between job title and profile title/headline |
| Skills Match | 35% | Ratio of profile skills found in job title + description |
| Keyword Match | 15% | Profile keywords found in job posting text |
| Seniority | 10% | Level alignment (entry/mid/senior) based on experience |
| Location | 8% | City/region match; remote bonus |
| *(Floor)* | *(Remainder)* | Score clamped to 0–100 |

### AI Pass (top 15 candidates)

Jobs are re-scored by an LLM using a structured prompt covering:
- **Skills match (40%)** — Honest assessment of skill overlap and missing requirements
- **Title/role alignment (25%)** — Career trajectory fit, not just keyword match
- **Experience fit (20%)** — Appropriate seniority level
- **Location fit (15%)** — Geography preference

The prompt is tuned to be **critical** — scores of 80+ are reserved for strong alignment. No job receives a perfect 100.

---

## Optional: AI Integration

For AI-powered features (profile extraction, title suggestion, query expansion, relevance scoring), set the `$MINIMAX` environment variable or run `--configure`:

```bash
export MINIMAX="your_key_here"
```

The AI provider uses the **Kilo Gateway** (`api.kilo.ai`) with model `kilo-auto/small` — a free-tier-compatible endpoint.

With AI enabled:
- Resume PDFs are parsed entirely by AI — extracts name, skills (30+), title, experience, and summary in one pass
- Search queries are expanded to 3–5 diverse variants targeting adjacent roles
- Top 15 jobs are re-scored by AI for more accurate relevance ranking
- Job titles are suggested from your skill set (no hardcoded mappings)

---

## Project Structure

```
matcha/
├── main.py                  # CLI entry point, orchestration, UI
├── profile.py               # AI-only profile ingestion (PDF, LinkedIn, manual)
├── matcher.py               # Two-pass relevance scoring engine
├── ai.py                    # AI provider client (Kilo Gateway)
├── config.py                # Persistent config and profile storage
├── models.py                # Pydantic v2 data models
├── settings.py              # YAML config loader
├── actions.py               # Saved-job actions
├── requirements.txt         # Python dependencies
├── kilo.md                  # Dev session log / architecture notes
└── scrapers/
    ├── __init__.py
    ├── utils.py             # Resilient HTTP client, rate limiter, cache
    ├── indeed.py            # Indeed: cloudscraper (3.9) → ddgs fallback (3.14)
    ├── linkedin.py          # LinkedIn guest API
    ├── naukri.py            # Naukri via ddgs API search
    ├── remoteok.py          # RemoteOK public JSON API
    ├── serpapi_jobs.py      # Google Jobs via SerpAPI (optional)
    └── web_search.py        # ddgs API with targeted site: queries on job boards
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

---

## License

MIT
