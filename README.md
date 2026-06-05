# Job Finder 🔍

> **Multi-source job aggregator with AI-powered relevance ranking.**
> Enter your profile once — get ranked, personalized job matches from across the web.

[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue)]()
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
- **PDF Resume** — Extracts name, title, skills, and experience via `pdfplumber`, then AI-enriches the result for deeper skill detection and headline generation.
- **LinkedIn URL** — Fetches public profile data with DuckDuckGo fallback when LinkedIn blocks direct access (HTTP 999). Supplement mode lets you fill gaps.
- **Manual Entry** — Full control over every field. Always works.

**AI Query Expansion** — Generates 3–5 diverse search queries from your profile (e.g., "Platform Engineer" → "Site Reliability Engineer", "Cloud Infrastructure Engineer", "DevOps Automation", "Developer Productivity Engineer"), dramatically expanding the search surface.

**Intelligent URL Resolution** — Indeed tracking URLs (`/rc/clk`, `/pagead/clk`) are transparently resolved to clean `viewjob` URLs using job key extraction and fallback HEAD redirect following.

**Rich Terminal UI**
- Color-coded match scores (green ≥ 60, yellow ≥ 25, red < 25)
- Paginated results table (20 per page)
- Interactive job detail panel with full URL, match reasons, and description
- Live progress bars for search and AI scoring phases
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
           │                │    │  ai.py            │    │                  │
           │  • PDF parsing │    │                  │    │  • LinkedIn      │
           │  • LinkedIn    │    │  • Heuristic (5  │    │  • Indeed        │
           │    scraping    │    │    dimensions)   │    │  • Naukri        │
           │  • AI enrich   │    │  • AI re-scoring │    │  • RemoteOK      │
           │  • Manual      │    │  • Query gen     │    │  • Web Search    │
           └────────────────┘    └──────────────────┘    │  • SerpAPI (opt) │
                                                          └──────────────────┘
```

### Data Flow

1. **Profile Ingestion** — Resume PDF, LinkedIn URL, or manual input → structured profile (name, title, skills, experience, summary)
2. **Query Expansion** — Base query + AI-generated variant queries targeting adjacent roles
3. **Parallel Scraping** — `ThreadPoolExecutor` dispatches all queries × all scrapers concurrently (up to 30 tasks)
4. **Deduplication** — Title+company hash eliminates cross-source duplicates
5. **First-Pass Ranking** — Heuristic scorer evaluates all jobs in O(n) using token overlap matching
6. **Second-Pass Ranking** — Top 15 candidates re-scored by LLM with structured JSON output
7. **Display** — Paginated table with color-coded match scores → interactive detail view

---

## Installation

### System Requirements

- **Python 3.9+** — Works with CLT Python 3.9 (`/Library/Developer/CommandLineTools/usr/bin/python3`) on macOS
- **Python 3.14** — Also supported inside a virtual environment (see below)
- **macOS only** — Not tested on Linux/Windows

### Setup

```bash
git clone https://github.com/yourusername/job-finder.git
cd job-finder
pip3 install -r requirements.txt
python3 main.py
```

**Important for Python 3.14 (Homebrew):** Create a virtual environment first to avoid urllib3 v2 + macOS LibreSSL segfault:

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python3 main.py
```

### Dependencies

| Package | Purpose |
|---------|---------|
| `requests` | HTTP client for all scrapers |
| `requests-cache` | SQLite-backed HTTP cache (30-min TTL, 200-only) |
| `beautifulsoup4` | HTML parsing for all scrapers |
| `rich` | Terminal UI (tables, panels, progress bars, prompts) |
| `cloudscraper` | Cloudflare bypass for Indeed India (Python 3.9 only; 403s on 3.14) |
| `ddgs` | DuckDuckGo API — powers Web Search scraper + Indeed fallback |
| `pdfplumber` | PDF resume text extraction |
| `prompt_toolkit` | Interactive keyboard-driven UI for job browsing |
| `rapidfuzz` | Fuzzy string matching for deduplication |
| `pydantic` | Data models for profile, jobs, and settings |
| `pyyaml` | YAML config file support |
| `python-dotenv` | Environment variable management |
| `urllib3<2` | Pinned to v1 to prevent LibreSSL segfault on macOS |

