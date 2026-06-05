# Job Finder — Project Context

## Overview

Job Finder is a Python terminal application (TUI) that aggregates job listings from multiple sources, ranks them by relevance to a user's professional profile, and displays them in an interactive, color-coded terminal interface. It uses a two-pass relevance engine (heuristic + optional AI via Kilo Gateway) and supports three methods of profile entry (PDF resume, LinkedIn URL, manual).

---

## Tech Stack

| Technology | Purpose |
|---|---|
| Python 3.9+ | Runtime |
| Rich | Terminal UI (tables, panels, progress bars, live display) |
| prompt_toolkit | Interactive TUI navigation, keyboard bindings, full-screen mode |
| requests | HTTP client for all scrapers |
| beautifulsoup4 | HTML parsing for all scrapers |
| cloudscraper | Cloudflare bypass for Indeed India |
| pdfplumber | PDF text extraction for resumes |
| rapidfuzz | Fuzzy string matching for deduplication |
| ruff | Python linter and formatter |
| pre-commit | Git pre-commit hooks |
| Docker | Containerization (python:3.11-slim, multi-stage, non-root user UID 10001) |
| GitHub Actions | CI/CD (lint, format, test, Docker build/push to GHCR) |

## Python Dependencies

```
requests>=2.28.0
beautifulsoup4>=4.11.0
rich>=13.0.0
python-dotenv>=1.0.0
pdfplumber>=0.10.0
cloudscraper>=1.2.71
rapidfuzz>=3.0.0
prompt_toolkit>=3.0.0
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
├── actions.py                        # Save/unsave/load jobs (JSON persistence in ~/.job-finder/saved.json)
├── ai.py                             # AI client for Kilo Gateway (profile extraction, query gen, job scoring)
├── config.py                         # Persistent JSON config in ~/.job-finder/ (config.json, profile.json)
├── docker-compose.yml                # Docker Compose with MINIMAX/SERPAPI_KEY env vars, persistent config volume
├── kilo.md                           # This file — project context for AI agents
├── main.py                           # CLI entry point, orchestration, TUI (prompt_toolkit + Rich), 552 lines
├── matcher.py                        # Two-pass relevance scoring (heuristic + AI wrapper), 202 lines
├── profile.py                        # Profile ingestion via PDF, LinkedIn, or manual, 577 lines
├── pyproject.toml                    # Ruff config (line-length 100, target py39), pytest config
├── requirements.txt                  # 8 dependencies
├── scrapers/
│   ├── __init__.py                   # Re-exports from linkedin, naukri, remoteok, serpapi_jobs, web_search
│   ├── indeed.py                     # Indeed India scraper (cloudscraper + URL resolution), 115 lines
│   ├── linkedin.py                   # LinkedIn guest API scraper, 74 lines
│   ├── naukri.py                     # Naukri via DuckDuckGo search, 109 lines
│   ├── remoteok.py                   # RemoteOK public API scraper, 114 lines
│   ├── serpapi_jobs.py              # Google Jobs via SerpAPI (optional), 88 lines
│   ├── utils.py                      # resilient_get() with retry logic, 27 lines
│   └── web_search.py                 # DuckDuckGo web search with job board filtering, 213 lines
└── tests/
    ├── __init__.py
    └── test_core.py                  # 275 lines, 6 test classes, 24 test methods (unittest)
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
python3 main.py                          # Normal flow
python3 main.py --configure              # Set SerpAPI + AI API keys
python3 main.py --new-profile / -n       # Re-enter profile from scratch
python3 main.py --help                   # Help
```

---

## All Source Files — Detailed Breakdown

### main.py (552 lines) — Orchestrator + TUI

**Key functions:**
- `configure_serpapi()` — interactive SerpAPI key setup
- `configure_ai()` — interactive AI API key setup
- `run_scraper(name, scraper_func, query, location)` — wraps scraper call in try/except
- `_normalize(text)` — lowercase + strip roman numerals/seniority abbrev + remove punctuation + collapse whitespace
- `deduplicate(jobs, title_threshold=82, company_threshold=88)` — rapidfuzz fuzzy dedup
- `search_jobs(queries, location)` — parallel scrape across all sources × all queries, live Rich table
- `rank_jobs(jobs, profile, use_ai=False)` — heuristic ranking + optional AI re-scoring of top 15
- `build_results_table(ranked, page, page_size, total_pages, ai_enabled, saved_ids, highlight)` — Rich Table for results
- `show_job_detail(job, score, reasons)` — Rich Panel for job details
- `prompt_loop(ranked, source_counts, ai_enabled)` — full interactive TUI with prompt_toolkit Application
  - **Modes:** "list", "detail", "saved"
  - **Key bindings:** up/down (navigate), enter (detail), s (save/unsave), o (open in browser), n/p (next/prev page), l (saved list), r (re-run), q (quit)
  - State tracked via simple `State` class with: `page`, `selected`, `mode`, `detail_idx`, `re_run`

