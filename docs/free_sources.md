# Free/read-only job sources for France / Paris data-AI search

This project is designed for a free local workflow. It uses official/free read-only APIs where possible, and manual search URL helpers where no suitable free public applicant API exists.

## Implemented read-only API-style sources

- `francetravail` — France Travail Offres d'emploi API. Free credentials/habilitation required.
- `arbeitnow` — free Europe/remote job board API.
- `remotive`, `remoteok`, `himalayas` — useful for remote/global roles, less central for Paris.
- `greenhouse`, `lever`, `ashby` — public company ATS boards when you know the company board slug.

## Manual France job-board helpers

`job-agent france-search-urls` generates search URLs for:

- France Travail web search
- Welcome to the Jungle
- HelloWork
- Apec
- Indeed France
- LinkedIn Jobs France
- Glassdoor France
- Stage.fr
- JobTeaser
- La bonne alternance

These are not scraped automatically. Open the URLs, review jobs, then import promising job URLs with `job-agent add url`.

## Why not logged-in LinkedIn/Indeed/Glassdoor/WTTJ automation?

These platforms do not provide a free public personal applicant-side search-and-apply API suitable for this local project. Their official APIs are partner/employer/ATS oriented, authenticated, or require agreements.

Do not scrape or automate logged-in LinkedIn, Indeed, Glassdoor, Welcome to the Jungle, or similar job-board account flows.

This does **not** ban Job Agent's own local apply-mode toggle for supported public or direct application flows:

- `MANUAL_PACKET`: generate packet artifacts only.
- **Full Auto OFF** -> `FILL_AND_CONFIRM`: fill supported forms, then wait for user review and submit.
- **Full Auto ON** -> `FULL_AUTO`: fill and submit eligible supported applications without per-job human interaction.

`FULL_AUTO` must hand off to `NEEDS_MANUAL` when it encounters login walls, CAPTCHAs, anti-bot checks, rate limits, unknown required fields, unsupported forms, failed uploads, unclear submit state, or unknown factual answers. Detection is allowed; bypass is not.

## France Travail setup

```bash
export FRANCE_TRAVAIL_CLIENT_ID="..."
export FRANCE_TRAVAIL_CLIENT_SECRET="..."
export FRANCE_TRAVAIL_SCOPE="api_offresdemploiv2 o2dsoffre"
job-agent search-api francetravail --query "data scientist stage" --location Paris --save
```

Use `job-agent france-setup` for instructions.
