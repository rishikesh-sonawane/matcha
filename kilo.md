# Job Finder — Project Context

## Overview

Job Finder is a Python terminal application (TUI) that aggregates job listings from multiple sources, ranks them by relevance to a user's professional profile, and displays them in an interactive, color-coded terminal interface. It uses a two-pass relevance engine (heuristic + optional AI via Kilo Gateway) and supports three methods of profile entry (PDF resume, LinkedIn URL, manual).

---

## Tech Stack

| Technology | Purpose |
|---|---|---|
| Python 3.9+ | Runtime |
| Rich | Terminal UI (tables, panels, progress bars, live display) |
| prompt_toolkit | Interactive TUI navigation, keyboard bindings, full-screen mode |
| requests | HTTP client for all scrapers |
| beautifulsoup4 | HTML parsing for all scrapers |
| cloudscraper | Cloudflare bypass for Indeed India |
| pdfplumber | PDF text extraction for resumes |
| rapidfuzz | Fuzzy string matching for deduplication |
| requests-cache | Disk-backed HTTP cache (SQLite, 30min TTL) |
| pydantic | Data validation and type safety (v2) |
| ruff | Python linter and formatter |
| pre-commit | Git pre-commit hooks |
| Docker | Containerization (python:3.11-slim, multi-stage, non-root user UID 10001) |
| GitHub Actions | CI/CD (lint, format, test, Docker build/push to GHCR) |

## Python Dependencies

```
requests>=2.28.0
requests-cache>=1.0.0
pyyaml>=6.0
pydantic>=2.0
beautifulsoup4>=4.11.0
rich>=13.0.0
python-dotenv>=1.0.0
pdfplumber>=0.10.0
cloudscraper>=1.2.71
rapidfuzz>=3.0.0
prompt_toolkit>=3.0.0
ddgs>=9.14.0
```

---

## Directory Structure

```
/Users/rishi/Code/projects/job-finder/
├── .dockerignore
├── .github/workflows/ci.yml         # GitHub Actions: matrix (3.9-3.12), lint+format+test, Docker on tags
├── .pre-commit-config.yaml           # ruff (lint+format), trailing-whitespace, end-of-file, check-yaml, check-merge-conflict
├── Dockerfile                        # Multi-stage python:3.11-slim, non-root user
├── FuturePlan.txt                    # Detailed production-grade enhancement plan (25+ items)
├── README.md                         # Full project documentation
├── actions.py                        # Save/unsave/load jobs (SQLite persistence in ~/.job-finder/jobs.db)
├── ai.py                             # AI client for Kilo Gateway (profile extraction, query gen, job scoring)
├── config.py                         # Persistent JSON config in ~/.job-finder/ (config.json, profile.json)
├── docker-compose.yml                # Docker Compose with MINIMAX/SERPAPI_KEY env vars, persistent config volume
├── kilo.md                           # This file — project context for AI agents
├── main.py                           # CLI entry point, orchestration, TUI (prompt_toolkit + Rich), ~625 lines
├── matcher.py                        # Two-pass relevance scoring (heuristic + AI wrapper), ~25 lines
├── models.py                         # Pydantic v2 data models (Job, Profile, RelevanceResult, SavedJob, SearchConfig, AIConfig, ScraperConfig, Settings)
├── profile.py                        # AI-only profile ingestion via PDF, LinkedIn, or manual, ~415 lines
├── pyproject.toml                    # Ruff config (line-length 100, target py39), pytest config
├── requirements.txt                  # 10 dependencies
├── scrapers/
├── settings.py                       # YAML config loader (non-interactive mode), 48 lines
│   ├── __init__.py                   # Re-exports from linkedin, naukri, remoteok, serpapi_jobs, web_search
│   ├── indeed.py                     # Indeed India scraper (cloudscraper + URL resolution), 115 lines
│   ├── linkedin.py                   # LinkedIn guest API scraper, 74 lines
│   ├── naukri.py                     # Naukri via DuckDuckGo API (ddgs), ~143 lines
│   ├── remoteok.py                   # RemoteOK public API scraper, 114 lines
│   ├── serpapi_jobs.py              # Google Jobs via SerpAPI (optional), 88 lines
│   ├── utils.py                      # resilient_get() + HTTP cache + per-domain rate limiter (token bucket), 76 lines
│   └── web_search.py                 # DuckDuckGo web search with job board filtering, 213 lines
└── tests/
    ├── __init__.py
    └── test_core.py                  # 274 lines, 6 test classes, 42 test methods (unittest)
```

