# free-job-agent — France / Paris Data & AI Edition

A completely **free, local-first** job-search and application assistant focused on **Paris, France, and Europe** for **data science, machine learning, AI, data analyst, data engineer, stage, alternance, and junior data roles**.

It runs on your machine, uses SQLite, and never requires paid LLM APIs, paid browser agents, paid scraping platforms, or cloud services.

## What it does

- **France-first job intake:** paste text, import local files, fetch public URLs, parse RSS/Atom feeds, discover likely career links, search free/read-only APIs, and generate French job-board search URLs.
- **France Travail API support:** source `francetravail` uses the official France Travail Offres d’emploi API when you configure free credentials.
- **Internship tracking workbook:** exports submitted internship applications into `profiles/Internship Search Tracking File A24.xlsx` with the columns you requested.
- **French board shortcuts:** generates manual search URLs for France Travail, Welcome to the Jungle, HelloWork, Apec, Indeed France, LinkedIn France, Glassdoor France, Stage.fr, JobTeaser, and La bonne alternance.
- **CAC 40 targeting:** lists career pages for large French companies including BNP Paribas, AXA, Orange, Schneider Electric, Capgemini, L’Oréal, LVMH, Sanofi, TotalEnergies, Thales, Safran, Airbus, and more.
- **Normalization:** extracts tech stack, salary, remote/hybrid/onsite signals, seniority, French/English language signals, requirements, responsibilities, and benefits.
- **Fit scoring:** deterministic 0-100 score with notes, confidence, decision, missing requirements, and risk flags.
- **CV tailoring:** reorders and selects facts from your master CV; it never invents facts.
- **Cover letter:** concise, role-specific, grounded only in your profile/CV/job posting.
- **Locked screening answers:** uses `master_qa_profile.json`; unknown factual answers require manual review.
- **Artifacts:** writes `cv.md`, `cv.tex`, `cv.html`, `cv.pdf`, `cover_letter.md`, `cover_letter.html`, `cover_letter.pdf`, and `assistant.html`.
- **Tracking:** jobs, packets, and events are saved in local SQLite.
- **Manual final submit:** the system opens/creates an assistant page, but it never submits applications automatically.

## Why not full auto-apply?

The goal is to stay free, safe, and reliable. Fully autonomous ATS submission normally requires paid browser-agent infrastructure, paid APIs, proxies, CAPTCHA handling, login automation, or fragile scraping. This system automates the useful free parts: search, import, dedupe, score, tailor documents, prepare locked screening answers, and open a local assistant page. You still review and submit manually.

## Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

If you are working in a constrained environment, the project also includes local fallbacks for the command runner, HTTP fetches, and basic HTML extraction so the core workflow can still run without every optional package being installed.

Windows PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

## Quick start

```bash
job-agent init
job-agent copy-examples
job-agent validate-profile
```

Run the local dashboard:

```powershell
job-agent ui
```

Then open:

```text
http://127.0.0.1:8765
```

The dashboard gives you one-click search controls, language selection, curated
job-board links, France Travail API search when configured, job tracking,
URL/text import, packet generation, profile readiness, and the suggested app
description for France Travail API access.

You can also export submitted internship applications into the Excel tracker
from the CLI or the dashboard.

If this repository contains a `profiles/` folder with the three profile JSON
files, the CLI uses it automatically and stores runtime data in the local
ignored `.job_agent/` folder. Otherwise, edit these files in
`~/.job_agent/profiles/`:

```text
candidate_profile.json
master_cv.json
master_qa_profile.json
```

The example profile is now a France/Paris data-AI template. Replace all `EDIT THIS` content with your real information.

You can override locations explicitly with `JOB_AGENT_DATA_DIR` and
`JOB_AGENT_PROFILES_DIR`.

## LaTeX CV output

Every generated application packet includes an editable `cv.tex` next to
`cv.md`, `cv.html`, and `cv.pdf`. When `profiles/main.tex` exists, the app
preserves that `moderncv` template, keeps the same layout/photo/style, and
replaces only the CV content macros with job-tailored text from your profile
data. Local LaTeX assets such as `me.jpg` and `.sty` files are copied beside
the generated `cv.tex`.

