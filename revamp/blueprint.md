# Matcha — Phase 2 Architectural Blueprint & Algorithmic Strategy

## Executive Summary

Restructure Matcha into a **3-layer resilient pipeline**: clean I/O scraper layer → error-aware orchestrator → rebalanced ranking engine. All changes are surgical refactors within the existing codebase — no new external services, no framework migrations.

The primary mandate is **algorithmic accuracy**: fix the scoring engine so the heuristic pass is a high-signal gatekeeper (not a noisy filter that drops great jobs), and the query expansion generates targeted, seniority-aware search terms.

---

## Architecture Decision Records

### ADR-1: Structured Logging via `logging` + Rich Console Separation
- **Problem:** 100% output via `console.print()` — no log levels, no file output, no debugging.
- **Decision:** `logging.getLogger(__name__)` per module. Rotating file handler in `~/.matcha/logs/`. TUI stays on Rich `Console` (stdout). Logs to stderr + file.
- **Zero new dependencies.** Stdlib only.

### ADR-2: Typed Error Recovery (Eliminate Silent Swallowing)
- **Problem:** 12+ locations `except: return []/None` — errors vanish silently.
- **Decision:** New `ScraperResult(jobs: list, errors: list[str])` dataclass. Every scraper returns it. `run_scraper` surfaces errors. Status table shows per-scraper error counts.
- **Principle:** One scraper failure must never block others. Isolation via `ScraperResult`.

### ADR-3: Heuristic Scoring Overhaul (Algorithmic Accuracy — Primary)
- **Problem:** Current scoring has 4 critical flaws that kill result quality:
  1. **Substring matching** — "aws" matches "awesome", "claws". Token-boundary matching needed.
  2. **80% skill weight drowns other signals** — Title (+10), seniority (0 — unimplemented!), location (+10) barely move the needle. A perfect title match with zero skill text gets ~15/100.
  3. **Seniority dimension defined but code is missing** — The dimension table lists 10% weight for seniority but `compute_relevance` has zero seniority logic.
  4. **Zero-score jobs silently filtered** — `prompt_loop:267` drops all jobs with `score == 0`. These never reach AI re-scoring.
- **Decision:** Rewrite with properly balanced, token-boundary-aware dimensions:

  | Dimension | Weight | Implementation |
  |-----------|--------|----------------|
  | Skills Match | 35% | Tokenized (word-boundary) matching. Ratio of profile skills found as whole words in job text. |
  | Title/Role Match | 25% | Token overlap between profile title and job title. Significantly increased from 10 → 25 pts. |
  | Experience/Seniority | 15% | **NEW.** Map experience years → level (entry/mid/senior/staff). Penalize both over- and under-qualification. |
  | Location Match | 15% | City-level, region-level, remote bonus. Increased from 10 → 15 pts. |
  | Keywords & Signals | 10% | Bonus for certifications, specific tools, technologies in description. |
  | **Floor** | **5 pts** | **Every job gets minimum 5 points. Zero-score elimination is removed.** |

- **Critical design change:** The heuristic pass now keeps ALL jobs visible. Jobs with low scores appear at the bottom of the TUI with "Low match" styling instead of being silently deleted. The AI pass top_n increases from 15 → 30 to catch more candidates.

### ADR-4: Query Expansion Quality Gate (Algorithmic Accuracy)
- **Problem:** AI generates 3-5 queries but has no quality validation. Near-duplicate queries waste scraper capacity. Query expansion can dilute relevance by generating overly broad terms.
- **Decision:** Add post-generation validation gate:
  1. **Semantic dedup** — rapidfuzz ratio > 85% between any two queries → merge/remove duplicate
  2. **Min-token validation** — Each query must have ≥2 significant tokens (exclude stop words)
  3. **Seniority-aware variants** — If profile has 4+ years exp, generate one senior-level query variant
  4. **Location injection** — Include location term in at least one generated query
  5. **Hard cap** — Maximum 5 unique queries (existing behavior, formalized)
- **Files:** `main.py:609-615` — post-processing block after `ai_generate_queries()`.

### ADR-5: 2-Pass Relevance Engine Critical Evaluation
- **Risk analysis:** The current heuristic pass can filter out excellent matches before AI sees them because:
  - 80% skill weight means a job with empty/no description (but perfect title + company) scores ~15
  - Substring matching creates false negatives ("aws" not found in job text but "AWS" actually required)
  - No seniority scoring means a "Principal Engineer" role gets same score as "Junior Developer"
  - Zero-score drop means the user never sees jobs the heuristic disliked
