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

## Why not LinkedIn/Indeed/Glassdoor/WTTJ auto-apply?

These platforms do not provide a free public personal applicant-side search-and-apply API suitable for this local project. Their official APIs are partner/employer/ATS oriented, authenticated, or require agreements. Browser automation against logged-in job boards is intentionally out of scope because it is fragile and can violate platform rules.

## France Travail setup

```bash
export FRANCE_TRAVAIL_CLIENT_ID="..."
export FRANCE_TRAVAIL_CLIENT_SECRET="..."
export FRANCE_TRAVAIL_SCOPE="api_offresdemploiv2 o2dsoffre"
job-agent search-api francetravail --query "data scientist stage" --location Paris --save
```

Use `job-agent france-setup` for instructions.
