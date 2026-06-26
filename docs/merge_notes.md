# Merge notes

This repo uses the Copilot repo as the base and ports the strongest parts of the scaffold:

- stronger QA schema
- profile validation
- packet artifacts with SHA-256 hashes
- application assistant HTML page
- standard locked QA answers on assistant page
- no inferred visa/sponsorship language
- hard-filter blocking unless `--force`
- improved normalizer and 0-100 scoring
- link discovery command
- process command for one-command packet creation
- Click CLI for stable local execution
- expanded end-to-end tests

The old Typer CLI was replaced with Click because the available Typer/Click versions can break option parsing in some environments. Command names remain the same or are expanded.

Additional merged capabilities:

- conservative extraction of explicit screening questions from job text
- free/read-only public job API intake for Remotive, Remote OK, Himalayas, Arbeitnow, Greenhouse, Lever, and Ashby
- `search-api`, `api-sources`, and `hunt` commands for automated search/import/packet preparation without default submission; actual browser submission is controlled separately by the Full Auto toggle: Full Auto OFF -> `FILL_AND_CONFIRM`, Full Auto ON -> `FULL_AUTO`
- distinct packet version output directories to avoid overwriting previous packet artifacts

## Apply-mode merge decision

The old scaffold's confirmation-only posture has been superseded. The merged project now has a user-controlled Full Auto toggle:

- `MANUAL_PACKET` for artifact generation only.
- Full Auto OFF -> `FILL_AND_CONFIRM`: browser fill + user submit.
- Full Auto ON -> `FULL_AUTO`: automatic submit for eligible supported applications without per-job human interaction.

This does not permit logged-in board scraping, CAPTCHA solving, anti-bot bypass, rate-limit bypass, or invented screening answers. Those cases must hand off to `NEEDS_MANUAL`.