**SCRAPER_DEFS dict (line 37-43):**
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

### profile.py (577 lines) — Profile Ingestion

**Key functions:**
- `suggest_title(skills)` — maps skills → job title using SKILL_TO_TITLE_MAP (17 mappings)
- `extract_experience(text_lower)` — regex extraction of years from free text
- `parse_resume_pdf(path)` — pdfplumber extraction + regex keyword detection (40+ tech keywords) + optional AI enhancement
- `scrape_linkedin_profile(url)` — direct LinkedIn page scrape, falls back to `search_linkedin_profile_via_web()` via DuckDuckGo
- `search_linkedin_profile_via_web(username)` — DuckDuckGo search fallback for LinkedIn profile gathering
- `manual_profile_entry()` — interactive prompts for all profile fields
- `build_or_load_profile(force_new=False)` — orchestrator: check saved → choose method → fallback chain

**SKILL_TO_TITLE_MAP (17 entries):** Backend Developer, ML Engineer, AI Engineer, Data Analyst, Data Engineer, DevOps Engineer, Cloud Engineer, Frontend Developer, Full Stack Developer, Java Developer, Go Developer, Systems Engineer, Product Manager

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

### ai.py (262 lines) — AI Client

**Provider:** Kilo Gateway (`https://api.kilo.ai/api/gateway/chat/completions`, model `kilo-auto/small`)
**Auth:** Bearer token from `$MINIMAX` env var or `config.json` `ai_key` field
**Config key:** `ai_key`, **Env var:** `MINIMAX`
**Temperature:** 0.1 (hardcoded)

