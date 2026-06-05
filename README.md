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

```bash
git clone https://github.com/yourusername/job-finder.git
cd job-finder
pip3 install -r requirements.txt
python3 main.py
```

### Dependencies

| Package | Purpose |
|---------|---------|
| `requests` | HTTP client for all scrapers |
| `beautifulsoup4` | HTML parsing for all scrapers |
| `rich` | Terminal UI (tables, panels, progress bars, prompts) |
| `cloudscraper` | Cloudflare bypass for Indeed India |
| `pdfplumber` | PDF resume text extraction |
| `python-dotenv` | Environment variable management |

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
Found 245 total jobs — 24 from LinkedIn | 30 from Indeed | 18 from Naukri | 8 from RemoteOK | 165 from Web Search

  #  Title                    Company         Source    Link                               Match
 ─── ──────────────────────── ─────────────── ──────── ────────────────────────────── ─────────
  1  Platform Engineer        Barclays        Indeed    in.indeed.com/viewjob?jk=b5...     82%
  2  Platform Engineer II     Mastercard      Indeed    in.indeed.com/viewjob?jk=e4...     78%
  3  GCP Platform Engineer    Nexifyr         Web       nexifyr.com/careers/position...    71%
  4  Platform Engineer        Evolent Health  Indeed    in.indeed.com/viewjob?jk=cc...     65%
  ...
```

Interactive features:
- **Paginated browsing** — 20 results per page, `y/n` to continue
- **Job details** — Enter a number to see full URL, match reasons, and description
- **Re-run** — Search again with different terms

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
| **Indeed India** | `cloudscraper`-based HTML parsing of `in.indeed.com` | ~25 listings | Nothing |
| **RemoteOK** | Public JSON API filtered by keyword matching | ~8 listings | Nothing |
| **Naukri** | DuckDuckGo search for Naukri.com listings | Search page links | Nothing |
| **Web Search** | DuckDuckGo HTML search with job board domain filtering | 100+ listings | Nothing |
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
├── requirements.txt         # Python dependencies
└── scrapers/
    ├── __init__.py
    ├── indeed.py            # Indeed India (cloudscraper + URL resolution)
    ├── linkedin.py          # LinkedIn guest API
    ├── naukri.py            # Naukri via DuckDuckGo search
    ├── remoteok.py          # RemoteOK public API
    ├── serpapi_jobs.py      # Google Jobs via SerpAPI (optional)
    └── web_search.py        # DuckDuckGo web search with job board filtering
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