If a LaTeX compiler is installed on `PATH`, `cv.pdf` is built from `cv.tex`.
Supported compilers are `latexmk`, `pdflatex`, `xelatex`, or `lualatex`.

The app now also checks the common MiKTeX install locations on Windows, so if
`pdflatex --version` works in PowerShell, the dashboard should normally report
LaTeX as ready after a refresh.

On Windows, install one of:

```text
MiKTeX: https://miktex.org/download
TeX Live: https://tug.org/texlive/windows.html
```

After installing, restart PowerShell and verify:

```powershell
pdflatex --version
```

Then rerun packet generation:

```powershell
job-agent apply <job-id> --force
```

If no compiler is installed, the app still writes `cv.tex`, creates a fallback
PDF, and writes `latex_warning.txt` in the packet folder.

## France / Paris workflow

### 1. See setup instructions

```bash
job-agent france-setup
```

### 2. Generate manual search URLs for French job boards

```bash
job-agent france-search-urls --query "data science stage" --location Paris
job-agent france-search-urls --query "machine learning alternance" --location "Île-de-France"
```

The default output is a plain list with full, copyable URLs. It uses recommended
boards by default and expands queries in English first, then French. You can
control both:

```powershell
job-agent france-search-urls --query "data scientist" --location Paris --language english --limit 8
job-agent france-search-urls --query "data scientist" --location Paris --language french --limit 8
job-agent france-search-urls --query "data scientist" --location Paris --boards all --limit 8
job-agent france-search-urls --query "data scientist" --location Paris --limit 8 --output france_urls.txt
job-agent france-search-urls --query "data scientist" --location Paris --format table
job-agent france-search-urls --query "data scientist" --location Paris --format json --output france_urls.json
```

Open the best URLs, copy promising job URLs, then import them:

```bash
job-agent add url "https://company-or-job-board/job-url"
job-agent apply <job-id>
job-agent apply-assist <packet-id>
```

### 3. Use France Travail API when configured

France Travail requires free developer credentials/habilitation for the API.
Your normal candidate login is separate and is not used by this CLI. After
approval, set:

```bash
export FRANCE_TRAVAIL_CLIENT_ID="your-client-id"
export FRANCE_TRAVAIL_CLIENT_SECRET="your-client-secret"
export FRANCE_TRAVAIL_SCOPE="api_offresdemploiv2 o2dsoffre"
```

Windows PowerShell:

```powershell
[Environment]::SetEnvironmentVariable("FRANCE_TRAVAIL_CLIENT_ID", "your-client-id", "User")
[Environment]::SetEnvironmentVariable("FRANCE_TRAVAIL_CLIENT_SECRET", "your-client-secret", "User")
[Environment]::SetEnvironmentVariable("FRANCE_TRAVAIL_SCOPE", "api_offresdemploiv2 o2dsoffre", "User")
```

Restart PowerShell after saving user environment variables.

Suggested France Travail API application details:

```text
App name: Paris Data Career Copilot
URL: https://github.com/m-ihab/free-job-agent
Description: A local-first career copilot for data science, AI, and analytics roles in France. It searches public job data, tracks opportunities, scores fit against my profile, and prepares tailored CV and cover-letter packets for manual review and submission.
```

For portfolio value, keep private application data local and use the GitHub
repository or a later GitHub Pages demo page as the public project URL.

Then search and save:

```bash
job-agent search-api francetravail --query "data scientist stage" --location Paris --limit 20 --save
```

Run the built-in Paris data/AI query pack:

```bash
job-agent france-hunt --location Paris --limit 10
```

This tries queries like `data scientist stage`, `machine learning internship`, `alternance data science`, `junior data scientist`, etc.

To keep France Travail search results internship-only, add `--internships-only`:

```powershell
job-agent search-api francetravail --query "data scientist stage" --location Paris --save --internships-only
job-agent france-hunt --location Paris --limit 10 --internships-only
```

