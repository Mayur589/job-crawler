# Keyword-Based Job Crawler & Career Pipeline

A high-performance, modular job search and crawler engine built in Python (`httpx`, `pydantic`, `sqlite3`, `rich`, `pytest`). It pulls directly from public ATS endpoints (**Greenhouse**, **Lever**) and developer job feeds (**RemoteOK**)—avoiding brittle HTML scraping and bot-detection issues.

---

## Architecture

```
[Scheduler / CLI]
       │
       ▼
 [Job Sources] ──► Greenhouse ATS (boards-api.greenhouse.io)
               ──► Lever ATS (api.lever.co)
               ──► RemoteOK Feed (remoteok.com/api)
       │
       ▼
 [Normalizer]   ── Strip tracking query params (utm_*, gh_src, ref), unescape HTML, deterministic hash ID
       │
       ▼
  [Matcher]     ── Regex with word boundaries (\bGo\b vs Google), title/tech weighting, hard exclusions
       │
       ▼
[Deduplication] ── Exact ID check + Fuzzy cross-source deduplication (company | title | location)
       │
       ▼
 [SQLite Store] ── State tracking (new, seen, applied, saved, ignored, closed)
       │
       ▼
 [Rich CLI / UI]── Interactive terminal dashboard, filters, inspect view, CSV/JSON export
```

---

## Quickstart

This project uses [`uv`](https://github.com/astral-sh/uv) for fast, reproducible dependency management.

### 1. Run a Crawl Session
Fetch jobs across all configured Greenhouse companies, Lever boards, and RemoteOK feeds:
```bash
uv run job-crawler crawl
```
*(Use `--no-close` if you do not want unseen jobs marked as closed).*

### 2. View Matched Jobs
List jobs ranked by match score with color badges:
```bash
# List all matches
uv run job-crawler list

# Filter remote-only roles with score >= 10
uv run job-crawler list --remote --min-score 10.0

# Search by title, company, or keyword
uv run job-crawler list --search "Backend"
uv run job-crawler list --search "Golang"
uv run job-crawler list --search "Python"

# Filter by application status
uv run job-crawler list --status new
uv run job-crawler list --status applied
```

### 3. Inspect a Job & View Details
View formatted job information, matched keywords with contextual snippets, and description:
```bash
uv run job-crawler show <JOB_ID>
# Example:
uv run job-crawler show 0c7ba998
```
*(Inspecting a job automatically marks it from `NEW` to `SEEN`).*

### 4. Track Application Status
Mark jobs as applied, saved, or ignored:
```bash
uv run job-crawler set-status <JOB_ID> applied
uv run job-crawler set-status <JOB_ID> saved
uv run job-crawler set-status <JOB_ID> ignored
```

### 5. View Crawler Stats
Inspect total jobs, breakdown by source, status breakdown, and top tech keywords:
```bash
uv run job-crawler stats
```

### 6. Export to CSV or JSON
Export all matches for tracking in spreadsheets or custom dashboards:
```bash
uv run job-crawler export --format csv -o data/jobs_export.csv
uv run job-crawler export --format json -o data/jobs_export.json
```

### 7. Test Keyword Matching on the Fly
Test your keyword rules against any role title or description before saving to config:
```bash
uv run job-crawler test-match "Backend Engineer" -d "Building high-scale services in Go and PostgreSQL"
```

---

## Configuration

### Keywords & Scoring (`config/keywords.yaml`)

- **`roles.title_keywords`**: High-weight patterns matched against job titles (e.g. `Backend Engineer`, `Go Engineer`, `Full Stack Engineer`).
- **`roles.tech_keywords`**: Tech stack tokens (e.g. `Go`, `Golang`, `Python`, `FastAPI`, `Docker`, `PostgreSQL`).
  - Strict regex word boundaries (e.g. `\bGo\b`) prevent false positives from tokens like `Google`.
  - Tech appearing in the title receives a 1.3x boost.
- **`exclusions.title_hard_rejects`**: Hard exclusion regexes (e.g. `Director`, `VP`, `Recruiter`, `Sales`, `HR`) that reject roles immediately.
- **`exclusions.negative_keywords`**: Penalty keywords (e.g. `10+ years`, `Security Clearance`) that subtract points.
- **`thresholds.min_score`**: Minimum score threshold (default: `3.0`).
- **`thresholds.require_role_title`**: Ensures non-engineering positions never match.

### Sources (`config/sources.yaml`)

Add any company using Greenhouse or Lever simply by appending their slug:
```yaml
sources:
  greenhouse:
    enabled: true
    companies:
      - slug: gitlab
        name: "GitLab"
      - slug: stripe
        name: "Stripe"
      - slug: cloudflare
        name: "Cloudflare"
      - slug: reddit
        name: "Reddit"
      - slug: coinbase
        name: "Coinbase"

  lever:
    enabled: true
    companies:
      - slug: spotify
        name: "Spotify"
      - slug: palantir
        name: "Palantir"

  remoteok:
    enabled: true
    tags:
      - "backend"
      - "golang"
      - "python"
      - "full-stack"
```

---

## Running Automated Tests

Run the complete test suite with offline JSON fixtures:
```bash
uv run pytest -v
```
All tests run offline in under 0.2 seconds and validate URL canonicalization, HTML stripping, word boundaries, weighted scoring, exact & fuzzy deduplication, and source parsers.

---

## Future Extensions: Resume Extraction

The modular design makes adding resume-based ranking straightforward:
1. Extract candidate skills and project keywords from PDF/DOCX resumes (e.g. using `pypdf` or `pdfplumber`).
2. Feed extracted skill sets directly into `matcher.py` as personalized dynamic weights.
3. Compute cosine similarity or semantic embeddings between the resume summary and the normalized job descriptions.