---

## Core Workflow (main.py)

1. **Profile Entry** — `build_or_load_profile()`: load saved or enter via PDF/LinkedIn/manual
2. **Query Input** — Prompt for search query + location (with defaults from config/profile)
3. **Query Expansion** — If AI available, `ai_generate_queries()` adds 3-5 variant queries
4. **Parallel Search** — `search_jobs()` runs all scrapers × all queries via ThreadPoolExecutor (max 12 workers)
5. **Live Status** — Rich table shows scraper status (OK/...) with result counts during search
6. **Deduplication** — `deduplicate()` uses rapidfuzz (title threshold 82%, company threshold 88%)
7. **Heuristic Ranking** — `compute_relevance()` scores on 5 dimensions (title 20%, skills 35%, keywords 15%, seniority 10%, location 8%)
8. **AI Re-scoring** — If AI available, top 15 jobs re-scored via `compute_relevance_ai()` (ThreadPoolExecutor, max 8 workers)
9. **Interactive TUI** — `prompt_loop()` with paginated table (10/page), keyboard navigation, job detail panel, save/open

## CLI

```bash
python3 main.py                                    # Normal flow (interactive prompts)
python3 main.py -b                                   # Non-interactive mode (requires YAML config)
python3 main.py --config /path/to/config.yaml -b     # Custom config path in non-interactive mode
python3 main.py --configure                          # Set SerpAPI + AI API keys
python3 main.py --new-profile / -n                   # Re-enter profile from scratch
python3 main.py --help                               # Help
```

---

## All Source Files — Detailed Breakdown

### main.py (552 lines) — Orchestrator + TUI

**Key functions:**
- `configure_serpapi()` — interactive SerpAPI key setup
- `configure_ai()` — interactive AI API key setup
- `run_scraper(name, scraper_func, query, location, days)` — wraps scraper call in try/except, passes days to each scraper
- `main()` now accepts `--non-interactive` / `-b` (skip prompts, uses YAML config values) and `--config` (custom YAML path)
- `_normalize(text)` — lowercase + strip roman numerals/seniority abbrev + remove punctuation + collapse whitespace
- `deduplicate(jobs, title_threshold=82, company_threshold=88)` — rapidfuzz fuzzy dedup
- `search_jobs(queries, location, days)` — parallel scrape across all sources × all queries, passes days to each scraper, live Rich table
- `rank_jobs(jobs, profile, use_ai=False)` — heuristic ranking + optional AI re-scoring of top 15
- `build_results_table(ranked, page, page_size, total_pages, ai_enabled, saved_ids, highlight)` — Rich Table for results
- `show_job_detail(job, score, reasons)` — Rich Panel for job details
- `prompt_loop(ranked, source_counts, ai_enabled)` — full interactive TUI with prompt_toolkit Application
  - **Modes:** "list", "detail", "saved"
  - **Key bindings:** up/down (navigate), enter (detail), s (save/unsave), o (open in browser), n/p (next/prev page), l (saved list), r (re-run), q (quit)
  - State tracked via simple `State` class with: `page`, `selected`, `mode`, `detail_idx`, `re_run`

**SCRAPER_DEFS dict (line 37-44):**
```python
SCRAPER_DEFS = {
    "LinkedIn": search_linkedin_jobs,
    "Indeed": search_indeed_jobs,
    "Naukri": search_naukri_jobs,
    "RemoteOK": search_remoteok_jobs,
    "Web Search": search_web_for_jobs,
}
```
Google Jobs added dynamically if SerpAPI key present.

---

### profile.py (~415 lines) — Profile Ingestion (AI-only)