- **Mitigation:**
  1. New balanced weights (Skills 35%, Title 25%, Seniority 15%, Location 15%, Keywords 10%)
  2. Token-boundary matching for all skill comparisons
  3. Seniority scoring actually implemented (4 levels: entry, mid, senior, staff)
  4. Floor score = 5 (jobs appear in TUI regardless)
  5. AI top_n increased 15 → 30
  6. AI timeout reduced 300s → 60s for faster failover

### ADR-6: Secure Credential Storage
- **Problem:** `ai_key` and `serpapi_key` in plaintext JSON, world-readable.
- **Decision:** `keyring` library for OS-native credential storage (macOS Keychain, Linux Secret Service). `cryptography.fernet` fallback encrypted file. Non-secret config stays in JSON.
- **Rejected:** Custom encryption (key management is hard). Keyring is zero-config on macOS.
- **Blast radius:** `config.py` only. Secrets read via keyring. Non-secrets via JSON.

### ADR-7: Infrastructure Fixes
- **docker-compose.yml:** Fix YAML syntax (missing `volumes:` key, incorrect indentation).
- **.dockerignore:** Exclude `venv/`, `__pycache__/`, `.git/`, etc.
- **Indeed domain:** New config key `scrapers.indeed_domain` (default `in.indeed.com`). Passed through scraper chain.
- **Config validation:** Pydantic schema for both JSON and YAML configs.

### ADR-8: Rate Limiter Compliance
- **Problem:** `profile.py:246` uses bare `requests.get()`. All DDGS-based scrapers bypass rate limiter.
- **Decision:** Route LinkedIn profile scraping through `resilient_get()`. Add `_limiter.acquire("duckduckgo.com")` before all DDGS calls.
- **Files:** `profile.py:246`, `naukri.py`, `web_search.py`, `indeed.py:_search_indeed_via_ddgs`

### ADR-9: Shared Constants Extraction
- **Problem:** Identical ~50-word stop word sets duplicated across `indeed.py`, `naukri.py`, `remoteok.py`, `web_search.py` (~200 lines total).
- **Decision:** Extract all shared constants → `scrapers/constants.py`. Single source of truth.
- **Files:** NEW `scrapers/constants.py`. Remove duplicates from 4 scraper files.

### ADR-10: Fix Recursive Re-run
- **Problem:** `main()` calls `main()` on re-run → stack overflow after ~500 iterations.
- **Decision:** New top-level `run()` function with `while` loop.

### ADR-11: Fix Dedup Bug + Optimize
- **Problem:** Inverted company comparison condition (main.py:117-118). O(n²) scaling.
- **Decision:** Fix conditional. Add hybrid: exact hash pass first (O(n)), then fuzzy on remaining collisions (typically <10% of N).

---

## Implementation Phases

### Phase 1 — Pipeline Integrity (Foundation)
*Priority: Highest — must fix before accuracy improvements have effect*

| # | File | Change |
|---|------|--------|
| 1.1 | `main.py` | Replace recursive `main()` call → iterative `while` loop in `run()` |
| 1.2 | `scrapers/utils.py` | Add `ScraperResult` dataclass |
| 1.3 | All scrapers | Return `ScraperResult` instead of bare list |
| 1.4 | `main.py` | Update `run_scraper` and `search_jobs` to use `ScraperResult`. Surface errors in TUI status table. |
| 1.5 | All source files | Add `logger = logging.getLogger(__name__)`. Configure file+stderr handler in main entry point. |
| 1.6 | `scrapers/constants.py` (NEW) | Extract all stop words + job boilerplate + SKIP_DOMAIN_PARTS from 4 files. Update imports. |
| 1.7 | `main.py:104-128` | Fix inverted company comparison. Add hybrid O(n)+O(k²) optimization. |
| 1.8 | `docker-compose.yml` | Fix YAML syntax |
| 1.9 | `.dockerignore` (NEW) | Exclude venv, caches, git |

### Phase 2 — Algorithmic Accuracy (Core Value)
*Priority: Critical — the primary user-facing improvement*

| # | File | Change |
|---|------|--------|
| 2.1 | `matcher.py` | Full rewrite with balanced weights, token-boundary skill matching, seniority scoring, floor=5 |
| 2.2 | `main.py:267` | Remove `if s > 0` filter. Show all jobs, low scores dimmed. |
| 2.3 | `main.py:609-615` | Add query validation gate: semantic dedup, min-token, seniority-aware, location variants |
| 2.4 | `matcher.py` + `ai.py` | Increase AI top_n 15→30. Reduce timeout 300s→60s. Add in-memory AI result cache. |

