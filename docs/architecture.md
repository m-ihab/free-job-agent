# Architecture

free-job-agent is a free, local-first job-search, application, and conversion copilot for Paris / France / Europe data, AI, ML, analyst, data engineering, stage, alternance, apprenticeship, internship, and junior roles.

```text
candidate_profile.json
master_cv.json
master_qa_profile.json
profiles/main.tex
GitHub / LinkedIn manual enrichment
        |
        v
Profile validation + locked factual fields
        |
        v
Job discovery / intake
  - paste
  - file
  - public URL
  - RSS
  - free/read-only APIs
  - France Travail
  - La bonne alternance when token configured
  - public ATS feeds
  - manual French board URLs
        |
        v
Normalization
  - title
  - company
  - location / remote
  - seniority
  - contract type
  - salary
  - language requirements
  - work-authorization signals
  - requirements / responsibilities
  - tech stack
        |
        v
Fingerprinting + company canonicalization + dedupe
        |
        v
Hard filters + deterministic fit scoring
        |
        v
Application preflight
  - apply / edit / manual / skip verdict
  - missing must-haves
  - ATS keyword gap
  - evidence map
  - unknown screening answers
  - risk flags
        |
        v
Packet generation
  - tailored CV
  - cover letter
  - locked QA answers
  - application brief
  - outreach / follow-up drafts
  - proof pack / portfolio links
        |
        v
Renderers + artifact hashes
  - Markdown
  - HTML
  - PDF
  - LaTeX
  - assistant.html
        |
        v
Apply behavior
  - MANUAL_PACKET: packet only, no browser submission
  - Full Auto OFF -> FILL_AND_CONFIRM: fill form, wait for user submit
  - Full Auto ON  -> FULL_AUTO: fill and submit eligible jobs automatically
        |
        v
Fail-closed handoff
  - CAPTCHA / anti-bot
  - login wall
  - rate limit
  - unsupported ATS
  - unknown required field
  - unknown factual answer
  - upload failure
  - unclear submit state
        |
        v
SQLite tracker + application events
        |
        v
Pipeline / Conversion cockpit
  - next-best action
  - freshness / timing urgency
  - follow-up due
  - outreach sent
  - local referral contacts and warm paths
  - local job notes
  - reply / interview / offer tracking
  - needs-manual queue
  - stale detection
  - conversion metrics
        |
        v
Learning loop
  - source quality
  - score calibration
  - outreach reply rate
  - follow-up effectiveness
  - manual vs full-auto outcomes
```

## Grounding And Work Authorization

- `evidence.py` builds a local `evidence_items` index from existing profile,
  master CV, and locked QA facts. It does not synthesize facts; generators and
  preflight features should query this store before adding claims or keywords.
- `generator/evidence_map.py`, `generator/ats_gap.py`, and
  `generator/preflight.py` turn that evidence into a per-job verdict:
  `APPLY`, `APPLY_WITH_EDITS`, `NEEDS_MANUAL`, or `SKIP`. The dashboard
  exposes this through `/api/preflight`, and generated packet folders include
  `preflight.json` as a defensibility trace.
- `generator/proof_pack.py` turns the same preflight result into
  `proof_pack.md`, a local recruiter/interview prep artifact with defensible
  strengths, safe keywords, missing must-haves, and unsupported claims to avoid.
- `work_auth.py` routes jobs by contract kind (`stage`, `alternance`, `CDI`,
  `CDD`, etc.). For non-EU student profiles, stage/alternance can be directly
  applicable when the profile explicitly contains stage/convention facts, while
  CDI/permanent roles that need sponsorship are flagged as `SPONSORSHIP_GATED`.
- Stage gratification warnings are opt-in via `france_gratification_min_hourly`;
  the application does not hardcode statutory thresholds that can become stale.
- `timing.py`, `referral.py`, and `conversion.py` build the local Pipeline
  cockpit: forward status mapping, freshness-aware next-best actions, stale
  detection, conversion metrics, private job notes, local contacts, warm-path
  matching, and grounded referral asks. They read existing tracker/profile data
  and do not drive browser submission.

## Apply-mode contract

The system is local-first, but browser submission is controlled by the Full Auto toggle:

| Toggle state | Browser mode | Behavior |
|---|---|---|
| Full Auto OFF | `FILL_AND_CONFIRM` | Opens and fills a supported form, then waits for the user to review and click Submit. |
| Full Auto ON | `FULL_AUTO` | Runs without per-job human interaction and submits eligible supported applications automatically. |

`MANUAL_PACKET` is a separate packet-only path that generates artifacts and assistant pages without driving browser submission.

`FULL_AUTO` must fail closed. CAPTCHA, anti-bot checks, login walls, rate limits, unsupported forms, unknown required fields, unknown factual screening answers, failed uploads, unclear submit state, post-submit human walls, or detection failures become `NEEDS_MANUAL`. The run records the reason and continues without bypassing the wall.

## Non-goals

- No paid scraping.
- No paid browser agents.
- No paid CAPTCHA solvers.
- No cloud job-data storage by default.
- No invented candidate facts.
- No logged-in scraping of LinkedIn, Indeed, Welcome to the Jungle, Glassdoor, or similar job boards.
- No bypassing access controls or human-presence checks.

## Product direction

The core architecture should evolve from a packet generator into a conversion OS:

```text
discovery -> qualification -> proof -> apply/outreach -> follow-up -> interview -> learning
```
