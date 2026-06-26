# France / Paris Data & AI Market Strategy

This project is now focused on Paris, France, and Europe for data science, machine learning, AI, data analyst, data engineer, stage, alternance, and junior data roles.

## Priority sources

1. **France Travail API** — best official/free API-style source when credentials are configured.
2. **Manual French board URLs** — Welcome to the Jungle, HelloWork, Apec, Indeed France, LinkedIn France, Glassdoor France, Stage.fr, JobTeaser, La bonne alternance.
3. **Company career pages** — CAC 40 and large French companies.
4. **Public ATS boards** — Greenhouse, Lever, Ashby when a company uses one of those boards.
5. **Europe/remote APIs** — Arbeitnow, Remotive, RemoteOK, Himalayas.

## Commands

```bash
job-agent france-setup
job-agent france-search-urls --query "data science stage" --location Paris
job-agent france-targets
job-agent search-api francetravail --query "data scientist stage" --location Paris --save
job-agent france-hunt --location Paris --limit 10
```

## France Travail credentials

Set these after receiving free France Travail API credentials/habilitation:

```bash
export FRANCE_TRAVAIL_CLIENT_ID="..."
export FRANCE_TRAVAIL_CLIENT_SECRET="..."
export FRANCE_TRAVAIL_SCOPE="api_offresdemploiv2 o2dsoffre"
```

The default API base URL can be overridden if France Travail changes your integration details:

```bash
export FRANCE_TRAVAIL_API_BASE_URL="https://api.francetravail.io"
export FRANCE_TRAVAIL_TOKEN_URL="https://entreprise.francetravail.fr/connexion/oauth2/access_token?realm=/partenaire"
```

## Manual sources

Use `france-search-urls`, open the generated results in your browser, then import promising jobs:

```bash
job-agent add url "https://..."
job-agent apply <job-id>
job-agent apply-assist <packet-id>
```

## Why not scraping?

Logged-in job-board scraping remains out of scope. Do not scrape or automate logged-in LinkedIn, Indeed, Welcome to the Jungle, Glassdoor, or similar job-board account flows.

That is separate from Job Agent's local apply-mode toggle.

Supported workflow:

1. Use official/free APIs where available.
2. Generate manual French board search URLs.
3. Import promising public job URLs manually.
4. Use public ATS feeds when available.
5. Generate grounded packets locally.
6. Apply through the toggle:
   - **Full Auto OFF** -> `FILL_AND_CONFIRM`: fill supported forms and wait for the user to submit.
   - **Full Auto ON** -> `FULL_AUTO`: fill and submit eligible supported applications automatically.

`FULL_AUTO` must not bypass CAPTCHAs, login walls, anti-bot checks, rate limits, paywalls, or access controls. Human-presence walls and unknown factual questions become `NEEDS_MANUAL`.