**Key functions:**
- `parse_resume_pdf(path)` — pdfplumber extraction → AI-only extraction via `ai_extract_profile()` (no fallback keyword matching)
- `scrape_linkedin_profile(url)` — direct LinkedIn page scrape, falls back to `search_linkedin_profile_via_web()` via DuckDuckGo
- `search_linkedin_profile_via_web(username)` — DuckDuckGo search fallback for LinkedIn profile gathering
- `manual_profile_entry()` — interactive prompts for all profile fields
- `build_or_load_profile(force_new=False)` — orchestrator: check saved → choose method → AI-first extraction, falls back to manual entry if AI unavailable
- `ai_suggest_titles()` called from `ai.py` to suggest job titles from skills (replaces old `suggest_title` with hardcoded map)

**Removed (AI replacement):** `suggest_title()`, `_fallback_parse()`, `_load_profile_config()`, `_match_keywords()`, `_extract_skills_section()`, `_find_section_range()`, `_score_section_skills()`, `_clean_keyword()`, all keyword/section/pattern configs

**Profile dict shape:**
```python
{
    "name": str,
    "title": str,
    "headline": str,
    "skills": list[str],
    "experience": str,      # e.g. "4"
    "summary": str,
    "location": str,        # added at search time
}
```

---

### models.py (54 lines) — Pydantic V2 Data Models

**Models:**
- `Job` — `{title, company, location, description, url, source}`
- `Profile` — `{name, title, headline, skills, experience, summary, location}`
- `RelevanceResult` — `{score: float 0-100, reasons: list[str]}`
- `SavedJob` — `{title, company, url, source}`
- `SearchConfig` — `{query, location, days}`
- `AIConfig` — `{enabled}`
- `ScraperConfig` — `{serpapi}`
- `Settings` — `{search: SearchConfig, ai: AIConfig, scrapers: ScraperConfig}`

**Usage:** Models are defined for type safety and documentation. Runtime code still uses plain dicts for flexibility and backward compatibility with scrapers and serialization.

---

### matcher.py (202 lines) — Relevance Scoring

**Two-pass system:**

**Pass 1 — Heuristic (`compute_relevance`):**
| Dimension | Weight | How it works |
|---|---|---|
| Title Match | 20% | Token overlap between profile title/headline and job title |
| Skills Match | 35% | Ratio of profile skills found in job text |
| Keyword Match | 15% | Remaining profile keywords in job text (capped at 15 pts) |
| Seniority Match | 10% | Experience years → expected level (entry/mid/senior) matched against job keywords |
| Location Match | 8% | Profile location in job location, or "Remote" bonus |

Score clamped to [0, 100], top 8 reasons returned.

**Pass 2 — AI (`compute_relevance_ai`):** Wraps `ai_score_job()` from ai.py. Only runs if AI key available. Top 15 jobs re-scored in parallel (max 8 workers).

Helper: `tokenize(text)` — lowercase + extract `[a-z0-9+#.]+` tokens. `STOP_WORDS` set (58 words).

---

### ai.py (~305 lines) — AI Client

**Provider:** Kilo Gateway (`https://api.kilo.ai/api/gateway/chat/completions`, model `kilo-auto/small`)
**Auth:** Bearer token from `$MINIMAX` env var or `config.json` `ai_key` field
**Config key:** `ai_key`, **Env var:** `MINIMAX`
**Temperature:** 0.1 (hardcoded)
**Note:** `response_format={"type": "json_object"}` is NOT passed — the `kilo-auto/small` model does not support it and silently fails.

