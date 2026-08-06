# OpenCLI Integration Plan: Matcha + OpenCLI

## Overview

**Matcha** is a Python CLI job aggregator with AI-powered relevance ranking. **OpenCLI** is a Node.js toolkit that drives real browsers to interact with any website as if it were an API. Together, they enable end-to-end job search, enrichment, and application automation.

This document outlines the integration architecture, phased delivery, data model changes, and risk analysis.

> **Status: superseded-but-adopted** by `matcha-2.0-strategy.md` (Rev 3). The
> strategy doc §6.3 and §6.8 carry the **verified** OpenCLI details — in
> particular, health checks must never run `opencli doctor` (it auto-starts the
> daemon); probe `opencli --version` + the loopback daemon `/status` endpoint
> instead. Treat this file as historical background only.

---

## 0. Why OpenCLI?

### Problem statement

Matcha's two highest-value scrapers — LinkedIn and Indeed — are its weakest:
- **LinkedIn** uses an unauthenticated guest API capped at ~10 results, no descriptions, no apply URLs
- **Indeed India** relies on `cloudscraper` (breaks on Python 3.14) or DDGS fallback (noisy, low yield)
- **No scraper** returns `apply_url`, full descriptions, salary, workplace type, or company metadata
- **No path** to automating job applications from the terminal

### ROI summary

| Phase | Effort | Impact |
|---|---|---|
| Phase 1: Scraper replacement | ~200 lines wrapper code | LinkedIn yield 5–10x, Indeed reliable again |
| Phase 2: Enrichment | ~150 lines + model changes | Full descriptions + apply URLs in TUI |
| Phase 3: Application automation | ~300 lines + profile changes | "Search and apply from terminal" — new capability |

All three phases degrade gracefully: if OpenCLI isn't installed, Matcha works exactly as it does today.

---

## 1. Current State

### Matcha (Python)

| Capability | Status |
|---|---|
| Profile ingestion (manual, PDF, LinkedIn URL) | Done |
| Multi-source job search (LinkedIn, Indeed, Naukri, RemoteOK, Web Search, Google Jobs) | Done |
| Deduplication via `rapidfuzz` | Done |
| Two-pass relevance scoring (heuristic + AI/LLM) | Done |
| Interactive TUI (browse, save, open in browser) | Done |
| Saved jobs database (SQLite) with status workflow | Done |
| Non-interactive YAML-driven mode | Done |
| Docker packaging | Done |

**Scraper limitations:**
- LinkedIn scraper uses guest API — limited results (~10), no auth
- Indeed scraper uses `cloudscraper` or DDGS fallback — flaky, low yield
- Naukri scraper uses DDGS — indirect, noisy
- Web Search scraper uses DDGS — limited depth
- No scraper returns `apply_url` or full job descriptions
- No capability to submit applications

### OpenCLI (Node.js)

| Capability | Status |
|---|---|
| Browser automation (click, type, fill, select, state, eval, upload) | Mature |
| `linkedin search` — authenticated, high-yield job search | Done |
| `linkedin job-detail` — full description, apply URL, company metadata | Done |
| `linkedin job-detail` — returns `apply_url` (Easy Apply or external redirect) | Done |
| `indeed search` — browser-based, bypasses Cloudflare | Done |
| `indeed job` — full job detail | Done |
| `opencli browser` — drive any website dynamically | Done |
| Session management, tab control, network capture | Done |
| Compound form controls (date, select, file upload, checkboxes) | Done |
| No existing `apply` adapter | Gap |

---

## 2. Integration Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                          Matcha (Python)                          │
│                                                                    │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────────┐ │
│  │  Profile  │  │ Scrapers │  │  Matcher │  │   Actions DB     │ │
│  │  Engine   │  │  (5+ src)│  │(heur+AI) │  │  (SQLite saves)  │ │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────────┬─────────┘ │
│       │              │             │                  │           │
│  ┌────┴──────────────┴─────────────┴──────────────────┴──────┐   │
│  │              Orchestration Layer (main.py)                  │   │
│  │  - Query expansion  - Parallel scraping  - Ranking  - TUI  │   │
│  └────────────────────────────┬───────────────────────────────┘   │
│                               │ subprocess.run() with -f json    │
└───────────────────────────────┼───────────────────────────────────┘
                                │
