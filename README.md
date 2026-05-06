# free-job-agent

A completely **free, local-first** job-search and application assistant. No paid APIs, no paid browser services, no cloud costs — runs entirely on your machine.

## Features

- **Job intake**: paste text, import local files, fetch public URLs, parse RSS/Atom feeds
- **Normalization**: extracts tech stack, salary, remote status, requirements, responsibilities from raw text
- **Deduplication**: SHA-256 fingerprints prevent duplicate jobs in the database
- **Hard filters**: block companies/keywords, enforce remote-only, salary minimums, location
- **Fit scoring**: RapidFuzz-based skill matching, title matching, and location scoring
- **CV tailoring**: selects and orders your most relevant experience from a master CV — never invents facts
- **Cover letter**: 3-paragraph letter grounded only in your actual profile
- **QA answers**: matches screening questions to your locked answer bank
- **Artifact generation**: Markdown, HTML, and PDF output (ReportLab, no cloud)
- **Application tracker**: all jobs, packets, and events in SQLite
- **Typer CLI + Rich UI**: clean terminal interface
- **Safety**: never auto-submits applications — final submit is always manual

## Quick Start

### 1. Install

```bash
pip install -e ".[dev]"
```

### 2. Initialize

```bash
job-agent init
```

This creates `~/.job_agent/` with subdirectories for profiles and outputs.

### 3. Set up your profiles

Copy the example files to your profiles directory and customize:

```bash
cp examples/candidate_profile.json ~/.job_agent/profiles/
cp examples/master_cv.json ~/.job_agent/profiles/
cp examples/master_qa_profile.json ~/.job_agent/profiles/
```

Edit each file to reflect your actual background.

### 4. Add a job

**Paste mode** (interactive):
```bash
job-agent add paste
```

**From file**:
```bash
job-agent add file path/to/job.txt
```

**From public URL**:
```bash
job-agent add url https://company.com/jobs/engineer
```

**From RSS feed**:
```bash
job-agent add rss https://jobs.example.com/feed.xml --limit 10
```

### 5. Score and apply

```bash
job-agent list
job-agent score <job-id>
job-agent apply <job-id>
```

The `apply` command generates a full application packet at `~/.job_agent/outputs/<job-id>/`:
- `cv.pdf` + `cv.html` — tailored CV
- `cover_letter.pdf` + `cover_letter.html` — tailored cover letter
- `assistant.html` — local application assistant page with all docs, apply URL, and QA answers

Review everything, then submit manually.

### 6. Track your applications

```bash
job-agent status <job-id> applied
job-agent history <job-id>
```

## Profile Files

| File | Purpose |
|------|---------|
| `candidate_profile.json` | Your contact info, skills, target roles, salary expectations, work authorization |
| `master_cv.json` | Your full CV: experience, education, projects, certifications |
| `master_qa_profile.json` | Locked answers to common screening questions |

See `examples/` for annotated templates.

## CLI Reference

```
job-agent init                     Initialize data directory
job-agent add paste                Add job from stdin
job-agent add file PATH            Add job from text file
job-agent add url URL              Add job from public URL
job-agent add rss URL [--limit N]  Add jobs from RSS feed
job-agent list [--status STATUS]   List all tracked jobs
job-agent show JOB_ID              Show job details
job-agent score JOB_ID             Score job against your profile
job-agent apply JOB_ID             Generate full application packet
job-agent status JOB_ID STATUS     Update job status
job-agent history JOB_ID           Show event history
job-agent packet show JOB_ID       Show latest packet for a job
```

## Safety Rules

- **Never invents facts** — CV and cover letter use only content from your master CV and profile
- **Never answers unknown screening questions** — only matched locked QA entries are used
- **Never auto-submits** — all application submission is manual
- **Never bypasses CAPTCHAs** or login walls
- **No paid services** — all processing is local

## Project Structure

```
src/job_agent/
├── cli/          — Typer + Rich CLI
├── db/           — SQLite database layer
├── generator/    — CV, cover letter, QA generators
├── intake/       — paste, file, URL, RSS ingestion
├── renderer/     — Markdown, HTML, PDF output
├── schemas/      — Pydantic v2 data models
├── config.py     — Configuration management
├── filters.py    — Hard job filters
├── fingerprint.py — SHA-256 deduplication
├── normalizer.py  — Raw text → structured job
├── scorer.py      — Fit scoring
└── tracker.py     — Application tracking
examples/         — Template profile files
tests/            — pytest test suite (98 tests)
```

## Development

```bash
pip install -e ".[dev]"
pytest tests/ -v
```

## Optional: Ollama (local LLM)

For enhanced normalization and generation, install [Ollama](https://ollama.ai) and enable it in `~/.job_agent/config.json`:

```json
{
  "ollama_enabled": true,
  "ollama_model": "mistral"
}
```

The system runs fully deterministically without Ollama — it's purely optional.