**Functions:**
- `_get_api_key()` — env var > config file
- `check_ai_available()` — bool if key present
- `configure_ai(key)` — save key to config
- `_call_ai(messages, response_format, max_tokens=500)` — POST to Kilo Gateway, 30s timeout
- `_extract_json(text)` — parse JSON from LLM response (handles ```json blocks, embedded JSON, plain JSON)
- `ai_extract_profile(text)` — resume enrichment via `PROFILE_EXTRACTION_PROMPT`
- `ai_generate_queries(profile)` — 3-5 expanded search queries via `QUERY_GENERATION_PROMPT`
- `ai_score_job(profile, job)` — structured job scoring via `JOB_SCORING_PROMPT` (0-100 + reasons)
- `ai_suggest_titles(skills)` — suggests 3-5 job titles matching a skills list via `SUGGEST_TITLES_PROMPT`

---

### config.py (38 lines) — File-based Config

**Directory:** `~/.job-finder/` (auto-created)
**Files:**
- `config.json` — `{ai_key, serpapi_key, last_query, last_location}`
- `profile.json` — saved profile dict

**Functions:** `load_config()`, `save_config()`, `load_profile()`, `save_profile()`

---

### actions.py (107 lines) — Job Lifecycle (SQLite)

**File:** `~/.job-finder/jobs.db` (SQLite)
**Schema:**
```sql
CREATE TABLE jobs (
    url TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    company TEXT NOT NULL,
    source TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'saved',  -- saved, applied, dismissed, interview, rejected, offer
    saved_at TEXT NOT NULL,
    applied_at TEXT,
    notes TEXT DEFAULT ''
)
```
**Valid statuses:** `saved`, `applied`, `dismissed`, `interview`, `rejected`, `offer`
**Functions:** `load_saved_jobs()` → `{url: {title, company, url, source}}`, `is_job_saved()`, `save_job()`, `unsave_job()`, `set_job_status(url, status)`, `get_job_status(url)`
**Migration:** Automatically migrates from `saved.json` on first run — creates SQLite DB with WAL mode. Backward-compatible dict interface preserved for in-memory `saved_ids` use in TUI loop.

---

## Scrapers — Detailed

### scrapers/indeed.py (115 lines)
- **Target:** `in.indeed.com` (India)
- **Method:** cloudscraper with HTML parsing
- **URL resolution:** `resolve_indeed_url()` decodes `rc/clk` and `pagead/clk` tracking URLs → clean `viewjob?jk=` URLs
- **Selectors:** `.job_seen_beacon`, `[data-jk]`, `h3.jobTitle a`, `[data-testid=company-name]`, `[data-testid=text-location]`

### scrapers/linkedin.py (76 lines)
- **Target:** LinkedIn guest API
- **Endpoint:** `/jobs-guest/jobs/api/seeMoreJobPostings/search?keywords=...&location=...&f_TPR=r{days*86400}`
- **Method:** requests + BeautifulSoup, parses `<li>` job cards
- **Time filter:** `f_TPR=r{days*86400}` — accepts `days` kwarg (default 7, min 1). User is prompted for days in main flow

### scrapers/naukri.py (~143 lines)
- **Target:** Naukri.com (via DuckDuckGo API)
- **Method:** Uses `ddgs.text("site:naukri.com {query}")` API call (was `html.duckduckgo.com` HTML scrape)
- **Filtering:** Strips non-job content (`/code360/`, `/campus/`, `/blog/`, `/interview-`, `companies.naukri.com`)
- **Title extraction:** URL-based fallback for search category pages, snippet-based extraction for job listings
- **Timeout:** 8s per request (was 15s)
- **Performance:** Single API call per query (was 2 sequential HTML searches)

### scrapers/remoteok.py (114 lines)
- **Target:** RemoteOK public API (`remoteok.com/api`)
- **Method:** Fetch JSON, filter by title/tag match against significant query terms (stop words excluded)
- **Response:** Array with index 0 being metadata, rest are job objects

### scrapers/serpapi_jobs.py (88 lines)
- **Target:** Google Jobs via SerpAPI (`serpapi.com/search.json?engine=google_jobs`)
- **Required:** `serpapi_key` in config
- **Method:** `resilient_get()` → parse `jobs_results` array
- **Fallback:** Silent skip if no key

### scrapers/web_search.py (213 lines)
- **Target:** DuckDuckGo web search for any job listings
- **Method:** Two queries per run (`{query} {location}` + `{query} hiring`), parse `.result` elements
- **Filtering:**
  - Skip ads (`.badge--ad`)
  - Skip search/aggregation pages (regex patterns in `SEARCH_PAGE_PATTERNS`)
  - Accept individual job pages (`INDIVIDUAL_JOB_PATTERNS`) OR known job board domains (13 domains)
- **Helper functions:** `is_search_page()`, `extract_url()`, `clean_title()`, `extract_company()`, `extract_location()`, `identify_source()`

### scrapers/utils.py (90 lines)
- `resilient_get(url, session, **kwargs)` — 3 retries, exponential backoff (1s, 2s, 4s), retry on {429, 502, 503, 504}, ConnectionError, Timeout
- **HTTP cache:** Module-level `requests_cache.CachedSession` with SQLite backend at `~/.job-finder/http_cache.sqlite`, 30-minute TTL, caches only 200 OK responses. Used by default in `resilient_get()` — LinkedIn, Naukri, RemoteOK, SerpAPI, and Web Search scrapers all benefit automatically
- **Rate limiter:** `TokenBucket` + `RateLimiter` classes implement per-domain token bucket throttling with per-domain locks (thread-safe). Rates:
  - `linkedin.com`: 3 req/min
  - `indeed.com`: 5 req/min
  - `remoteok.com`: 10 req/min
  - `serpapi.com`: 8 req/min
  - `duckduckgo.com`: 6 req/min
  - Jitter (0.5–1.5x) applied to wait times to avoid thundering herd

### scrapers/__init__.py (6 lines)
- Re-exports: `search_linkedin_jobs`, `search_naukri_jobs`, `search_remoteok_jobs`, `check_serpapi_available`, `search_serpapi_jobs`, `search_web_for_jobs`
- **Missing:** Does NOT re-export `search_indeed_jobs` or `resolve_indeed_url` (main.py imports directly from `scrapers.indeed`)

---

## External Services

| Service | Endpoint | Auth | Required? |
|---|---|---|---|
| Kilo Gateway | `api.kilo.ai/api/gateway/chat/completions` | Bearer token (`$MINIMAX` / config) | Optional |
| SerpAPI | `serpapi.com/search.json` | `api_key` query param | Optional |
| LinkedIn | `linkedin.com/jobs-guest/jobs/api/...` | None (guest) | Free |
| Indeed | `in.indeed.com/jobs` | None (cloudscraper) | Free |
| RemoteOK | `remoteok.com/api` | None | Free |
| DuckDuckGo | `ddgs` Python library | None | Free (for web search, Naukri, Indeed fallback) |

---

## Configuration (Persistent)

**Config directory:** `~/.job-finder/` (auto-created)
**Config files:**
- `config.json` — `{ai_key, serpapi_key, last_query, last_location, last_days}` (`last_query`/`last_location` are checked AFTER profile title/settings query in default precedence)`
- `profile.json` — `{name, title, headline, skills, experience, summary}`
- `jobs.db` — SQLite database for job lifecycle tracking (statuses: saved, applied, dismissed, interview, rejected, offer)
- `http_cache.sqlite` — Auto-created by requests-cache, 30min TTL
- `settings.yaml` — Optional user-facing YAML config (also loaded from `./job-finder.yaml`)

**YAML config structure:**
```yaml
search:
  query: "Platform Engineer"
  location: "Pune"
  days: 7
ai:
  enabled: true
scrapers:
  serpapi: false
```
Config files are loaded in order: `--config` flag > `./job-finder.yaml` > `~/.job-finder/settings.yaml`, with deep merge semantics. Used to pre-fill prompts in interactive mode or drive non-interactive mode.

**Hardcoded settings:**
- AI model: `kilo-auto/small`, API URL: `https://api.kilo.ai/api/gateway/chat/completions`, temp: 0.1
- Indeed domain: `in.indeed.com` (India-only)
- Page size: 10, AI scoring top N: 15, max scraper workers: 12, max AI workers: 8
- HTTP timeouts: 8-20s (8s for Naukri, 10-20s for other scrapers)
- Dedup thresholds: title 82%, company 88%
- Retry: 3 attempts, backoff 1s/2s/4s, on {429,502,503,504} + ConnectionError + Timeout
- HTTP cache: SQLite backend, 30-minute TTL, caches only 200 OK

---

## Testing

**Framework:** Python `unittest` (stdlib)
**File:** `tests/test_core.py` (~288 lines)
**Run:** `python -m unittest tests.test_core -v`

**Test classes (24 methods total):**
| Class | Tests | What it covers |
|---|---|---|
| TestNormalize | 6 | `_normalize()` — lowercase, roman numerals, seniority abbrev, punctuation, whitespace, empty |
| TestDeduplicate | 8 | `deduplicate()` — exact, roman vs digit, reordering, different jobs, company variants, sr/senior, empty fields, no duplicates |
| TestTokenize | 5 | `tokenize()` — basic, lowercase, numbers, empty, special chars |
| TestComputeRelevance | 5 | `compute_relevance()` — perfect match, no match, partial, reasons, bounds |
| TestResolveIndeedURL | 6 | `resolve_indeed_url()` — rc/clk, clean URL, non-indeed, pagead/clk, no jk param, empty |
| TestSuggestTitle | 5 | `ai_suggest_titles()` — devops/backend/frontend skills, empty, unrecognized (mocks `check_ai_available` + `_call_ai`) |
| TestExtractJSON | 6 | `_extract_json()` — plain, codeblock, embedded, invalid, empty |

**CI:** GitHub Actions runs tests across Python 3.9, 3.10, 3.11, 3.12 matrix.

---

## CI/CD Pipeline (`.github/workflows/ci.yml`)

**Triggers:** push to `main`, PR to `main`, tags `v*`

**Jobs:**
1. **quality** — matrix (3.9-3.12): install → ruff check → ruff format --diff → pre-commit → unittest
2. **docker** — on tags only, after quality: build → push to GHCR with semver tags (version, major.minor, latest)

---

## Docker

**Base:** `python:3.11-slim` (multi-stage)
**User:** Non-root UID 10001
**Entrypoint:** `python3 main.py`
**Compose:** Mounts `job-finder-config` volume at `/home/app/.job-finder`, passes `$MINIMAX` and `$SERPAPI_KEY` env vars

---

## TUI Interaction (main.py `prompt_loop`)

**Modes:**
- `list` — paginated results table (10/page), color-coded scores (green ≥60, yellow ≥25, red <25), saved jobs marked with ★
- `detail` — full job panel (title, company, location, source, URL, score, reasons, description truncated to 500 chars)
- `saved` — table of bookmarked jobs

**Key bindings:**
| Key | Action |
|---|---|
| ↑/↓ | Navigate list (wraps across pages) |
| Enter | Toggle list ↔ detail mode |
| s | Save/unsave current job |
| o | Open job URL in browser |
| n/p | Next/previous page |
| l | Show saved jobs list |
| r | Re-run with new query |
| q | Quit |

**Edge case:** Jobs with score 0 are filtered out before TUI display (`prompt_loop` line 267).

---

## Data Schemas (Pydantic v2 models in models.py + dicts for runtime)

**Job dict:**
```python
{"title": str, "company": str, "location": str, "description": str, "url": str, "source": str}
```

**Relevance result:**
```python
{"score": float (0-100), "reasons": list[str] (max 8)}
```

**Ranked job tuple:** `(score, job_dict, reasons_list)`

**Saved job entry:**
```python
{"title": str, "company": str, "url": str, "source": str}
```

---

## Key Observations & Gotchas

1. **scrapers/__init__.py is incomplete** — does not re-export `search_indeed_jobs` or `resolve_indeed_url` (main.py imports them directly from `scrapers.indeed`)
2. ~~**urllib3 v2 + LibreSSL segfault**~~ **RESOLVED:** Pinned `urllib3<2` in requirements.txt. urllib3 v2 requires OpenSSL 1.1.1+ but macOS ships LibreSSL; HTTPS POSTs (AI scoring) segfault. urllib3 v1 is fully compatible.
3. ~~**Web search garbled titles/companies**~~ **RESOLVED:** Replaced broken DuckDuckGo HTML scraper (`html.duckduckgo.com` returns captcha 202) with `ddgs` API. Titles cleaned to first segment. `identify_source()` strips `www` prefix. `extract_company()` uses title-based extraction for "X hiring Y" patterns + validated regex against snippet + domain fallback with `_SKIP_DOMAIN_PARTS` (skips "in", "uk", "careers", "boards", etc.) and `_STOP_WORDS` filtering.
4. ~~**Indeed returns 0 on Python 3.14**~~ **RESOLVED:** Cloudscraper returns 403 on Python 3.14 (challenge-solving broken for Indeed's Cloudflare type). Indeed now tries `_fetch_indeed_page` (resilient_get → cloudscraper) first; if that returns 0, falls back to `ddgs` with `site:in.indeed.com/viewjob` queries. On Python 3.9 cloudscraper works so the ddgs fallback isn't needed.
5. ~~**No type hints anywhere**~~ **RESOLVED:** Full type hints across all source files + Pydantic v2 models in `models.py`
6. **No logging framework** — all output via `console.print()` mixed with Rich UI
7. **API keys in plaintext** — stored in `~/.job-finder/config.json` unencrypted
8. **India-centric** — Indeed hardcoded to `in.indeed.com`
9. **LinkedIn scraper fragility** — guest API could break without notice, returns ~10 results
10. **Naukri scraper uses DDG API** — rewritten from `html.duckduckgo.com` HTML scraping (which was captcha-blocked and unreliable) to `ddgs.text("site:naukri.com")`. Returns 6-44 jobs per query. Still limited to DDG-indexed Naukri pages, not direct API access.
11. ~~**No HTTP caching** — re-scrapes everything every run~~ **RESOLVED:** requests-cache with SQLite backend, 30-min TTL, caches only 200 OK
12. ~~**No rate limiting** — could get IP banned with aggressive usage~~ **RESOLVED:** Per-domain token bucket rate limiter in `scrapers/utils.py` with 5 configured domains, jitter, and per-domain locks
13. **No web server or API** — pure terminal app, no frontend framework
14. **No state management library** — plain Python dicts + JSON file persistence
15. **No user accounts or authentication** — single-user local app
16. **deduplicate() has edge case in company matching** — line 103-105: when `norm_company` or `s_company` is empty, uses `token_sort_ratio` instead of `token_set_ratio` (logic may be inverted — currently uses `token_set_ratio` when BOTH non-empty, `token_sort_ratio` when either is empty)
17. **deduplicate() doesn't filter done/dead sources** — if a scraper errors, `run_scraper` returns `[]` silently
18. **AI dependency on single provider** (Kilo Gateway) — no fallback
19. **Profile `title` and `headline` often identical** — `headline` defaults to `title` in multiple code paths
20. **Jobs with score 0 are silently filtered** in `prompt_loop` line 267
21. **DuckDuckGo HTML endpoint now fully captcha-blocked** — `html.duckduckgo.com` returns 202 with image captcha for all automated requests. Replaced with `ddgs` Python library in `web_search.py`.
22. **Indeed Cloudflare challenge breaks cloudscraper on Python 3.14** — cloudscraper works on Python 3.9 for Indeed but returns 403 on 3.14. The `ddgs` fallback (`site:in.indeed.com/viewjob`) is the workaround. Company extraction from ddgs snippets is limited ("Unknown" for many results).
23. **`ddgs` is a new dependency** — requires Python >= 3.10. Replaces the DuckDuckGo HTML scraper and serves as Indeed fallback on Python 3.14. CI matrix updated to drop Python 3.9 (was EOL Oct 2025). Both scrapers handle `ImportError` gracefully and return `[]` if `ddgs` is not installed.
24. **Company extraction from search snippets is inherently unreliable** — `extract_company` uses regex + stop-word filtering + title-based + domain fallback but still misses many companies. Future work could use LLM-based extraction.
25. **FuturePlan.txt** contains 25+ planned enhancements (tests, type hints, logging, rate limiting, caching, proxy rotation, config encryption, SQLite job tracking, scheduled mode, more scrapers, fuzzy dedup, health monitoring, profile merge, retry with tenacity, YAML config, better LinkedIn scraping)

---

## Enhancements Log

| # | Enhancement | Status | What changed |
|---|---|---|---|
| 1 | **HTTP Cache (requests-cache)** | ✅ Done | Added `requests-cache>=1.0.0` to requirements; `scrapers/utils.py` now creates a module-level `CachedSession` with SQLite backend at `~/.job-finder/http_cache.sqlite`, 30-min TTL, caches only 200 OK; all scrapers using `resilient_get()` benefit automatically |
| 2 | **Rate Limiting** | ✅ Done | Added `TokenBucket` + `RateLimiter` classes to `scrapers/utils.py` with per-domain token bucket throttling, per-domain locks (thread-safe), and jitter (0.5-1.5x). Configured rates: LinkedIn 3/min, Indeed 5/min, RemoteOK 10/min, SerpAPI 8/min, DuckDuckGo 6/min |
| 3 | **Non-interactive mode + YAML config** | ✅ Done | Added `settings.py` with `load_settings()` — loads YAML from `--config` flag > `./job-finder.yaml` > `~/.job-finder/settings.yaml` with deep merge. Added `--non-interactive`/`-b` flag to skip all prompts. Added `pyyaml>=6.0` to requirements. YAML supports `search.{query,location,days}`, `ai.enabled`, `scrapers.serpapi` |
| 4 | **SQLite job tracking** | ✅ Done | Replaced `saved.json` with SQLite database `~/.job-finder/jobs.db`. Schema: `jobs(url PK, title, company, source, status, saved_at, applied_at, notes)` with statuses: saved/applied/dismissed/interview/rejected/offer. Added `set_job_status()` and `get_job_status()` functions. Uses WAL mode for thread safety. Backward-compatible API preserved (`load_saved_jobs()` still returns dict, `save_job()`/`unsave_job()` work unchanged). No new dependencies (Python stdlib `sqlite3`). |
| 5 | **Type hints + Pydantic models** | ✅ Done | Added `models.py` with Pydantic v2 models (Job, Profile, RelevanceResult, SavedJob, SearchConfig, AIConfig, ScraperConfig, Settings). Added full type hints to all 20+ source files: all function signatures, class attributes, module-level variables. Added `from __future__ import annotations` where needed. Added `pydantic>=2.0` to requirements. Removed "No type hints" gotcha. |
| 6 | **Web search via ddgs API** | ✅ Done | Replaced DuckDuckGo HTML scraper with `ddgs` Python library. DuckDuckGo's `html.duckduckgo.com` endpoint now returns captcha 202 for automated requests. `ddgs` uses the DDG API directly. Also added `_SKIP_DOMAIN_PARTS` company fallback, `_STOP_WORDS` filtering, title-based company extraction, aggregate/search page filtering, non-job URL filtering. |
| 7 | **Indeed fallback via ddgs (Python 3.14)** | ✅ Done | Cloudscraper returns 403 on Python 3.14 for Indeed (Cloudflare challenge-solving broken). Added `_fetch_indeed_page` that tries `resilient_get` → cloudscraper; if 0 jobs, falls back to `ddgs` with `site:in.indeed.com/viewjob` queries. Company extraction from ddgs snippets uses validated regex patterns with stop-word filtering. Added `ddgs` to requirements. |
| 8 | **AI-only profile extraction** | ✅ Done | Removed `response_format={"type": "json_object"}` from all AI calls (model does not support it). Rewrote `profile.py` as AI-only: no fallback parsing functions, no keyword matching, no section-aware extraction. Removed `suggest_title()`, `_fallback_parse()`, `_load_profile_config()`, `_match_keywords()`, `_extract_skills_section()`, `_find_section_range()`, `_score_section_skills()`, `_clean_keyword()`. Added `ai_suggest_titles()` to `ai.py`. Stripped profile fallback config from `settings.py`. Updated tests to mock AI calls. |
| 9 | **Naukri scraper rewritten (DDGS API)** | ✅ Done | Replaced `html.duckduckgo.com` HTML scraping (unreliable, 2×15s sequential) with single `ddgs.text("site:naukri.com")` API call. Filters out non-job content (code360, blog, campus). Timeout reduced to 8s. Returns 6-44 jobs per query (was 0). |

---

## Branches

| Branch | Description |
|---|---|
| `main` | Primary branch |
| `add-ci-improvements/rishi` | CI pipeline improvements |
| `ux-improvements/rishi` | UX enhancements |
