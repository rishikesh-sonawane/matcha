# Job Finder

CLI tool that finds the most relevant jobs from across the web based on your professional profile.

## Quick Start

```bash
# Install dependencies
pip3 install -r requirements.txt

# Run
python3 main.py
```

## How to Provide Your Profile

You have three options when you start the app:

### 1. Upload a Resume PDF

Select option `2` and provide the path to your PDF resume.

```
How would you like to enter your profile?
  1. Enter details manually
  2. Upload a resume PDF          <-- choose this
  3. Provide a LinkedIn profile URL
Choose (1): 2
Path to resume PDF: /Users/you/Documents/Resume.pdf
```

The tool extracts your name, job title, skills, and experience using `pdfplumber`.

**Supported**: Text-based PDFs (not scanned images).

### 2. LinkedIn Profile URL

Select option `3` and paste your full LinkedIn profile URL.

```
Choose (3): 3
LinkedIn profile URL: https://www.linkedin.com/in/your-profile-name/
```

The tool fetches your public profile to extract name, headline, and skills.

**Note**: LinkedIn requires authentication for detailed data. The scraper gets what's publicly visible — you can supplement with manual entry afterwards.

### 3. Manual Entry

Select option `1` and type in your details — name, title, skills, experience, and summary. This always works regardless of LinkedIn/PDF limitations.

### Saving & Reusing

Your profile is saved to `~/.job-finder/profile.json`. On subsequent runs, you'll be asked whether to reuse it.

## Searching for Jobs

After profile setup, enter:

- **Job search query** — defaults to your job title (e.g., "Software Engineer")
- **Location** — city name or leave blank for remote/anywhere

The tool searches 4-5 sources concurrently:

| Source | Results | Requires |
|--------|---------|----------|
| LinkedIn | ~10 individual job listings | Nothing |
| Naukri | Search page links for India jobs | Nothing |
| RemoteOK | Remote job listings filtered by query | Nothing |
| Web Search | Job board links from web search | Nothing |
| Google Jobs (optional) | Rich job listings via SerpAPI | SerpAPI key |

## Relevance Scoring

Each job gets a 0–100% match score based on:

- **Title match** (20%) — does the job title match yours?
- **Skills match** (35%) — what fraction of your skills appear in the listing?
- **Keyword match** (15%) — do profile keywords appear in the description?
- **Seniority alignment** (10%) — is the seniority level appropriate for your experience?
- **Location match** (8%) — is the job in your preferred location?

## Viewing Job Details

After the results table, answer `y` when asked about details, then enter a job number to see:

- Full title, company, location
- Application URL
- Match score and why it matched
- Job description (when available)

## Optional: Google Jobs via SerpAPI

For richer Google Jobs results, get a free API key from https://serpapi.com (100 searches/month free).

When you run the app, it will ask if you want to configure a key. Say `y` and paste your key. Or manually add it to `~/.job-finder/config.json`:

```json
{
  "serpapi_key": "your_api_key_here"
}
```

When configured, "Google Jobs" appears as an additional source with full job descriptions and direct apply links.

## How It Works

```
                         ┌──────────────┐
                         │  Your Profile │
                         │  (PDF/URL/manual) │
                         └──────┬───────┘
                                │
                    ┌───────────┴───────────┐
                    │   Relevance Matcher   │
                    │   (title, skills,     │
                    │    keywords, seniority,│
                    │    location)          │
                    └───────────┬───────────┘
                                │
         ┌──────────────────────┼──────────────────────┐
         ▼                      ▼                      ▼
   ┌──────────┐          ┌──────────┐          ┌──────────┐
   │ LinkedIn  │          │ Naukri   │          │ RemoteOK │
   │ (API)    │          │ (Search) │          │ (API)     │
   └──────────┘          └──────────┘          └──────────┘
         ▼                      ▼                      ▼
   ┌───────────────────────────────────────────────────────┐
   │              Ranked Results Table                     │
   │  # │ Title       │ Company │ Location │ Source │ Match │
   └───────────────────────────────────────────────────────┘
```

## Files

| File | Purpose |
|------|---------|
| `main.py` | CLI entry point |
| `profile.py` | Profile management (PDF, LinkedIn, manual) |
| `matcher.py` | Relevance scoring engine |
| `config.py` | Config profile storage |
| `scrapers/linkedin.py` | LinkedIn Jobs via guest API |
| `scrapers/naukri.py` | Naukri listings via web search |
| `scrapers/remoteok.py` | RemoteOK via public API |
| `scrapers/web_search.py` | DuckDuckGo web search fallback |
| `scrapers/serpapi_jobs.py` | Google Jobs via SerpAPI (optional) |
