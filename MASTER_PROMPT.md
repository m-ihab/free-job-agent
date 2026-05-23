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
1. Improve France Travail field mapping, radius/region handling, contract filters, and search-quality cleanup.
2. Add richer CV bullet tagging for data/AI roles (done — bullets are reordered by job-relevance keywords).
3. Add CAC 40 company-board slug mapping only where public ATS endpoints are stable and safe.

Recently shipped:
- Multi-source aggregated search (Remotive, Remote OK, Himalayas, Arbeitnow, Jobicy, The Muse) with per-source error isolation, synonym expansion, and word-boundary title matching.
- Free company ATS connectors: Greenhouse, Lever, Ashby, Recruitee, SmartRecruiters, Workable, Personio.
- Analytics: funnel, weekly throughput, top companies/sources/locations, score distribution. Rendered as real Chart.js charts.
- CSV export of tracked jobs.
- Profile setup wizard (`job-agent setup-wizard`) for stage/alternance fields.
- GitHub enrichment via public API (skills + repos) and LinkedIn skills paste merge.
- Conservative LaTeX renderer: preserves user's `main.tex` curated narrative; only summary closing sentence + experience bullet ordering + top project change per role. Photo and skills sections untouched.
- pdflatex/latexmk picker: prefers latexmk when Perl is available, falls back to pdflatex otherwise.
- Master CV.pdf fallback when LaTeX compilation fails.
- AI agent module (`ai_agent.py`) with local-Ollama integration:
  - `analyze_fit` — JSON verdict/score/strengths/gaps/suggested_emphasis.
  - `classify_job` — tags, seniority, role family, contract, remote_mode, must/nice haves.
  - `summarize_job` — 2-sentence TL;DR + key signals.
  - `draft_cover_letter_body` — 3 paragraphs with ≥55% vocabulary-overlap validation.
  - `chat_about_job` — grounded Q&A with ≥25% overlap check.
  - `suggest_search_queries` — AI-planned bilingual queries with deterministic fallback.
- AI results cached in `ai_cache` SQLite table per (job_id, kind).
- Autopilot background loop: AI query planner → France Travail + multi-source → score → auto-packet for high-fit jobs. SSE stream for live UI status.
- Dashboard upgrades: Chart.js charts, light/dark theme toggle, AI badges on job rows, inline TL;DR, AI chat modal, keyboard shortcuts, accessible color tokens, sticky header.
- Search-quality scoring to hide obvious noise (cancer registry, product marketing, maintenance, non-EU, senior/PhD-gated jobs) without deleting broad-search capability.
- One-click Ollama launch/pull flow with separate heavy analysis and fast chat models.
- Local CV template/photo import: editable `.tex` replaces `profiles/main.tex`; PDF/DOCX/image uploads stay in git-ignored `profiles/`.
- Job removal from dashboard/CLI, inline PDF CV preview, and optional local/email notifications for strong Autopilot matches.
- Easy Windows launchers: `launch.ps1` and `launch.bat`.
- Optional npm + Playwright e2e tests (`npm run test:e2e`).

Open ideas worth exploring next:
- Diff view between packet versions.
- Auto-tagging by ROME / O*NET categories using local TF-IDF.
- Multi-model A/B comparisons for AI fit.
- Calendar reminders for follow-up dates after manual submission.