┌───────────────────────────────┼───────────────────────────────────┐
│                    OpenCLI (Node.js)                               │
│                               │                                    │
│  ┌────────────────────────────┴──────────────────────────────┐   │
│  │                CLI Dispatcher                               │   │
│  │  opencli linkedin search ... -f json                        │   │
│  │  opencli linkedin job-detail ... -f json                    │   │
│  │  opencli browser <session> open/state/click/type/fill       │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                               │                                    │
│  ┌────────────────────────────┴──────────────────────────────┐   │
│  │              Browser Bridge (Chrome + Extension)            │   │
│  │  - Authenticated sessions (LinkedIn login via cookies)      │   │
│  │  - DOM interaction via CDP                                  │   │
│  │  - Network capture for API responses                        │   │
│  └─────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────┘
```

### Design decisions

These decisions were made during the design review and should be preserved during implementation:

| Decision | Choice | Rationale |
|---|---|---|
| **Integration approach** | Phased (Approach A) — incremental, no refactoring of existing scrapers | The existing `SCRAPER_DEFS` dict makes scraper swapping trivial. No need for abstract base classes or parallel pipelines. |
| **Scope** | All 3 phases | Scraper replacement alone doesn't unlock the full value. Enrichment + apply automation are where OpenCLI differentiates. |
| **Fallback behavior** | Auto-detect, warn on fallback | If OpenCLI not found, print a one-time warning at startup suggesting `npm install -g @jackwener/opencli`, then use existing scrapers silently. User isn't nagged per-run. |
| **LinkedIn auth** | Prompt on first use, fallback if declined | First time OpenCLI LinkedIn is used, ask: "Use your logged-in Chrome for LinkedIn? This will give 5-10x more results. (y/n)". If no, remember the choice in config and fall back to guest API. |
| **Existing scrapers** | Kept as fallbacks, never deleted | OpenCLI may not be available (no Node.js, no Chrome, user declined). Existing scrapers remain the safe default. |
| **Enrichment scope** | LinkedIn jobs only initially | `opencli linkedin job-detail` is mature. Indeed enrichment is lower priority and can be added later. |

### Communication Protocol

Matcha calls OpenCLI via `subprocess.run()` with JSON output:

```python
import subprocess, json

def opencli(*args: str) -> dict | list:
    result = subprocess.run(
        ["opencli", *args, "-f", "json"],
        capture_output=True, text=True, timeout=120
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr)
    return json.loads(result.stdout)
```

**Why subprocess over SDK:** OpenCLI has no stable Python SDK. Subprocess is the documented integration surface and guarantees compatibility across updates. The JSON output format is explicitly designed for machine consumption.

---

## 3. Data Model Changes

### Current `Job` model (models.py)

```python
class Job(BaseModel):
    title: str = ""
    company: str = ""
    location: str = ""
    description: str = ""
    url: str = ""
    source: str = ""
```

### Proposed `Job` model

```python
class Job(BaseModel):
    title: str = ""
    company: str = ""
    location: str = ""
    description: str = ""          # Full description (from job-detail)
    url: str = ""                  # LinkedIn/Indeed search URL
    source: str = ""
    apply_url: str = ""            # NEW: Easy Apply or external redirect URL
    workplace_type: str = ""       # NEW: remote/hybrid/on-site
    job_type: str = ""             # NEW: full-time/contract/etc
    salary: str = ""               # NEW: salary range if available
    listed_date: str = ""          # NEW: posting date
    company_url: str = ""          # NEW: company LinkedIn page
    applicants: str = ""           # NEW: applicant count
```

### Proposed `Profile` additions

```python
class Profile(BaseModel):
    name: str = ""
    title: str = ""
    headline: str = ""
    skills: list[str] = []
    experience: str = ""
    summary: str = ""
    location: str = ""
    # NEW fields for application automation
    phone: str = ""
    email: str = ""
    preferred_locations: list[str] = []
    remote_preference: str = ""    # remote/hybrid/on-site
    min_salary: int = 0
    max_salary: int = 0
    notice_period: str = ""
    linkedin_url: str = ""
    github_url: str = ""