**Functions:**
- `_get_api_key()` — env var > config file
- `check_ai_available()` — bool if key present
- `configure_ai(key)` — save key to config
- `_call_ai(messages, response_format, max_tokens=500)` — POST to Kilo Gateway, 30s timeout
- `_extract_json(text)` — parse JSON from LLM response (handles ```json blocks, embedded JSON, plain JSON)
- `ai_extract_profile(text)` — resume enrichment via `PROFILE_EXTRACTION_PROMPT`
- `ai_generate_queries(profile)` — 3-5 expanded search queries via `QUERY_GENERATION_PROMPT`
- `ai_score_job(profile, job)` — structured job scoring via `JOB_SCORING_PROMPT` (0-100 + reasons)

---

### config.py (38 lines) — File-based Config

**Directory:** `~/.job-finder/` (auto-created)
**Files:**
- `config.json` — `{ai_key, serpapi_key, last_query, last_location}`
- `profile.json` — saved profile dict

**Functions:** `load_config()`, `save_config()`, `load_profile()`, `save_profile()`

---

### actions.py (54 lines) — Job Bookmarks

**File:** `~/.job-finder/saved.json`
**Data shape:** `{url: {title, company, url, source}}`
**Functions:** `load_saved_jobs()`, `is_job_saved(url, saved_ids)`, `save_job(job, saved_ids)`, `unsave_job(url, saved_ids)`

---

## Scrapers — Detailed

### scrapers/indeed.py (115 lines)
- **Target:** `in.indeed.com` (India)
- **Method:** cloudscraper with HTML parsing
- **URL resolution:** `resolve_indeed_url()` decodes `rc/clk` and `pagead/clk` tracking URLs → clean `viewjob?jk=` URLs
- **Selectors:** `.job_seen_beacon`, `[data-jk]`, `h3.jobTitle a`, `[data-testid=company-name]`, `[data-testid=text-location]`

### scrapers/linkedin.py (74 lines)
- **Target:** LinkedIn guest API
- **Endpoint:** `/jobs-guest/jobs/api/seeMoreJobPostings/search?keywords=...&location=...&f_TPR=r86400`
- **Method:** requests + BeautifulSoup, parses `<li>` job cards
- **Filter:** Past 24 hours (`f_TPR=r86400`)

### scrapers/naukri.py (109 lines)
- **Target:** Naukri.com (via DuckDuckGo)
- **Method:** Searches `html.duckduckgo.com` for `naukri.com {query}` and `naukri {query}`
- **Fallback:** Only gets search result snippets, not full job listings
- **Helper functions:** `clean_title()`, `build_job()`, `extract_url()` (DDG redirect resolver)

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

### scrapers/utils.py (27 lines)
- `resilient_get(url, session, **kwargs)` — 3 retries, exponential backoff (1s, 2s, 4s), retry on {429, 502, 503, 504}, ConnectionError, Timeout

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
| DuckDuckGo | `html.duckduckgo.com/html/` | None | Free (for Naukri, web search, LinkedIn fallback) |

---

## Configuration (Persistent)

**Config directory:** `~/.job-finder/` (auto-created)
**Config files:**
- `config.json` — `{ai_key, serpapi_key, last_query, last_location}`
- `profile.json` — `{name, title, headline, skills, experience, summary}`
- `saved.json` — `{url: {title, company, url, source}}`

**Hardcoded settings:**
- AI model: `kilo-auto/small`, API URL: `https://api.kilo.ai/api/gateway/chat/completions`, temp: 0.1
- Indeed domain: `in.indeed.com` (India-only)
- Page size: 10, AI scoring top N: 15, max scraper workers: 12, max AI workers: 8
- HTTP timeouts: 15-20s
- Dedup thresholds: title 82%, company 88%
- Retry: 3 attempts, backoff 1s/2s/4s, on {429,502,503,504} + ConnectionError + Timeout

---

## Testing

**Framework:** Python `unittest` (stdlib)
**File:** `tests/test_core.py` (275 lines)
**Run:** `python -m unittest tests.test_core -v`

**Test classes (24 methods total):**
| Class | Tests | What it covers |
|---|---|---|
| TestNormalize | 6 | `_normalize()` — lowercase, roman numerals, seniority abbrev, punctuation, whitespace, empty |
| TestDeduplicate | 8 | `deduplicate()` — exact, roman vs digit, reordering, different jobs, company variants, sr/senior, empty fields, no duplicates |
| TestTokenize | 5 | `tokenize()` — basic, lowercase, numbers, empty, special chars |
| TestComputeRelevance | 5 | `compute_relevance()` — perfect match, no match, partial, reasons, bounds |
| TestResolveIndeedURL | 6 | `resolve_indeed_url()` — rc/clk, clean URL, non-indeed, pagead/clk, no jk param, empty |
| TestSuggestTitle | 5 | `suggest_title()` — devops/backend/frontend skills, empty, unrecognized |
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

## Data Schemas (informal dicts, no dataclasses/Pydantic)

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
2. **No type hints anywhere** — no mypy, no Pydantic, no dataclasses
3. **No logging framework** — all output via `console.print()` mixed with Rich UI
4. **API keys in plaintext** — stored in `~/.job-finder/config.json` unencrypted
5. **India-centric** — Indeed hardcoded to `in.indeed.com`
6. **LinkedIn scraper fragility** — guest API could break without notice, returns ~10 results
7. **Naukri scraper is shallow** — only gets DuckDuckGo search snippets, not full listings
8. **No HTTP caching** — re-scrapes everything every run
9. **No rate limiting** — could get IP banned with aggressive usage
10. **No web server or API** — pure terminal app, no frontend framework
11. **No state management library** — plain Python dicts + JSON file persistence
12. **No user accounts or authentication** — single-user local app
13. **deduplicate() has edge case in company matching** — line 103-105: when `norm_company` or `s_company` is empty, uses `token_sort_ratio` instead of `token_set_ratio` (logic may be inverted — currently uses `token_set_ratio` when BOTH non-empty, `token_sort_ratio` when either is empty)
14. **deduplicate() doesn't filter done/dead sources** — if a scraper errors, `run_scraper` returns `[]` silently
15. **AI dependency on single provider** (Kilo Gateway) — no fallback
16. **Profile `title` and `headline` often identical** — `headline` defaults to `title` in multiple code paths
17. **Jobs with score 0 are silently filtered** in `prompt_loop` line 267
18. **FuturePlan.txt** contains 25+ planned enhancements (tests, type hints, logging, rate limiting, caching, proxy rotation, config encryption, SQLite job tracking, scheduled mode, more scrapers, fuzzy dedup, health monitoring, profile merge, retry with tenacity, YAML config, better LinkedIn scraping)

---

## Branches

| Branch | Description |
|---|---|
| `main` | Primary branch |
| `add-ci-improvements/rishi` | CI pipeline improvements |
| `ux-improvements/rishi` | UX enhancements |
