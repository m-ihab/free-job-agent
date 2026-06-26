# free-job-agent — Paris Data Career Copilot

A completely **free, local-first** job-search and application copilot focused
on **Paris, France, and Europe** for **data science, machine learning, AI,
data analyst, data engineer, stage, alternance, and junior data roles**.

Runs on your machine, uses SQLite, never requires paid LLM APIs, paid browser
agents, paid scraping platforms, or cloud services. Your candidate data and
application history stay local.

## TL;DR

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
job-agent init
job-agent copy-examples
job-agent setup-wizard          # optional: fill stage/alternance fields
job-agent enrich-github         # pull skills/projects from your GitHub
job-agent validate-profile
.\launch.ps1                    # opens http://127.0.0.1:8765
```

The dashboard gives you 1-click hunt, multi-source search across free public
APIs, tracked-jobs board, insights & funnel, CSV export, GitHub/LinkedIn
profile enrichment, AI fit analysis (with Ollama), an autonomous job-hunting
loop, one-click Ollama startup, and one-click packet generation that fills your `profiles/main.tex`
with role-tailored text while preserving your photo, design, and skills
narrative.

## France Travail credentials — what you actually need

You only need **two environment variables** for the core search:

```text
FRANCE_TRAVAIL_CLIENT_ID
FRANCE_TRAVAIL_CLIENT_SECRET
```

The "endpoints map" file (``.france_travail.endpoints.local.json``) is
**optional** — it only unlocks the enrichment endpoints (ROME 4.0 skills,
Anotea employer reviews, Open Training, Labour Market). The dashboard now
shows this clearly: with just the ID/secret you're fully set for job search,
scoring, and packet generation.

For apprenticeship/alternance opportunities from La bonne alternance, add this
local-only variable to `.env.local`:

```text
APPRENTISSAGE_API_TOKEN=your-token
```

That token is used with `Authorization: Bearer ...` against
`api.apprentissage.beta.gouv.fr`. `.env.local` is gitignored.

## What it does

- **France-first job intake:** paste text, import local files, fetch public
  URLs, parse RSS/Atom feeds, discover likely career links, search free/
  read-only APIs, and generate French job-board search URLs.
- **France Travail API:** when you set free credentials, the dashboard pulls
  data straight from the official Offres d'emploi API.
- **Multi-source search:** one button to query Remotive, Remote OK, Himalayas,
  Arbeitnow, Jobicy, The Muse, and La bonne alternance when its local token is
  configured, deduplicating results.
- **Company ATS feeds:** Greenhouse, Lever, Ashby, Recruitee, SmartRecruiters,
  Workable, Personio — all free and credential-free, just point at the
  company slug.
- **Internship tracking workbook:** exports submitted internship applications
  into `profiles/internship_tracker.xlsx` (or any path you set via
  `JOB_AGENT_INTERNSHIP_WORKBOOK`). The file lives in the gitignored
  `profiles/` directory so it never leaves your machine.
- **French board shortcuts:** generates manual search URLs for France Travail,
  Welcome to the Jungle, HelloWork, Apec, Indeed France, LinkedIn France,
  Glassdoor France, Stage.fr, JobTeaser, and La bonne alternance.
- **CAC 40 targeting:** lists career pages for large French companies
  including BNP Paribas, AXA, Orange, Schneider Electric, Capgemini, L'Oréal,
  LVMH, Sanofi, TotalEnergies, Thales, Safran, Airbus, and more.
- **Normalization & scoring:** extracts tech stack, salary, remote/hybrid,
  seniority, language signals, requirements, responsibilities, and benefits;
  deterministic 0-100 fit score with notes, confidence, decision, missing
  requirements, and risk flags.
- **Tailored LaTeX CV:** uses your `profiles/main.tex`. The template's design,
  layout, photo, language toggle, and curated skills narrative are preserved;
  only role-relevant text (summary closer, experience-bullet ordering, top
  project) is updated per job.
- **CV Studio:** local LaTeX workbench with a larger split preview, isolated
  asset editor, icon-pack switching, project promotion, one-page guard, and ATS
  keyword radar.
- **Portfolio Builder:** generates a local static portfolio site from your CV,
  GitHub/profile projects, photo, skills, and experience. Edit HTML/CSS, switch
  themes/fonts, preview locally, export ZIP, and create a publish checklist.
- **Cover letter:** concise, role-specific, grounded only in your profile,
  CV, and the job posting — never invents sponsorship or visa facts.
- **Locked screening answers:** uses `master_qa_profile.json`; unknown
  factual answers require manual review.
- **Artifacts per job:** `cv.md`, `cv.tex`, `cv.html`, `cv.pdf`,
  `cover_letter.md`, `cover_letter.html`, `cover_letter.pdf`, and
  `assistant.html`.
- **Insights & analytics:** local funnel, weekly throughput, top companies,
  sources, locations, and score distribution.
- **CSV export** of the tracked-jobs table.
- **Optional local LLM polish:** opt-in Ollama support that lightly polishes
  bullets and paragraphs under strict validation (no invented facts, numbers
  preserved verbatim, bounded length). Off by default.
- **Safe auto-apply:** Playwright can open a separate local Job Agent browser
  profile and fill supported application forms. With **Full Auto OFF**, Job Agent
  uses **Fill & Confirm** and waits for you to review and submit. With
  **Full Auto ON**, Job Agent uses **Full Auto** and submits eligible supported
  applications automatically without per-job human interaction.

## Auto-apply safety model

Auto-apply has a simple toggle:

| Full Auto toggle | Mode | What happens |
|------------------|------|--------------|
| **OFF** | **Fill & Confirm** | Job Agent fills supported forms, then waits for you to review and click Submit. |
| **ON** | **Full Auto** | Job Agent fills and submits eligible supported applications without per-job human interaction. |

`Manual Packet` remains available as a packet-only path for generating artifacts without browser submission.

Full Auto is intentionally hands-off after you turn it on for a run. It does not pause for per-job confirmation. If you want to review each application before submission, keep Full Auto OFF and use Fill & Confirm.

Full Auto still fails closed. It will not bypass CAPTCHA, anti-bot checks, login walls, paywalls, rate limits, or access controls. It also will not guess unknown factual screening answers. If any of those appear, Job Agent marks the job `NEEDS_MANUAL`, records the reason, and continues with the next eligible job.

Browser automation uses a dedicated local profile by default:

```text
.job_agent/browser_profiles/auto_apply
```

Sign in once inside that browser and the login stays local for future sessions.

Your normal Chrome profile is not used by default. If you intentionally opt in, close every Chrome window and set:

```text
JOB_AGENT_AUTO_APPLY_USE_REAL_CHROME_PROFILE=1
```

To choose a custom local browser profile folder, set:

```text
JOB_AGENT_AUTO_APPLY_PROFILE_DIR
```

The 10-second cancellation window, when enabled, is a non-blocking safety window. It is not a confirmation requirement and must not turn Full Auto into Fill & Confirm.

Full Auto is separate from Autopilot. Autopilot discovers jobs and prepares packets; the apply-mode toggle controls browser submission.

## Install

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

The core workflow includes local fallbacks for the command runner, HTTP
fetches, and basic HTML extraction so it still runs without every optional
package being installed.

## Quick start

```powershell
job-agent init                  # create local data dirs
job-agent copy-examples         # seed profile files
job-agent setup-wizard          # optional: stage/alternance Q&A
job-agent validate-profile      # check profile files are ready
.\launch.ps1                    # local dashboard on http://127.0.0.1:8765
```

On Windows you can also double-click `launch.bat`. The launcher uses `.venv`,
installs/updates the local package, loads `.env.local`, and opens the
dashboard. Manual launch still works with `job-agent ui`.

The setup wizard updates `master_qa_profile.json` with the stage/alternance
fields most French employers ask for: school/program, availability,
convention de stage, French/English level, visa/work-authorization (sensitive
fields stay locked for manual completion).

If a `profiles/` folder exists next to the repo root, the CLI uses it
automatically and stores runtime data in the local ignored `.job_agent/`
folder. Otherwise edit these files in `~/.job_agent/profiles/`:

```text
candidate_profile.json
master_cv.json
master_qa_profile.json
main.tex                # your LaTeX CV template
me.jpg                  # photo referenced by main.tex
```

Override locations explicitly with `JOB_AGENT_DATA_DIR` and
`JOB_AGENT_PROFILES_DIR`.

## Dashboard

```powershell
.\launch.ps1
```

Tabs:

- **Search:** 1-click hunt (France Travail + curated board links),
  multi-source search across free public APIs, deep API search, and a clean
  link builder.
- **Jobs:** filter, sort, search, remove noisy jobs, batch enrich, batch
  packet generation, CSV export, color-coded score badges, inline detail
  panel, and a CV preview for packet-ready roles.
- **CV Studio:** edit the LaTeX draft, inspect profile assets in a separate
  asset editor, compile a PDF preview, swap contact icon packs, upload/remove
  the photo, add/promote GitHub projects, run the one-page guard, and scan
  ATS keyword coverage.
- **Portfolio:** generate a local static portfolio, preview it, edit the
  HTML/CSS, switch themes and fonts, export ZIP, and create a publish
  checklist.
- **Career Coach:** market-skill analysis from tracked jobs, evidence-aware
  skill gaps, free/audit certification ideas, portfolio project ideas, and a
  dated weekly plan.
- **Insights:** application funnel, 8-week activity bars, top companies/
  sources/locations, score distribution.
- **Add Job:** paste a URL or job description.
- **Profile & API:** profile validation, LaTeX/Ollama readiness, France
  Travail API request text (copy/paste-ready), internship workbook export,
  and local CV template/photo import.

Keyboard shortcuts (press `?` in the dashboard):

```text
?   Show shortcuts help
1-9 Switch tabs
/   Focus job search
g h 1-click hunt
g m Multi-source search
g p Open Portfolio Builder
r   Refresh jobs
Esc Close dialogs
```

### CV Studio guardrails

The Studio has two editors on purpose:

- The large editor is always the LaTeX CV draft that **Compile preview**
  renders.
- The asset editor is only for `profiles/` assets such as `master_cv.json`,
  `candidate_profile.json`, `.sty` files, images, and PDFs.

This prevents JSON/profile assets from being accidentally compiled as LaTeX.
If you add a team project that is not under your own GitHub account, use
**Import a GitHub project -> Add / update a project locally**, then promote it.
The project is saved only in your local `profiles/master_cv.json`, and the
active Studio draft is updated immediately so **Compile preview** shows it.

### Portfolio Builder

The Portfolio tab generates a static site in:

```text
.job_agent/portfolio/
```

Use **Generate portfolio** after choosing a theme/font. The preview is served
locally, and the HTML/CSS editors write back to the same folder. **Export ZIP**
creates `.job_agent/portfolio/portfolio_export.zip`. **Publish checklist**
creates `.job_agent/portfolio/PUBLISHING.md` with local steps for GitHub
Pages, Netlify, or Vercel. Nothing is uploaded automatically.

## LaTeX CV output

Every generated packet includes an editable `cv.tex` next to `cv.md`,
`cv.html`, and `cv.pdf`. The renderer is conservative: when
`profiles/main.tex` exists, the template's `moderncv` design, language
toggle, photo, and curated skills narrative are preserved. Only the parts
that should change per job are rewritten:

- **`\mysummary`**: keep the master narrative; append one short sentence that
  names the target role/company and the top matching skills. Updated in both
  the English and French branches of the language toggle.
- **`\expone / \exptwo / \expthree`**: bullets re-ranked so the most relevant
  ones appear first (no facts invented, no metrics added).
- **`\projone`**: most relevant project from `master_cv.json` for this role.
- **Skills sections**: untouched. Your curated `Classification/Regression,
  Time-Series Forecasting…` text stays as-is so the CV reads naturally.

If a LaTeX compiler is visible to the terminal that launched the app, `cv.pdf`
is built from `cv.tex`. When Perl is installed, the compiler order is
`latexmk`, then `pdflatex`, `xelatex`, and `lualatex`. Without Perl, the app
prefers `pdflatex` first because MiKTeX can run it directly.

If no compiler is visible, the app still writes the tailored `cv.tex`. For the
PDF fallback, it first copies `profiles/CV.pdf` if present so your original CV
design is preserved; that copied PDF is not role-tailored. If no master PDF is
available, it generates a plain role-tailored Markdown PDF and adds
`latex_warning.txt` to the packet folder.

On Windows, install one of:

```text
MiKTeX:    https://miktex.org/download
TeX Live:  https://tug.org/texlive/windows.html
```

After installing, restart PowerShell and verify:

```powershell
pdflatex --version
```

Then re-generate the packet:

```powershell
job-agent apply <job-id> --force
```

### Import a CV template/photo locally

Use **Profile & API -> CV template import** or the CLI:

```powershell
job-agent import-cv-template C:\path\to\main.tex
job-agent import-cv-template C:\path\to\me.jpg
job-agent import-cv-template C:\path\to\CV.pdf
```

`.tex` uploads replace `profiles/main.tex` after creating a timestamped
backup, so future packets preserve that LaTeX layout and only tailor safe
role-specific text. `.jpg/.jpeg` becomes `profiles/me.jpg`. `.pdf` becomes
`profiles/CV.pdf`, used as a design fallback if LaTeX compilation ever fails.
`.docx` is stored as `profiles/source_cv.docx` for reference; exact DOCX/PDF
to editable LaTeX conversion is not reliable enough to automate silently.

## France / Paris workflow

### 1. See setup instructions

```bash
job-agent france-setup
```

### 2. Generate manual search URLs for French job boards

```bash
job-agent france-search-urls --query "data science stage" --location Paris
job-agent france-search-urls --query "machine learning alternance" --location "Île-de-France"
job-agent france-search-urls --query "data scientist" --location Paris --language french --limit 8
job-agent france-search-urls --query "data scientist" --location Paris --format table
job-agent france-search-urls --query "data scientist" --location Paris --format json --output france_urls.json
```

Open promising URLs, copy job URLs, then import them:

```bash
job-agent add url "https://company-or-job-board/job-url"
job-agent apply <job-id>
job-agent apply-assist <packet-id>
```

### 3. Use France Travail API when configured

France Travail requires free developer credentials/habilitation for the API.
Your normal candidate login is separate. After approval, set:

```powershell
[Environment]::SetEnvironmentVariable("FRANCE_TRAVAIL_CLIENT_ID", "your-client-id", "User")
[Environment]::SetEnvironmentVariable("FRANCE_TRAVAIL_CLIENT_SECRET", "your-client-secret", "User")
[Environment]::SetEnvironmentVariable("FRANCE_TRAVAIL_SCOPE", "api_offresdemploiv2 o2dsoffre", "User")
```

Or put them in a git-ignored `.env.local` at the repo root:

```text
FRANCE_TRAVAIL_CLIENT_ID=your-client-id
FRANCE_TRAVAIL_CLIENT_SECRET=your-client-secret
FRANCE_TRAVAIL_SCOPE=api_offresdemploiv2 o2dsoffre
```

The app auto-loads `.env.local` when it starts. If your portal does not show a
scope, leave `FRANCE_TRAVAIL_SCOPE` blank — fallback scope logic runs.

### 4. (Optional) Configure France Travail enrichment endpoints

To use ROME 4.0, Anotea, Open Training, Labour Market, etc., copy
`docs/france_travail_endpoints.example.json` to
`.france_travail.endpoints.local.json` at the repo root and fill the paths
from your developer portal. This file is git-ignored.

Then:

```powershell
job-agent enrich <job-id>
```

Without this file, only the core job-offer search works — enrichment is
skipped safely.

### 5. Target CAC 40 / large French companies

```bash
job-agent france-targets
```

Open the career page, search for `data`/`stage`/`alternance`, import promising
URLs with `job-agent add url`.

### 6. Run the built-in Paris data/AI query pack

```bash
job-agent france-hunt --location Paris --limit 10
job-agent france-hunt --location Ile-de-France --limit 10 --internships-only
job-agent france-hunt --location Paris --radius-km 25 --min-relevance 50 --internships-only
```

Tries queries like `data scientist stage`, `machine learning internship`,
`alternance data science`, `junior data scientist`, etc.

`--min-relevance 50` is the smart cleanup mode: it keeps data/AI/BI roles and
drops obvious noise such as cancer registry abstractor, product marketing,
maintenance, non-EU, and senior/PhD-gated jobs. Use `--min-relevance 0` when
you intentionally want a broad sweep.

## Multi-source search (no credentials, no boards needed)

```bash
job-agent multi-search --query "data scientist" --location Paris --limit 8 --save --min-relevance 50 --france-eu-only
```

Hits Remotive, Remote OK, Himalayas, Arbeitnow, Jobicy, and The Muse at once
and dedupes by URL. Each source can fail without breaking the others.

## Generic API search

```bash
job-agent api-sources
```

Supported sources:

```text
arbeitnow, ashby, francetravail, greenhouse, himalayas, jobicy,
labonnealternance, lever, personio, recruitee, remoteok, remotive,
smartrecruiters, themuse, workable
```

For company ATS boards, pass the slug:

```bash
job-agent search-api greenhouse --board example-company --query "data" --save
job-agent search-api lever --board example-company --query "machine learning" --save
job-agent search-api ashby --board ExampleCompany --query "data" --save
job-agent search-api recruitee --board examplecompany --query "data" --save
job-agent search-api smartrecruiters --board examplecompany --query "data" --save
job-agent search-api workable --board examplecompany --query "data" --save
job-agent search-api personio --board examplecompany --query "data" --save
```

For La bonne alternance (apprentissage/alternance), no board slug is needed:

```bash
job-agent search-api labonnealternance --query "data scientist" --location "Ile-de-France" --radius-km 30 --internships-only --save
```

## Local AI with Ollama

If [Ollama](https://ollama.com/) is running locally, the app auto-detects
installed models and selects the best available one. For example, if your
machine has `qwen3.6:latest`, the app uses that model instead of assuming a
different default.

Check readiness and generate an AI query plan:

```powershell
job-agent ai-status
job-agent smart-plan --query "data scientist" --location Paris --limit 8
```

Local AI is used for smart query planning, Autopilot search expansion, AI fit
analysis, dashboard **AI fit**, per-job chat, and packet `ai_fit_brief.md`
files. The dashboard separates the heavy analysis model from the fast chat
model: for example `qwen3.6:latest` for analysis and `llama3.2:3b` for quick
chat. The Autopilot tab has one-click **Start Ollama** and **Pull fast chat
model** buttons.

Polishing generated prose is still opt-in. Enable it only when you want the
model to rewrite CV bullets/paragraphs:

```powershell
$env:JOB_AGENT_USE_OLLAMA = "1"
$env:JOB_AGENT_OLLAMA_MODEL = "qwen3.6:latest"   # or any local model
job-agent apply <job-id> --force
```

Guarantees:

- All numbers from the original bullet must appear in the polished version
  (no new numbers, no removed numbers).
- Bag-of-words overlap ≥ 55% — drastic drift is rejected.
- Polished text can't be more than 1.4× the original length.
- If any check fails (or Ollama is unreachable), the **original bullet is
  used unchanged**. Polishing never blocks the pipeline.

Disable prose polishing by unsetting `JOB_AGENT_USE_OLLAMA`. Query planning
and AI fit analysis still work when Ollama is running.

### AgentCore-style local routing

The app does not send prompts to paid cloud models by default, but local AI can
still become slow if every task uses the largest model. Job Agent now routes
AI work through a three-tier local stack:

- **L1 Sentry:** fast model for chat, job classification, short summaries, and
  search-query planning.
- **L2 Worker:** fast operational model for normal structured tasks.
- **L3 Architect:** heavier model for fit analysis, CV/cover-letter strategy,
  and longer-context drafting.

Each call writes a prompt-free trace to `.job_agent/ai_traces.jsonl` with task,
tier, selected model, estimated input tokens, latency, and success/failure. The
trace never stores CV text, job descriptions, secrets, or chat content.

## AI smart mode — local-only, on by default when Ollama runs

When a local Ollama server is reachable, the agent unlocks five capabilities,
all grounded in your profile + the job posting and validated for hallucination
before they reach your CV / cover letter:

1. **Fit analysis** (`/api/ai-analyze`) — verdict (strong / moderate / weak),
   0-100 score, strengths, gaps, suggested-emphasis bullets. Surfaced as fit
   notes on the packet and a colored badge on the job row.
2. **Classifier** — tags, seniority, role family, contract type, remote mode,
   must-haves and nice-to-haves. Used to filter and group jobs visually.
3. **TL;DR summary** — 2-sentence pitch for fast scanning, shown right below
   the job title in the table.
4. **Cover-letter drafter** — replaces the deterministic body with 3 AI
   paragraphs that must keep ≥55% vocabulary overlap with your profile + the
   job. Otherwise the deterministic fallback is used.
5. **Chat about a job** — open the **Chat** button on any row to ask
   "Should I apply?", "What should I emphasize?", "Where will I struggle?".
   Replies are rejected if vocabulary overlap drops below 25%.

All five are cached in a local `ai_cache` SQLite table per job + model — the
model only runs once per job and stays warm across reloads.

The selected model is the first available one matching your install. The
qwen3.6 family is detected automatically. Set `JOB_AGENT_OLLAMA_MODEL` to pin
a different model.

The `main.tex` CV summary stays conservative: the master narrative is
preserved and only the role-specific closing sentence is updated. AI is used
for insights and chat, never to invent a new CV identity.

## Autopilot — autonomous job hunting

Open the **Autopilot** tab. Configure interval (e.g. 30 min), queries, and
auto-packet score threshold. Click **Start**. The background loop will:

1. Build a smart local-AI query plan when Ollama is reachable.
2. Search France Travail (if credentials are set) + multi-source aggregators.
3. Deduplicate against the local database.
4. Score every new job against your profile.
5. Auto-generate tailored packets for jobs that beat the threshold.
6. Optionally write a local email-style notification for strong matches.

Autopilot itself **does not submit applications**. It discovers jobs, scores them,
deduplicates them, and can prepare packets for strong matches. Submitting applications
is controlled separately by the apply-mode toggle:

- **Full Auto OFF** -> Fill & Confirm.
- **Full Auto ON** -> Full Auto.

Autopilot never bypasses login walls, CAPTCHAs, anti-bot checks, rate limits,
or platform access controls.

Email notifications are optional. With **Notify me for strong matches** on,
Autopilot always writes a local `.eml` file under `.job_agent/notifications`.
If you also set SMTP env vars (`JOB_AGENT_NOTIFY_EMAIL=1`,
`JOB_AGENT_NOTIFY_TO`, `JOB_AGENT_SMTP_HOST`, etc.), it sends the same message
to you. The notification contains the job, score, apply URL, and packet paths;
it never submits anything.

## GitHub & LinkedIn enrichment

```bash
job-agent enrich-github                    # uses contact.github_url, no auth
job-agent enrich-github --handle your-username   # explicit handle override
job-agent enrich-linkedin --file linkedin_skills.txt
```

GitHub enrichment pulls your public profile + repos via the public REST API,
weighs languages by byte count, and merges new skills/projects into your
profile JSON files without overwriting existing curated entries.

LinkedIn requires login (cannot be scraped legally), so the workflow is:
copy the Skills section from your profile and paste it into the **Add LinkedIn
skills** modal on the Autopilot tab — endorsement counts and bullet glyphs
are stripped automatically.

## External Agent / OpenClaw Review

Every packet now includes `external_agent_prompt.md`. Use it with OpenClaw or
another local reviewer to critique the packet before you apply:

```powershell
openclaw .job_agent\outputs\<company_jobid>\packet_vN\external_agent_prompt.md
```

The prompt forbids invented facts, unarmed submissions, login-wall bypass,
access-control circumvention, and unsafe screening answers. It asks for
file-specific edits only.

## One-command processing

```bash
job-agent process file path/to/job.txt --title "Data Scientist Intern" --company "Company" --url "https://company.com/apply"
```

Does: `ingest -> normalize -> dedupe -> filter -> score -> generate packet`.

## CLI reference

```text
job-agent init
job-agent copy-examples
job-agent setup-wizard [--non-interactive]
job-agent ai-status
job-agent smart-plan [--query ...] [--location ...] [--limit N]
job-agent enrich-github [--handle ...] [--no-projects]
job-agent enrich-linkedin [--file PATH]
job-agent validate-profile
job-agent ui [--host 127.0.0.1] [--port 8765] [--no-open]
job-agent france-setup
job-agent france-search-urls [--query ...] [--location ...] [--language english|french|both] [--boards recommended|all] [--format list|table|json] [--output PATH]
job-agent france-targets [--limit N]
job-agent france-hunt [--query ...] [--location Paris] [--limit N] [--packets/--no-packets] [--internships-only]
job-agent enrich <job-id> [--rome] [--anotea] [--training] [--labour-market] [--territory] [--employer]
job-agent export internships [--workbook PATH] [--sheet NAME]
job-agent import-cv-template PATH
job-agent add paste [--title ...] [--company ...] [--url ...]
job-agent add file PATH [--title ...] [--company ...] [--url ...]
job-agent add url URL
job-agent add rss FEED_URL [--limit N]
job-agent discover-links URL [--limit N]
job-agent api-sources
job-agent multi-search [--query ...] [--location ...] [--sources a,b,c] [--limit N] [--save] [--remote-only] [--internships-only] [--min-relevance N] [--france-eu-only/--worldwide]
job-agent search-api SOURCE [--query ...] [--location ...] [--country ...] [--board ...] [--limit N] [--remote-only] [--min-relevance N] [--radius-km N] [--cache/--no-cache] [--save]
job-agent hunt SOURCE [--query ...] [--location ...] [--country ...] [--board ...] [--limit N] [--remote-only] [--cache/--no-cache] [--force]
job-agent list [--status STATUS]
job-agent show JOB_ID
job-agent score JOB_ID
job-agent apply JOB_ID [--force]
job-agent process file PATH [--title ...] [--company ...] [--url ...] [--force]
job-agent apply-assist PACKET_ID [--no-open-browser]
job-agent mark-submitted PACKET_ID [--note ...]
job-agent status JOB_ID STATUS [--note ...]
job-agent delete-job JOB_ID --yes
job-agent history JOB_ID
job-agent packet show JOB_OR_PACKET_ID
```

## Safety rules

- Never invent experience, education, metrics, certifications, dates, legal
  facts, visa facts, work authorization, language level, school/program,
  availability, or salary expectations.
- Never infer sponsorship claims in the CV, cover letter, outreach, screening
  answers, or auto-apply fields.
- Never answer unknown factual screening questions automatically.
- Never bypass CAPTCHAs, login restrictions, paywalls, platform rate limits,
  anti-bot checks, or access controls.
- Never scrape logged-in LinkedIn / Indeed / Glassdoor / Welcome to the
  Jungle pages or automate account actions on those platforms.
- Never submit outside an explicitly chosen apply mode.
- **Full Auto OFF** is the default browser behavior: Fill & Confirm fills supported forms and waits for user submit.
- **Full Auto ON** enables `FULL_AUTO`: eligible supported applications may be submitted automatically without per-job human interaction.
- Full Auto must hand off uncertain, unsupported, unknown-answer, or human-presence cases to `NEEDS_MANUAL`.
- Keep every generated artifact traceable with hashes.
- Keep candidate data and application history local by default.

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
  analytics.py            # local stats, CSV export
  polish.py               # optional Ollama bullet polish (strict)
  cli/main.py             # standard-library CLI
  db/database.py          # SQLite layer
  generator/              # CV, cover letter, QA
  intake/                 # paste, file, URL, RSS, link discovery, APIs, France market helpers
  renderer/               # markdown, HTML, PDF, LaTeX, assistant page
  schemas/                # Pydantic-compatible models
  ui/                     # local web dashboard
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
  preview_cv.py           # render a sample cv.tex for quick inspection
examples/
  candidate_profile.json
  master_cv.json
  master_qa_profile.json
tests/
```