```

### Proposed `SavedJob` table additions

```sql
-- Current schema
CREATE TABLE IF NOT EXISTS jobs (
    url TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    company TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'saved',
    saved_at TEXT NOT NULL,
    applied_at TEXT,
    notes TEXT DEFAULT ''
);

-- Additional columns needed
ALTER TABLE jobs ADD COLUMN apply_url TEXT DEFAULT '';
ALTER TABLE jobs ADD COLUMN workplace_type TEXT DEFAULT '';
ALTER TABLE jobs ADD COLUMN salary TEXT DEFAULT '';
ALTER TABLE jobs ADD COLUMN company_url TEXT DEFAULT '';
```

### Proposed status additions

```python
VALID_STATUSES = {
    "saved", "applied", "dismissed", "interview", "rejected", "offer",
    "applying",       # NEW: browser application in progress
    "apply_failed",   # NEW: application attempt failed
    "apply_external", # NEW: opened external URL for manual apply
}
```

---

## 4. Phase 1: Replace Scrapers with OpenCLI

### Goal

Replace LinkedIn and Indeed scrapers with OpenCLI's authenticated, browser-backed commands for higher yield and richer data. The other three scrapers (Naukri, RemoteOK, Web Search) are kept as-is — they work well and have no OpenCLI adapter.

### New scraper modules

```
scrapers/
  opencli_linkedin.py    # Wraps: opencli linkedin search <query> [options]
  opencli_indeed.py      # Wraps: opencli indeed search <query> [options]
```

### Scraper implementations

```python
# scrapers/opencli_linkedin.py
import subprocess, json, logging
from models import ScraperResult

logger = logging.getLogger(__name__)

def search_linkedin_jobs(query: str, location: str = "", days: int = 7,
                         max_pages: int = 2, **kwargs) -> ScraperResult:
    try:
        cmd = ["opencli", "linkedin", "search", query, "-f", "json"]
        if location:
            cmd += ["--location", location]
        cmd += ["--date-posted", _map_days(days)]
        cmd += ["--limit", str(max_pages * 25)]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            return ScraperResult(errors=[result.stderr.strip()], source="LinkedIn(OpenCLI)")

        jobs = json.loads(result.stdout)
        return ScraperResult(
            jobs=[{
                "title": j.get("title", ""),
                "company": j.get("company", ""),
                "location": j.get("location", ""),
                "url": j.get("url", ""),
                "source": "LinkedIn",
                "salary": j.get("salary", ""),
                "listed": j.get("listed", ""),
            } for j in jobs],
            source="LinkedIn(OpenCLI)"
        )
    except subprocess.TimeoutExpired:
        return ScraperResult(errors=["OpenCLI timed out"], source="LinkedIn(OpenCLI)")
    except Exception as e:
        logger.exception("OpenCLI LinkedIn search failed")
        return ScraperResult(errors=[str(e)], source="LinkedIn(OpenCLI)")

def _map_days(days: int) -> str:
    if days <= 1: return "24h"
    if days <= 7: return "week"
    if days <= 30: return "month"
    return "any"
```

### Startup probe

```python
OPENCLI_AVAILABLE: bool = False
OPENCLI_LINKEDIN_CONSENT: bool = False  # loaded from config

def _probe_opencli() -> bool:
    """Check if opencli is installed and functional."""
    try:
        r = subprocess.run(["opencli", "--version"], capture_output=True, timeout=5)
        return r.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
```

On startup, `_probe_opencli()` runs once. If it returns `False`, print a one-time warning:
```
[i] OpenCLI not found. Install with: npm install -g @jackwener/opencli
    OpenCLI enables 5-10x more LinkedIn results, job descriptions, and apply URLs.
    Falling back to built-in scrapers.
```

### LinkedIn auth consent

LinkedIn requires the user's browser session. First time OpenCLI LinkedIn scraping is needed, prompt:

```
OpenCLI can use your logged-in Chrome to search LinkedIn.
This gives 25-100 results per query (vs ~10 now).
Use Chrome for LinkedIn? (y/N):
```

If `y`: set `OPENCLI_LINKEDIN_CONSENT = True`, save to config, register OpenCLI LinkedIn scraper.

If `n`: set `OPENCLI_LINKEDIN_CONSENT = False`, save to config, keep existing LinkedIn scraper. User can re-enable later via config.

### SCRAPER_DEFS update

```python
# Existing scrapers (unchanged)
SCRAPER_DEFS = {
    "LinkedIn": search_linkedin_jobs_original,
    "Indeed": search_indeed_jobs_original,
    "Naukri": search_naukri_jobs,
    "RemoteOK": search_remoteok_jobs,
    "Web Search": search_web_for_jobs,
}

