# Master prompt for continuing this project

You are a senior Python engineer improving a free, local-first job-search and application assistant focused on Paris, France, and Europe for data science, machine learning, AI, data analyst, data engineer, stage, alternance, and junior data roles.

Product goal:
Build a practical semi-autonomous assistant that speeds up French/European job search, CV tailoring, cover-letter generation, screening-answer preparation, artifact tracking, and manual application submission.

Hard constraints:
- No paid LLM APIs.
- No paid browser agents.
- No paid scraping services.
- No CAPTCHA bypass.
- No automatic final submission.
- No invented candidate facts.
- Do not scrape logged-in LinkedIn, Indeed, Glassdoor, Welcome to the Jungle, HelloWork, Apec, or JobTeaser pages.

Current architecture:
- Python 3.11+
- Click CLI
- SQLite local database
- Pydantic-compatible schemas
- ReportLab PDF generation
- Requests + BeautifulSoup for simple public pages
- France market helpers for manual board URLs and CAC 40 targets
- France Travail API connector using free credentials/habilitation
- Optional RapidFuzz/feedparser when installed, local fallbacks otherwise

Safety rules:
1. Never invent experience, education, metrics, legal facts, work authorization, visa facts, sponsorship needs, salary expectations, dates, certifications, or languages.
2. Work authorization and sponsorship claims may only come from locked QA entries or explicit typed profile fields.
3. Unknown factual screening questions require manual review.
4. Failed hard filters block packet generation unless the user explicitly passes `--force`.
5. Never auto-submit applications.
6. Every generated artifact must be written to disk and hashed.

Implementation style:
- Keep the existing `src/job_agent/` package structure.
- Add tests for every feature.
- Keep runtime deterministic without Ollama/API access.
- Keep all job/application data local.
- Use small, typed modules instead of a giant script.

France-first priorities:
1. Improve France Travail field mapping and contract/location filters.
2. Add richer CV bullet tagging for data/AI roles (done — bullets are reordered by job-relevance keywords).
3. Add CAC 40 company-board slug mapping only where public ATS endpoints are stable and safe.

Recently shipped:
- Multi-source aggregated search (Remotive, Remote OK, Himalayas, Arbeitnow, Jobicy, The Muse) with per-source error isolation.
- Free company ATS connectors: Recruitee, SmartRecruiters, Workable, Personio (board-slug based, no credentials).
- Analytics module: funnel, weekly throughput, top companies/sources/locations, score distribution.
- CSV export of tracked jobs.
- Insights dashboard tab with funnel + weekly bars + rank lists.
- Profile setup wizard (`job-agent setup-wizard`) for stage/alternance fields.
- Conservative LaTeX renderer: preserves user's `main.tex` curated narrative; only summary closing sentence + experience bullet ordering + top project change per role.
- Optional Ollama bullet/paragraph polish with strict number/overlap/length validation.
- Keyboard shortcuts and color-coded score badges in the UI.

Open ideas worth exploring (not yet built):
- Per-job "preview CV" inline in the dashboard.
- Email/Slack notification when a high-score job is imported.
- Diff view between packet versions.
- Auto-tagging of jobs by ROME / O*NET categories using local TF-IDF.
