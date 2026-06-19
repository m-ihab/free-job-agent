"""Proactive headhunter mode — batch outreach, cadence tracking, English-first targeting.

Treats the candidate as the product. Generates a ready-to-send outreach pack for
every high-scoring saved job and identifies English-first Paris employers where
A2 French is not a barrier.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from job_agent.generator.linkedin_message import (
    generate_linkedin_connect_request,
    generate_linkedin_recruiter_message,
    generate_linkedin_followup_message,
)
from job_agent.generator.outreach_email import generate_outreach_email
from job_agent.schemas.candidate import CandidateProfile, MasterCV
from job_agent.schemas.job import JobListing

log = logging.getLogger(__name__)

# Companies strongly associated with English-first culture in Paris/France.
# Used to tag jobs where A2 French is unlikely to be a hard gate.
_ENGLISH_FIRST_SIGNALS = [
    # US tech in Paris
    "google", "meta", "microsoft", "amazon", "apple", "spotify", "stripe",
    "datadog", "salesforce", "oracle", "sap", "cisco", "intel", "nvidia",
    # Paris-based scale-ups with English culture
    "alan", "qonto", "payfit", "contentsquare", "mirakl", "vestiaire collective",
    "blablacar", "back market", "doctolib", "ledger", "shift technology",
    "hugging face", "mistral", "helsing", "nabla", "owkin", "inato",
    "voodoo", "malt", "spendesk", "pennylane", "teads", "accor tech",
    # Consulting / data firms with EN culture
    "mckinsey", "bcg", "bain", "accenture", "capgemini invent", "ekimetrics",
    "artefact", "quantmetry", "eleven strategy", "sia partners",
    # CAC40 international divisions
    "lvmh tech", "airbus ai", "total energies", "renault software",
    "société générale cib", "bnp paribas global markets",
]

_CADENCE_STEPS = [
    {"day": 0, "action": "apply", "label": "Submit application"},
    {"day": 7, "action": "followup_week1", "label": "Week-1 follow-up email"},
    {"day": 14, "action": "followup_week2", "label": "Week-2 follow-up email"},
    {"day": 21, "action": "close", "label": "Mark closed or keep warm"},
]


@dataclass
class OutreachPack:
    job_id: str
    job_title: str
    company: str
    score: int
    is_english_first: bool
    connect_request: str
    recruiter_message: str
    followup_message: str
    outreach_email: str
    cadence: list[dict] = field(default_factory=lambda: list(_CADENCE_STEPS))

    def to_markdown(self) -> str:
        lines = [
            f"# Outreach Pack — {self.job_title} @ {self.company}",
            "",
            f"**Job ID**: `{self.job_id}`  |  **Score**: {self.score}/100  |  "
            f"**English-first**: {'✓ Yes' if self.is_english_first else '—'}",
            "",
            "---",
            "",
            "## LinkedIn Connection Request",
            "*(250 char limit — copy & paste into LinkedIn)*",
            "",
            "```",
            self.connect_request,
            "```",
            "",
            "## LinkedIn Recruiter Message",
            "*(Send after connecting, or via InMail)*",
            "",
            self.recruiter_message,
            "",
            "## Follow-Up LinkedIn Message",
            "*(Send ~7 days after applying if no response)*",
            "",
            self.followup_message,
            "",
            "## Cold Outreach Email",
            "",
            self.outreach_email,
            "",
            "---",
            "",
            "## Application Cadence",
            "",
        ]
        for step in self.cadence:
            lines.append(f"- Day {step['day']:>2}: {step['label']}")
        lines.append("")
        return "\n".join(lines)


def is_english_first(company: str) -> bool:
    c = company.lower()
    return any(signal in c for signal in _ENGLISH_FIRST_SIGNALS)


def build_outreach_pack(
    job: JobListing,
    master_cv: MasterCV,
    profile: CandidateProfile,
) -> OutreachPack:
    connect = generate_linkedin_connect_request(job, master_cv, profile)
    recruiter = generate_linkedin_recruiter_message(job, master_cv, profile)
    followup = generate_linkedin_followup_message(job, master_cv, profile)
    email = generate_outreach_email(job, master_cv, profile)
    english_first = is_english_first(job.company or "")

    return OutreachPack(
        job_id=job.id,
        job_title=job.title or "Unknown role",
        company=job.company or "Unknown company",
        score=job.fit_score or 0,
        is_english_first=english_first,
        connect_request=connect,
        recruiter_message=recruiter,
        followup_message=followup,
        outreach_email=email,
    )


def build_batch_outreach(
    jobs: list[JobListing],
    master_cv: MasterCV,
    profile: CandidateProfile,
    min_score: int = 65,
    english_first_only: bool = False,
) -> list[OutreachPack]:
    """Build outreach packs for all jobs above min_score.

    When english_first_only is True, only include companies tagged as
    English-first culture — useful when French level is below B2.
    """
    eligible = [j for j in jobs if (j.fit_score or 0) >= min_score]
    if english_first_only:
        eligible = [j for j in eligible if is_english_first(j.company or "")]

    eligible.sort(key=lambda j: j.fit_score or 0, reverse=True)

    packs: list[OutreachPack] = []
    for job in eligible:
        try:
            packs.append(build_outreach_pack(job, master_cv, profile))
        except Exception as exc:
            log.warning("Skipped outreach pack for %s: %s", job.id, exc)
    return packs


def write_batch_outreach_file(
    packs: list[OutreachPack],
    output_path: Path,
) -> int:
    if not packs:
        return 0
    sections = [p.to_markdown() for p in packs]
    header = (
        f"# Batch Outreach Pack — {len(packs)} Jobs\n\n"
        "Generated by free-job-agent headhunter mode.\n"
        "Review each message before sending. Never auto-send.\n\n"
        "---\n\n"
    )
    output_path.write_text(header + "\n\n---\n\n".join(sections), encoding="utf-8")
    return len(packs)


def english_first_strategy_report(jobs: list[JobListing]) -> str:
    """Summarise which tracked jobs are at English-first companies."""
    tagged = [j for j in jobs if is_english_first(j.company or "")]
    untagged = [j for j in jobs if not is_english_first(j.company or "")]

    lines = [
        "# English-First Company Strategy",
        "",
        "Your French is A2. Focus on companies with English-first cultures first.",
        "",
        f"**English-first companies in your tracker**: {len(tagged)}",
        f"**Other companies**: {len(untagged)}",
        "",
    ]

    if tagged:
        lines += ["## English-First Targets (prioritise these)", ""]
        for job in sorted(tagged, key=lambda j: j.fit_score or 0, reverse=True)[:20]:
            score_str = f"{job.fit_score}/100" if job.fit_score else "unscored"
            lines.append(f"- **{job.company}** — {job.title} ({score_str})")
        lines.append("")

    lines += [
        "## Recommended Approach",
        "",
        "1. Apply to all English-first companies with score ≥ 65 first.",
        "2. For French-language companies: only apply if the job does not explicitly require French B2+.",
        "3. Mention in your cover letter: 'Fluent in English, French A2 (actively improving).'",
        "4. Target fintech, deeptech, and US-headquartered companies in Paris — they typically interview in English.",
        "",
    ]
    return "\n".join(lines)