# Conditionally upgrade to OpenCLI versions
if OPENCLI_AVAILABLE:
    SCRAPER_DEFS["Indeed"] = opencli_indeed_jobs

if OPENCLI_AVAILABLE and OPENCLI_LINKEDIN_CONSENT:
    SCRAPER_DEFS["LinkedIn"] = opencli_linkedin_jobs
```

This keeps the existing scraper functions as named fallbacks (imported with `_original` suffix or from their module directly), and only replaces them when OpenCLI is available and consented.

### Benefits

| Metric | Before | After |
|---|---|---|
| LinkedIn results per query | ~10 (guest API) | 25-100 (authenticated) |
| Indeed reliability | Flaky (Cloudflare/DDGS) | Stable (browser) |
| LinkedIn data per result | title, company, location | +salary, listed_date |
| Indeed data per result | title, company, location | +salary, tags |
| LinkedIn requires login? | No | Yes (but richer) |

### Risk: OpenCLI not installed

Handled by the startup probe above. If OpenCLI is absent, the original `SCRAPER_DEFS` entries remain in place and everything works exactly as before. The only difference is a one-time informational message recommending installation.

---

## 5. Phase 2: Enrich with Job Details

### Goal

After search, enrich top-ranked jobs with full descriptions + apply URLs using `opencli linkedin job-detail`.

### New module

```
enricher.py   # Enriches jobs with full detail from OpenCLI
```

### Implementation

```python
# enricher.py
import subprocess, json, logging
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger(__name__)

