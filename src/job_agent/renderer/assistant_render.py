"""Render a local assisted-application page."""
from __future__ import annotations

import html
from pathlib import Path

from job_agent.schemas.candidate import CandidateProfile
from job_agent.schemas.job import JobListing
from job_agent.schemas.packet import DocumentArtifact, ScreeningAnswer


def _li(text: str) -> str:
    return f"<li>{html.escape(text)}</li>"


def render_assistant_page(
    *,
    packet_id: str,
    job: JobListing,
    profile: CandidateProfile,
    artifacts: list[DocumentArtifact],
    screening_answers: list[ScreeningAnswer],
    fit_score: float | None,
    fit_decision: str | None,
    risk_flags: list[str],
) -> str:
    artifact_rows = []
    for art in artifacts:
        path = Path(art.path)
        href = path.resolve().as_uri() if path.exists() else html.escape(art.path)
        artifact_rows.append(
            f"<tr><td>{html.escape(art.kind)}</td><td><a href='{href}'>{html.escape(art.path)}</a></td><td><code>{html.escape(art.sha256[:16])}</code></td></tr>"
        )
    qa_rows = []
    for ans in screening_answers:
        cls = " class='needs-review'" if ans.needs_review else ""
        qa_rows.append(
            f"<tr{cls}><td>{html.escape(ans.question)}</td><td>{html.escape(ans.answer)}</td><td>{html.escape(ans.source)}</td></tr>"
        )
    c = profile.contact
    risks = "".join(_li(r) for r in risk_flags) or "<li>None detected</li>"
    apply_link = f"<a href='{html.escape(job.apply_url or '#')}'>{html.escape(job.apply_url or 'No apply URL captured')}</a>"
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Application Assistant - {html.escape(job.title)} at {html.escape(job.company)}</title>
<style>
body {{ font-family: Arial, sans-serif; max-width: 1000px; margin: 32px auto; line-height: 1.45; color: #111; padding: 0 20px; }}
h1, h2 {{ border-bottom: 1px solid #ddd; padding-bottom: 6px; }}
table {{ border-collapse: collapse; width: 100%; margin: 12px 0 24px; }}
th, td {{ border: 1px solid #ddd; padding: 8px; vertical-align: top; }}
th {{ background: #f7f7f7; text-align: left; }}
.warning {{ background: #fff7cc; border: 1px solid #e5c100; padding: 12px; border-radius: 6px; }}
.needs-review {{ background: #ffecec; }}
code {{ background: #f2f2f2; padding: 2px 4px; border-radius: 3px; }}
</style>
</head>
<body>
<h1>Application Assistant</h1>
<div class="warning"><strong>Manual final submit only.</strong> This page does not submit forms, bypass logins, or bypass CAPTCHAs. Use locked answers only. If an application asks an unknown factual/legal/visa/salary question, stop and update <code>master_qa_profile.json</code> instead of guessing.</div>
<h2>Job</h2>
<table>
<tr><th>Packet ID</th><td>{html.escape(packet_id)}</td></tr>
<tr><th>Job ID</th><td>{html.escape(job.id)}</td></tr>
<tr><th>Title</th><td>{html.escape(job.title)}</td></tr>
<tr><th>Company</th><td>{html.escape(job.company)}</td></tr>
<tr><th>Location</th><td>{html.escape(job.location or '')}</td></tr>
<tr><th>Fit</th><td>{html.escape(str(fit_score if fit_score is not None else 'N/A'))} / 100, decision: {html.escape(fit_decision or 'N/A')}</td></tr>
<tr><th>Apply URL</th><td>{apply_link}</td></tr>
</table>
<h2>Candidate Contact</h2>
<table>
<tr><th>Name</th><td>{html.escape(c.name)}</td></tr>
<tr><th>Email</th><td>{html.escape(c.email)}</td></tr>
<tr><th>Phone</th><td>{html.escape(c.phone or '')}</td></tr>
<tr><th>Location</th><td>{html.escape(c.location or '')}</td></tr>
<tr><th>LinkedIn</th><td>{html.escape(c.linkedin_url or '')}</td></tr>
<tr><th>GitHub</th><td>{html.escape(c.github_url or '')}</td></tr>
</table>
<h2>Documents</h2>
<table><tr><th>Kind</th><th>Path</th><th>SHA-256 prefix</th></tr>{''.join(artifact_rows)}</table>
<h2>Prepared Screening Answers / Locked Screening Answers Bank</h2>
<p>Rows highlighted for review are not safe to copy until you add a locked answer and regenerate the packet.</p>
<table><tr><th>Question or pattern</th><th>Answer</th><th>Source</th></tr>{''.join(qa_rows) or '<tr><td colspan="3">No locked QA answers found.</td></tr>'}</table>
<h2>Risk Flags</h2>
<ul>{risks}</ul>
<h2>Manual Apply Checklist</h2>
<ol>
<li>Open the apply URL.</li>
<li>Upload the tailored CV PDF.</li>
<li>Upload the cover letter PDF if requested.</li>
<li>Copy only locked answers from this page for screening questions.</li>
<li>If a factual question is missing, do not guess; add it to <code>master_qa_profile.json</code>.</li>
<li>After submitting, run: <code>job-agent mark-submitted {html.escape(packet_id)}</code></li>
</ol>
</body>
</html>"""