---

## Usage

### 1. Profile Setup

```
╭──────────────────────────────────────────────╮
│ Job Finder                                   │
│ Find the most relevant jobs for your profile │
╰──────────────────────────────────────────────╯
Existing profile found:
  Name          Rishikesh Vijay Sonawane
  Title         CI/CD Infrastructure | DevOps Engineer
  Skills        ansible, aws, ci/cd, django, docker, ...
  Experience    ~4 years
Use existing profile? [y/n] (y):
```

Three entry methods:
- **PDF Resume** — Extracts structured data with AI enhancement
- **LinkedIn URL** — Scrapes public profile with fallback
- **Manual** — Full manual control

### 2. Search

```
Job search query (Platform Engineer):
Location (or leave blank for remote): Pune
```

### 3. Results

```
Found 97 total jobs — 50 from LinkedIn | 6 from Naukri | 38 from RemoteOK | 4 from Web Search

  #  Title                    Company         Source    Link                               Match
 ─── ──────────────────────── ─────────────── ──────── ────────────────────────────── ─────────
  1  Platform Engineer        Barclays        Indeed    in.indeed.com/viewjob?jk=b5...     82%
  2  Platform Engineer II     Mastercard      Indeed    in.indeed.com/viewjob?jk=e4...     78%
  3  GCP Platform Engineer    Nexifyr         Web       nexifyr.com/careers/position...    71%
  4  Platform Engineer        Evolent Health  Indeed    in.indeed.com/viewjob?jk=cc...     65%
  ...
```

Interactive features:
- **Paginated browsing** — `↑↓` navigate, `n/p` page, `Enter` for details
- **Job details** — Full URL, match reasons, and description
- **Save jobs** — Press `s` to save/unsave; `l` to view saved
- **Open in browser** — Press `o` to open job URL
- **Re-run** — Press `r` to search again with different terms
- **Non-interactive mode** — Use `-b` or `--non-interactive` flag to skip all prompts and auto-search

### 5. Config File (Optional)

Create `job-finder.yaml` in the project directory or `~/.job-finder/settings.yaml`:

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
│   • Skill match: aws, docker, terraform, ci/cd, linux             │
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
| **Naukri** | DuckDuckGo API search for Naukri.com listings | 0–5 listings | Nothing |
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

For AI-powered features (profile enhancement, query expansion, relevance scoring), set the `$MINIMAX` environment variable or configure the key through the app prompt:

```bash
export MINIMAX="your_key_here"
```

The AI provider uses the **Kilo Gateway** (`api.kilo.ai`) with model `kilo-auto/small` — a free-tier-compatible endpoint.

With AI enabled:
- Resume PDF parsing is AI-enhanced for deeper skill and title extraction
- Search queries are expanded to 3–5 diverse variants targeting adjacent roles
- Top 15 jobs are re-scored by AI for more accurate relevance ranking

---

## Project Structure

```
job-finder/
├── main.py                  # CLI entry point, orchestration, UI
├── profile.py               # Profile ingestion (PDF, LinkedIn, manual)
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

- **Parallel execution** — `ThreadPoolExecutor` dispatches 30+ scraper tasks concurrently, reducing total search time from minutes to ~30–60 seconds
- **Resilient scrapers** — Each scraper is isolated in a try/except block; a single source failure never blocks others
- **Smart deduplication** — Cross-source duplicate detection using normalized title+company keys
- **Tracking URL resolution** — Indeed `rc/clk` and `pagead/clk` URLs decoded to clean `viewjob` URLs via job key extraction or HTTP redirect following
- **AI prompt engineering** — Structured JSON output with temperature 0.1 for reliable parsing; fallback regex extraction for malformed responses
- **Pagination** — Scrollable results with interactive job detail panels; no external dependencies beyond `rich`
- **Zero API key lock-in** — Core functionality works without any paid API keys

---

## License

MIT