### Phase 3 — Hardening & Security

| # | File | Change |
|---|------|--------|
| 3.1 | `config.py` | Add `keyring` credential storage. Add `cryptography.fernet` fallback. |
| 3.2 | `config.py` + `settings.py` | Pydantic schema validation for config loading |
| 3.3 | `profile.py:246` | Change `requests.get()` → `resilient_get()` |
| 3.4 | `naukri.py`, `web_search.py`, `indeed.py` | Add `_limiter.acquire("duckduckgo.com")` before DDGS calls |

### Phase 4 — Scale & Infra

| # | File | Change |
|---|------|--------|
| 4.1 | `scrapers/indeed.py`, `linkedin.py`, `serpapi_jobs.py` | Add pagination loop (configurable `max_pages`, default 2) |
| 4.2 | `scrapers/indeed.py`, `settings.py` | Make `indeed_domain` configurable. Pass through function chain. |
| 4.3 | `scrapers/__init__.py` | Add missing `search_indeed_jobs`, `resolve_indeed_url` exports |

---

## Data Model Changes

### New: `ScraperResult` (scrapers/utils.py)
```python
@dataclass
class ScraperResult:
    jobs: list[dict]
    errors: list[str]
```

### New: `scrapers/constants.py`
```python
STOP_WORDS: set[str] = { ... }       # single source from all 4 files
JOB_BOILERPLATE: set[str] = { ... }
SKIP_DOMAIN_PARTS: set[str] = { ... }
NON_JOB_TITLE_PATTERNS: list[str] = { ... }
NON_JOB_URL_PATTERNS: list[str] = { ... }
```

### Modified: settings.yaml schema
```yaml
search:
  query: string
  location: string
  days: int (default 7)
  max_pages: int (default 2, new)
ai:
  enabled: bool
  top_n: int (default 30, was 15)
  timeout: int (default 60, was 300)
scrapers:
  serpapi: bool
  indeed_domain: string (default "in.indeed.com", new)
```

---

## Failure Modes & Mitigation Matrix

| Failure | Impact | Mitigation |
|---------|--------|------------|
| Single scraper crashes | 0 jobs from that source | ADR-2: `ScraperResult.errors` logged + shown in TUI. Other scrapers unaffected. |
| AI API timeout (all calls) | AI re-scoring skipped | ADR-5: timeout 300s→60s. Graceful fallback to heuristic scores. |
| AI returns garbage JSON | Job keeps heuristic score | Existing `_extract_json` fallback. Log parse failure. |
| keyring unavailable | Can't store credentials securely | ADR-6: Fallback to encrypted file with loud warning. |
| Dedup on 1000+ jobs | ~2s instead of ~0.1s | ADR-11: Hybrid exact+fuzzy pass. |
| Recursive re-run loop | Stack overflow | ADR-10: Iterative `while` loop. |
| Indeed domain misconfigured | 0 results from Indeed | ADR-7: Validate domain format in settings. Log config error. |

---

## Blast Radius Analysis

| Change | Files Touched | Risk | Rollback Strategy |
|--------|--------------|------|-------------------|
| Recursive → iterative loop | main.py ~5 lines | Low | Revert single function |
| ScraperResult | 6 scraper files + main.py | Low | Keep old return path, wrap in adapter |
| Logging | All 20+ files | Low | Additive, no behavior change |
| Matcher rewrite | matcher.py only | Medium | Keep old as `compute_relevance_legacy` |
| Query validation | main.py ~15 lines | Low | Comment out block |
| Dedup fix | main.py ~10 lines | Low | Revert single commit |
| Keyring | config.py ~30 lines | Medium | Fallback path exists |
| Rate limiter | 3 scraper files + profile.py | Low | Remove acquire lines |
| Pagination | 3 scraper files | Medium | Revert per file |
| Constants extraction | 5 files | Low | Keep old constants as aliases |
| Config validation | config.py + settings.py | Low | Remove validation wrapper |

---

## Checkpoint: Phase 2 Complete

**Status:** Blueprint approved by user on 2026-06-08.
**Next:** Awaiting user confirmation to proceed to Phase 3 (Senior Staff Developer implementation).
**Drift risk:** None identified. All changes mapped to specific files with rollback strategies.