def enrich_job(job: dict) -> dict:
    url = job.get("url", "")
    if not url or "linkedin.com/jobs" not in url:
        return job  # Only LinkedIn jobs can be enriched

    try:
        result = subprocess.run(
            ["opencli", "linkedin", "job-detail", url, "-f", "json"],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode != 0:
            return job

        detail = json.loads(result.stdout)
        if isinstance(detail, list) and len(detail) > 0:
            detail = detail[0]

        job["description"] = detail.get("description", job.get("description", ""))
        job["apply_url"] = detail.get("apply_url", "")
        job["workplace_type"] = detail.get("workplace_type", "")
        job["job_type"] = detail.get("job_type", "")
        job["applicants"] = detail.get("applicants", "")
        job["company_url"] = detail.get("company_url", "")
        job["listed"] = detail.get("listed", job.get("listed", ""))
    except Exception as e:
        logger.warning("Failed to enrich %s: %s", url, e)

    return job


def enrich_top_jobs(jobs: list[dict], top_n: int = 30) -> list[dict]:
    """Enrich the top N jobs with full details."""
    with ThreadPoolExecutor(max_workers=min(top_n, 5)) as executor:
        futures = {executor.submit(enrich_job, j): i for i, j in enumerate(jobs[:top_n])}
        enriched = list(jobs)  # copy
        for f in as_completed(futures):
            i = futures[f]
            enriched[i] = f.result()
    return enriched
```

### Integration in `rank_jobs()`

```python
def rank_jobs(jobs, profile, use_ai=False, enrich=False, ...):
    # 1. heuristic scoring all jobs
    # 2. AI scoring top 30
    # 3. Enrich top N with full details (NEW)
    if enrich and check_opencli_available():
        jobs = enrich_top_jobs(ranked, top_n=30)
    # 4. Return ranked + enriched
```

### TUI display

Show enriched fields in detail panel:

```
Job Details
─────────────────────────────────
Title: Senior DevOps Engineer
Company: Cisco
Location: Pune (On-site)
Apply: https://www.linkedin.com/jobs/view/...
Apply URL: https://jobs.cisco.com/...        # External
Salary:                                      # If available
Posted: 2026-06-18
Applicants: Over 100
─────────────────────────────────
Description: ...
```

### Saved jobs integration

When user presses `s` to save, also store `apply_url`, `workplace_type`, `salary` in SQLite.

---

## 6. Phase 3: Application Automation

### Goal

Apply to jobs from within the TUI using OpenCLI browser driving.

### Workflows

**Easy Apply** (in-page LinkedIn modal):
1. `opencli browser <session> open <job-url>`
2. `opencli browser <session> state` — detect "Easy Apply" button
3. `opencli browser <session> click <ref>` — click Easy Apply
4. Loop: `state` → detect fields → `fill`/`type`/`select` → click "Next"
5. Click "Submit" after review stage

**External Apply** (redirects to Greenhouse/Lever/Workday/etc):
1. `opencli browser <session> open <apply-url>`
2. `state` → detect form fields
3. Bulk-fill via one `browser eval` call with profile data
4. Handle CAPTCHA by notifying user
5. Click submit

### Architecture

```
actions.py                       # Existing: save/unsave/set_status
  └── apply_to_job(url, profile)  # NEW: orchestrates application

applicator.py                    # NEW: browser-based application driver
  ├── prepare_session()          # Create/open browser session
  ├── detect_apply_type(url)     # Easy Apply vs External vs None
  ├── apply_easy_apply(url)      # Drive Easy Apply modal
  ├── apply_external(url)        # Drive external form
  ├── fill_form_fields(page)     # Fill detected fields from profile
  └── handle_captcha()           # Notify user if CAPTCHA detected
```

### Form-fill strategy

Two strategies, selected based on page structure:

**Strategy A: `browser eval` bulk fill (primary)**
- For Greenhouse, Lever, and standard forms
- Single JS evaluation fills all fields and triggers React events
- Demonstrated working on PhonePe/Greenhouse in 2 eval calls

**Strategy B: Step-by-step `browser` commands (fallback)**
- For custom/complex SPAs
- Use `state` → `click`/`type`/`select` per field
- Slower but handles any page structure

### Profile data mapping

Profile data is used to auto-fill common form fields:

| Form Field | Source |
|---|---|
| First/Last Name | `profile.name` (split on first space) |
| Email | `profile.email` |
| Phone | `profile.phone` |
| LinkedIn URL | `profile.linkedin_url` |
| GitHub URL | `profile.github_url` |
| Current Company | From work experience |
| Title | `profile.title` |
| Skills | `profile.skills` (comma-joined) |
| Years of Experience | `profile.experience` |
| Education | From profile (if available) |
| Location | `profile.location` |
| Salary Expectation | `profile.min_salary` / `profile.max_salary` |
| Notice Period | `profile.notice_period` |

### Custom questions (LLM integration)

When a question doesn't match a known field:

1. Read the question label from the DOM
2. Send to AI: `"Given this profile: {profile_json}, answer: '{question_text}'"`
3. Post AI response as the field value
4. User can override before submission

### TUI additions

```python
@kb.add("a")
@kb.add("A")
def _apply(event):
    """Apply to selected job."""
    idx = st.page * page_size + st.selected
    if 0 <= idx < len(ranked):
        job = ranked[idx][1]
        # Check if apply_url exists; enrich if not
        if not job.get("apply_url"):
            job = enrich_job(job)
        if job.get("apply_url"):
            st.mode = "applying"
            # Start application in background
            # Show progress panel
```

New keyboard shortcuts:
- `a` — Apply to selected/highlighted job
- `A` — Apply to all saved jobs (batch mode)

### Application status reporting

```
┌──────────────────────────────────────┐
│ Applying to: Senior DevOps @ Cisco   │
│                                      │
│  ✓ Opened job page                   │
│  ✓ Clicked "Easy Apply"              │
│  ⏳ Filling form page 1/3            │
│     ████████░░░░░░░░░ 45%            │
│                                      │
│  Press 'q' to cancel                 │
└──────────────────────────────────────┘
```

### User interaction points

| Scenario | Action |
|---|---|
| Custom question ("Why this role?") | Ask user via prompt, or use AI |
| File upload (cover letter) | Ask user for file path |
| Salary expectation field | Use profile range, ask if ambiguous |
| CAPTCHA detected | Notify user to solve manually |
| Multi-page form | Auto-detect "Next" button, proceed |
| External redirect to unknown site | Print URL; open in browser for user |

---

## 7. Orchestration & UX

### Full workflow

```
1. python3 main.py
2. Profile loaded (or enter new)
3. Search query + location + days
4. AI query expansion → 3-5 queries
5. Parallel OpenCLI scrapers → 2-5× more results
6. Deduplicate
7. Heuristic rank all
8. AI rank top 30
9. Enrich top 30 with full details + apply URLs
10. Interactive TUI
    ├── ↑↓ navigate
    ├── Enter view detail (with apply URL + description)
    ├── s save job
    ├── o open in browser
    ├── a apply to this job
    ├── A batch apply to saved jobs
    └── q quit
```

### New CLI flags

```python
parser.add_argument("--apply", action="store_true",
    help="Enable application automation (requires OpenCLI)")
parser.add_argument("--apply-limit", type=int, default=5,
    help="Max number of jobs to auto-apply to in batch mode")
parser.add_argument("--dry-run", action="store_true",
    help="Verify form fields without submitting")
```

### Config additions (settings.yaml)

```yaml
search:
  query: "DevOps Engineer"
  location: "Pune"
  days: 7
  max_pages: 2

ai:
  enabled: true
  top_n: 30
  timeout: 60

scrapers:
  opencli: true          # NEW: use OpenCLI-backed scrapers
  indeed_domain: "in.indeed.com"

# NEW section
apply:
  enabled: false
  max_per_run: 5
  dry_run: false
  auto_submit: false     # If false, stop at review step
  fill_strategy: "eval"  # "eval" or "stepwise"

profile_extras:           # NEW: extended profile for applications
  phone: ""
  email: ""
  notice_period: "Immediately Available"
```

---

## 8. Dependencies & Installation

### Runtime dependency

OpenCLI must be installed separately:

```bash
npm install -g @jackwener/opencli
opencli doctor    # Verify browser bridge
```

Matcha should check for OpenCLI at startup and degrade gracefully:

```python
OPENCLI_AVAILABLE: bool = False

def _probe_opencli() -> bool:
    try:
        r = subprocess.run(["opencli", "--version"], capture_output=True, timeout=5)
        return r.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
```

### Installation modes

| Mode | OpenCLI required? | Chrome required? | Features available |
|---|---|---|---|
| Basic | No | No | Existing scrapers, AI scoring, TUI |
| Scraper | Yes | Yes (LinkedIn login) | OpenCLI scrapers (25–100 LinkedIn results, reliable Indeed) |
| Enriched | Yes | Yes (LinkedIn login) | + job detail enrichment (descriptions, apply URLs, salary) |
| Full | Yes | Yes (browser bridge) | + application automation (Easy Apply, external apply) |

### Error handling

| Failure | Behavior |
|---|---|
| OpenCLI not installed | One-time startup warning suggesting `npm install -g @jackwener/opencli`, then use existing scrapers silently |
| LinkedIn consent declined | Use existing guest-API LinkedIn scraper (no further prompts) |
| OpenCLI timeout during scrape | Log error, skip that source, continue with remaining scrapers |
| OpenCLI returns non-zero exit | Log stderr, skip that source, continue |
| Browser not connected | Skip application, notify user |
| CAPTCHA during apply | Pause, prompt user to solve |
| Apply fails midway | Mark as `apply_failed`, save partial state for retry |

---

## 9. File Changes Summary

| File | Change |
|---|---|
| `models.py` | Extend `Job` model with `apply_url`, `workplace_type`, etc. Extend `Profile` with phone, email, etc. |
| `actions.py` | Add apply_url/salary columns to SQLite. Add `set_job_apply_status()` |
| `main.py` | Add `--apply`, `--apply-limit`, `--dry-run` flags. Update `SCRAPER_DEFS`. Add `a`/`A` key bindings. Add enrichment step. |
| `scrapers/opencli_linkedin.py` | **NEW** — OpenCLI wrapper for linkedin search |
| `scrapers/opencli_indeed.py` | **NEW** — OpenCLI wrapper for indeed search |
| `scrapers/__init__.py` | No changes needed |
| `enricher.py` | **NEW** — Job detail enrichment module |
| `applicator.py` | **NEW** — Application automation module |
| `profile.py` | Add phone/email/notice_period fields to manual entry prompts |
| `settings.py` | Add `scrapers.opencli` and `apply` sections to YAML config |
| `config.py` | Store additional profile fields |
| `matcher.py` | Optionally use apply_url presence as scoring signal |
| `revamp/opencli-integration-plan.md` | This document |

---

## 10. Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| OpenCLI breaks with Node version change | Low | High | Pin opencli version in docs; use subprocess with version check |
| LinkedIn changes DOM/API | Medium | High | OpenCLI's `match_level` system detects drift; run `--trace retain-on-failure` |
| Greenhouse/Lever change form structure | Medium | Medium | `browser find --css` with multiple fallback selectors; eval-based fill still works |
| Browser session timeout during long apply flow | Low | Medium | Implement retry with session resume |
| CAPTCHA blocks automated apply | High | Medium | Detect CAPTCHA, notify user, fall back to opening URL manually |
| User has no Chrome/browser installed | Low | High | Check `opencli doctor`; warn early |
| Easy Apply multi-page form varies per job | High | Medium | Use AI to determine next action; ask user on ambiguity |
| Subprocess startup latency (Node.js) per call | Medium | Low | Reuse session; batch enrichments in thread pool |

---

## 11. Recommendations

### Build order

1. **Phase 1 (Priority: High)**
   - Create `scrapers/opencli_linkedin.py`
   - Create `scrapers/opencli_indeed.py`
   - Add `check_opencli_available()` to main.py
   - Conditionally register OpenCLI scrapers
   - This immediately improves job discovery

2. **Phase 2 (Priority: High)**
   - Create `enricher.py`
   - Extend `Job` model with new fields
   - Enrich top 30 jobs after ranking
   - Display apply_url in TUI detail panel
   - Save enriched fields to SQLite

3. **Phase 3 (Priority: Medium)**
   - Extend `Profile` model with phone, email, notice_period, etc.
   - Extend manual profile entry to collect new fields in `profile.py`
   - Create `applicator.py` with eval-based bulk fill
   - Support Easy Apply workflow (LinkedIn modal)
   - Support external site application (Greenhouse, Lever, Workday)
   - Add `a` key binding to TUI for single-job apply
   - Add `A` key binding for batch apply to saved jobs
   - Add `--dry-run` mode to verify form fields without submitting
   - AI-powered custom question answering for unknown form fields
   - Application progress panel in TUI
   - Resume upload to Easy Apply
   - Track application state in SQLite (`applying`, `applied`, `apply_failed` statuses)

### Testing strategy

| Component | Test approach |
|---|---|
| OpenCLI wrappers | Unit tests with mocked subprocess |
| Enricher | Unit tests + integration test with 1 real job |
| Applicator | Integration test with dry-run mode on sample job |
| Full workflow | E2E: search → enrich → apply with `--dry-run` |
| Graceful degradation | Test without OpenCLI installed |

### Key design principles

1. **Graceful degradation** — Every OpenCLI feature should have a non-OpenCLI fallback
2. **User in control** — Never auto-submit without user confirmation (initially)
3. **Transparency** — Show the user what fields will be filled before submitting
4. **Resumability** — Save application state so partial fills can be retried
5. **Privacy** — Profile data stays local; browser automation uses the user's own Chrome session

---

## Appendix: OpenCLI Command Reference for Integration

### Job Search
```bash
opencli linkedin search "<query>" --location "Pune" --date-posted week \
  --experience-level mid-senior --job-type full-time --limit 25 -f json
```

### Job Detail
```bash
opencli linkedin job-detail "https://www.linkedin.com/jobs/view/..." -f json
```

### Indeed Search
```bash
opencli indeed search "<query>" --location "Pune" --limit 25 -f json
```

### Indeed Job Detail
```bash
opencli indeed job "<job-key>" -f json
```

### Browser Driving
```bash
opencli browser <session> open <url>                          # Navigate
opencli browser <session> state                                # Inspect page
opencli browser <session> click <ref>                          # Click element
opencli browser <session> fill <ref> "<value>"                 # Fill input
opencli browser <session> type <ref> "<value>"                # Type into input
opencli browser <session> select <ref> "<option>"             # Select dropdown
opencli browser <session> find --css "<selector>"             # Find elements
opencli browser <session> eval "<js code>"                    # Run JavaScript
opencli browser <session> upload <ref> <filepath>             # Upload file
opencli browser <session> wait selector "<css>" --timeout 5000 # Wait
opencli browser <session> close                               # Cleanup
```
