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
- conservative extraction of explicit screening questions from job text
- free/read-only public job API intake for Remotive, Remote OK, Himalayas, Arbeitnow, Greenhouse, Lever, and Ashby
- `search-api`, `api-sources`, and `hunt` commands for automated search/import/packet preparation without auto-submit
- distinct packet version output directories to avoid overwriting previous packet artifacts

