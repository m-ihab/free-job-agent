# Full Auto Contract

`FULL_AUTO` is a supported apply mode in free-job-agent.

The product narrative is toggle-based:

- **Full Auto OFF** means `FILL_AND_CONFIRM`: fill supported forms, then wait for the user to review and click Submit.
- **Full Auto ON** means `FULL_AUTO`: fill and submit eligible supported applications automatically without per-job human interaction.

The user's act of turning Full Auto ON for a run is the mode choice for automatic submission. Full Auto must not pause to ask for per-job confirmation; that behavior belongs to Fill & Confirm.

## Modes

| User choice | Internal mode | Behavior |
|---|---|---|
| Packet only | `MANUAL_PACKET` | Generate application artifacts only. No browser submission. |
| Full Auto OFF | `FILL_AND_CONFIRM` | Fill the form, then wait for the user to submit. |
| Full Auto ON | `FULL_AUTO` | Submit eligible jobs unattended. |

## Full Auto requirements

A `FULL_AUTO` run must have:

- an explicit Full Auto ON choice for the run;
- max submission count;
- minimum score threshold;
- allowed source or ATS list where supported;
- skip rules;
- dedicated browser profile by default;
- local attempt logs;
- visible cancellation control when implemented;
- fail-closed handoff behavior.

## Attempt log fields

Every attempt should record:

```text
job_id
packet_id
packet_hash
mode
full_auto_toggle
source
ats_detected
preflight_verdict
score
fields_filled
unknown_fields
files_uploaded
submitted
handoff_reason
error_code
timestamp
```

## Must hand off to NEEDS_MANUAL

`FULL_AUTO` must not continue submission for a job when it sees:

- CAPTCHA;
- anti-bot challenge;
- rate limit;
- login wall;
- paywall;
- unsupported ATS/page;
- unknown required field;
- unknown factual screening answer;
- missing work authorization fact;
- missing language fact;
- failed CV/cover-letter upload;
- unclear submit state;
- post-submit human wall;
- detection failure.

In those cases it must mark the job `NEEDS_MANUAL`, record the reason, and continue with the next eligible job without asking for mid-run human interaction.

## Never allowed

- CAPTCHA solving.
- Anti-bot bypass.
- Rate-limit bypass.
- Paywall bypass.
- Logged-in scraping of LinkedIn, Indeed, Glassdoor, Welcome to the Jungle, or similar boards.
- Invented candidate facts.
- Unknown screening answers guessed automatically.
- Paid browser agents or paid scraping platforms.
- Paid LLM APIs as a required feature.

## Default user promise

The default browser path is `FILL_AND_CONFIRM` with Full Auto OFF.

The power-user path is `FULL_AUTO` with Full Auto ON. It is hands-off, but it is not reckless: it fails closed to `NEEDS_MANUAL` instead of bypassing walls or guessing facts.

## Recommended UI copy

```text
Full Auto OFF: Fill & Confirm. Job Agent fills the form and waits for you to submit.
Full Auto ON: Full Auto. Job Agent fills and submits eligible applications automatically.
```
