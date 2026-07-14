---
name: free-job-agent
description: Drive the free-job-agent local job-search copilot through its argparse CLI or read-only MCP stdio tools. Use for France/EU job discovery, fit scoring, job intelligence, application packet generation, tracker updates, and recurring skill-gap analysis.
---

# free-job-agent

## Purpose

Use free-job-agent as a local-first, free-only job-search and application copilot for France and the EU. Keep candidate profiles, job data, scoring, packets, and tracking local by default.

## MCP stdio server

Launch the server from a Python environment where free-job-agent is installed:

```bash
python -m job_agent.mcp_server
```

For an MCP client, configure `python` as the command and `-m job_agent.mcp_server` as its arguments. Communicate with the process over stdio. The server exposes three read-only tools.

### `score_job_fit`

Score pasted job text against the configured candidate profile and return a deterministic fit breakdown.

- `job_text` (string, required): complete job description.
- `title` (string, optional): job title when known.
- `company` (string, optional): employer name when known.
- `location` (string, optional): job location when known.

### `extract_job_intel`

Normalize pasted job text and extract fields such as title, location, tech stack, salary, seniority, remote/work mode, and implied skills.

- `job_text` (string, required): complete job description.

### `evaluate_job_quality`

Apply hard filters and search-quality checks, returning a pass/reject decision, reasons, risk flags, and quality signals.

- `job_text` (string, required): complete job description.
- `title` (string, optional): job title when known.

## CLI workflows

Run `job-agent api-sources` to list supported free/read-only sources before selecting a source.

Search one public API and optionally save results to the local tracker:

```text
job-agent search-api <source> --query "data scientist" --location "Paris" --save
```

Search several free/public APIs, deduplicate results, and save them:

```text
job-agent multi-search --query "data scientist" --location "Paris" --save
```

Score a tracked job against the local candidate profile:

```text
job-agent score <job-id>
```

Generate the full local application packet for a tracked job:

```text
job-agent apply <job-id>
```

Use the local tracker from the CLI:

- `job-agent list --status <status>` lists tracked jobs, optionally filtered by status.
- `job-agent status <job-id> <new-status>` updates a job's status.
- `job-agent history <job-id>` shows the job's event history.

Rank recurring gaps across lower-scoring tracked jobs:

```text
job-agent gap-report --threshold 70 --top 10
```

## Hard constraints

- Never invent candidate facts. Use only facts present in the local evidence/profile store; leave unknown facts blank and flag them for the user.
- Keep candidate data, job data, packets, traces, and analytics local by default.
- Use only free capabilities: public/read-only APIs, free tiers, already-owned services, and local models. Do not require paid scraping, paid browser agents, paid CAPTCHA solving, or paid LLM APIs.
- Never scrape logged-in job boards such as LinkedIn, Indeed, Welcome to the Jungle, or Glassdoor. Use public endpoints, safe manual search URLs, or user-supplied public job content.
- Never bypass CAPTCHA, anti-bot, login, rate-limit, paywall, or human-presence controls.
