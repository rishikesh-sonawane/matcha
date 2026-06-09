# Matcha — Phase 1 System Instructions & Structural Breakdown

## Overview

Matcha is a Python terminal application (TUI) that aggregates job listings from multiple sources, ranks them by relevance to a user's professional profile, and displays them in an interactive, color-coded terminal interface. It uses a two-pass relevance engine (heuristic + optional AI via Kilo Gateway) and supports three methods of profile entry (PDF resume, LinkedIn URL, manual).

## System Architecture

```
Profile Entry (profile.py) → Query Expansion (ai.py) → Parallel Scraping (scrapers/*)
→ Deduplication (main.py:deduplicate) → Heuristic Scoring (matcher.py)
→ AI Re-scoring (ai.py → matcher.py) → Interactive TUI (main.py:prompt_loop)
```

State is managed across 4 persistence layers:
- `~/.matcha/config.json` — API keys, last query/location/days
- `~/.matcha/profile.json` — saved profile dict
- `./matcha.yaml` / `~/.matcha/settings.yaml` — user-facing YAML settings
- `~/.matcha/jobs.db` — SQLite job lifecycle (saved/applied/dismissed/etc.)

## Data Flow

1. **Profile Ingestion** — PDF resume (pdfplumber + AI), LinkedIn URL (direct scrape + DDG fallback), or manual entry → AI-extracted profile dict
2. **Query Expansion** — Base query + AI-generated variant queries targeting adjacent roles (3-5 total)
3. **Parallel Scraping** — ThreadPoolExecutor dispatches all queries × all scrapers concurrently (max 12 workers)
4. **Deduplication** — rapidfuzz token_sort_ratio + token_set_ratio on (title, company) pairs
5. **Heuristic Scoring** — 5 dimensions (title 20%, skills 35%, keywords 15%, seniority 10%, location 8%) → clamped [0, 100]
6. **AI Re-scoring** — Top 15 jobs re-scored by LLM with structured JSON output (parallel, max 8 workers, 300s timeout)
7. **Interactive TUI** — Paginated table (10/page), keyboard navigation, detail panel, save/open

## Source Files

| File | Lines | Role |
|------|-------|------|
| `main.py` | 631 | CLI entry point, orchestration, TUI |
| `profile.py` | 415 | Profile ingestion (PDF, LinkedIn, manual) |
| `ai.py` | 340 | AI provider client (Kilo Gateway) |
| `matcher.py` | 59 | Two-pass relevance scoring |
| `config.py` | 39 | JSON config persistence |
| `settings.py` | 48 | YAML config loader |
| `actions.py` | 120 | SQLite job lifecycle |
| `models.py` | 52 | Pydantic v2 models (unused at runtime) |
| `scrapers/utils.py` | 96 | HTTP client, rate limiter, cache |
| `scrapers/indeed.py` | 332 | Indeed India (cloudscraper + DDG fallback) |
| `scrapers/linkedin.py` | 85 | LinkedIn guest API |
| `scrapers/naukri.py` | 297 | Naukri via DDGS API |
| `scrapers/remoteok.py` | 125 | RemoteOK public API |
| `scrapers/serpapi_jobs.py` | 106 | Google Jobs via SerpAPI (optional) |
| `scrapers/web_search.py` | 429 | DuckDuckGo job board search |
| `scrapers/__init__.py` | 6 | Re-exports (missing indeed) |

## Key Dependencies

requests, requests-cache, beautifulsoup4, rich, cloudscraper, ddgs, pdfplumber, prompt_toolkit, rapidfuzz, pydantic, pyyaml, python-dotenv

## Critical Pain Points Identified

### Critical (Blocks Production)
1. **Silent error black hole** — 12+ locations catch `Exception` and return `[]`/`None`. No logging framework.
2. **O(n²) dedup with inverted company logic** — `deduplicate()` main.py:117-118: when either company field is empty, uses wrong comparison function.
3. **Recursive re-run crashes** — `main()` calls `main()` → eventual stack overflow.
4. **API keys in plaintext** — `~/.matcha/config.json` stores `ai_key`, `serpapi_key` unencrypted. No file permissions.
5. **docker-compose.yml broken** — YAML syntax error prevents building.
6. **No scraper pagination** — Every scraper fetches only page 1.

### High Severity
7. **Indeed hardcoded to India** — `in.indeed.com` in 5+ locations.
8. **LinkedIn profile scrape bypasses rate limiter** — uses bare `requests.get()`, not `resilient_get()`.
9. **DDGS scrapers bypass rate limiter** — Naukri, Indeed fallback, Web Search all use DDGS directly.
10. **Pydantic models defined but never used** — all runtime code uses raw dicts.
11. **Two overlapping config systems** — JSON vs YAML, no schema validation.
12. **Duplicate stop words (~200 lines)** — identical sets in 4 files.
13. **AI provider hardcoded** — Kilo Gateway only, confusing env var `MINIMAX`.
14. **300s AI timeout** — blocks workers for 5 minutes.

### Medium Severity
15. `scrapers/__init__.py` missing indeed exports.
16. Zero scraper tests, zero orchestration tests.
17. `actions.py`, `config.py`, `settings.py` untested.
18. RemoteOK loads all ~1000+ jobs then filters in-memory.
19. Duplicated company extraction logic in naukri.py and web_search.py.
20. Jobs with score 0 silently dropped (main.py:267).
21. Profile `title` and `headline` often identical.
22. No `--export`, `--version`, `--health` CLI flags.

## Hypothesis: Pain Point Root Causes

- **"App feels fragile / breaks silently"** → Silent Exception swallowing in 12+ locations + zero structured logging. Any scraper failure, AI timeout, or parsing error vanishes.
- **"Slow with many results"** → O(n²) dedup on 200-500 jobs × fuzzy matching + no scraper pagination hiding true throughput bottleneck.
- **"Security concerns"** → Plaintext API keys in world-readable JSON.
- **"Doesn't find enough jobs"** → No pagination. India-locked Indeed. 10-result LinkedIn API.
- **"Hard to know if it's working"** → No logging, health metrics, or error surfacing.
- **"Results quality is poor"** → Heuristic scoring uses substring matching ("aws" matches "claws"), 80% weight on skills drowns title/location signals, seniority dimension defined but unimplemented. Zero-score filter drops potentially good jobs before AI re-scoring.