To fill the Excel tracker with the internships you already marked as applied:

```powershell
job-agent export internships
```

### 4. Target CAC 40 / large French companies

```bash
job-agent france-targets
```

Open company career pages, search for `data`, `machine learning`, `AI`, `stage`, `alternance`, then import promising URLs with `job-agent add url`.

## Generic API search

List supported API-style sources:

```bash
job-agent api-sources
```

Supported sources include:

```text
francetravail, arbeitnow, remotive, remoteok, himalayas, greenhouse, lever, ashby
```

For company ATS boards:

```bash
job-agent search-api greenhouse --board example-company --query "data" --save
job-agent search-api lever --board example-company --query "machine learning" --save
job-agent search-api ashby --board ExampleCompany --query "data" --save
```

## One-command processing

```bash
job-agent process file path/to/job.txt --title "Data Scientist Intern" --company "Company" --url "https://company.com/apply"
```

This does:

```text
ingest -> normalize -> dedupe -> filter -> score -> generate packet
```

## CLI reference

```text
job-agent init
job-agent copy-examples
job-agent validate-profile
job-agent ui [--host 127.0.0.1] [--port 8765] [--no-open]
job-agent france-setup
job-agent france-search-urls [--query ...] [--location ...] [--language english|french|both] [--boards recommended|all] [--format list|table|json] [--output PATH]
job-agent france-targets [--limit N]
job-agent france-hunt [--query ...] [--location Paris] [--limit N] [--packets/--no-packets]
job-agent export internships [--workbook PATH] [--sheet NAME]
job-agent add paste [--title ...] [--company ...] [--url ...]
job-agent add file PATH [--title ...] [--company ...] [--url ...]
job-agent add url URL
job-agent add rss FEED_URL [--limit N]
job-agent discover-links URL [--limit N]
job-agent api-sources
job-agent search-api SOURCE [--query ...] [--location ...] [--country ...] [--board ...] [--limit N] [--remote-only] [--cache/--no-cache] [--save]
job-agent hunt SOURCE [--query ...] [--location ...] [--country ...] [--board ...] [--limit N] [--remote-only] [--cache/--no-cache] [--force]
job-agent list [--status STATUS]
job-agent show JOB_ID
job-agent score JOB_ID
job-agent apply JOB_ID [--force]
job-agent process file PATH [--title ...] [--company ...] [--url ...] [--force]
job-agent apply-assist PACKET_ID [--no-open-browser]
job-agent mark-submitted PACKET_ID [--note ...]
job-agent status JOB_ID STATUS [--note ...]
job-agent history JOB_ID
job-agent packet show JOB_OR_PACKET_ID
```

## Safety rules

- Never invent experience, education, metrics, certifications, dates, legal facts, visa facts, work authorization, or salary expectations.
- Never infer sponsorship claims in the cover letter.
- Never answer unknown screening questions automatically.
- Never bypass CAPTCHAs, login restrictions, paywalls, platform rate limits, or access controls.
- Never scrape logged-in LinkedIn/Indeed/Glassdoor/Welcome to the Jungle pages or automate account actions.
- Never auto-submit applications.
- Keep every generated artifact traceable with hashes.

## Development

```bash
pip install -e ".[dev]"
pytest -q
python -m compileall src
PYTHONPATH=src python scripts/smoke_test.py
```

## Project structure

```text
src/job_agent/
  cli/main.py             # Standard-library CLI with test shim compatibility
  db/database.py          # SQLite layer
  generator/              # CV, cover letter, QA
  intake/                 # paste, file, URL, RSS, link discovery, APIs, France market helpers
  renderer/               # markdown, HTML, PDF, assistant page
  schemas/                # Pydantic-compatible models
  config.py
  filters.py
  fingerprint.py
  hashutil.py
  normalizer.py
  pipeline.py
  scorer.py
  tracker.py
  validators.py
scripts/
  smoke_test.py           # end-to-end local sanity check
examples/
  candidate_profile.json
  master_cv.json
  master_qa_profile.json
tests/
```
