"""Job market intelligence — analyse tracked jobs to surface demand patterns.

Shows what the Paris/France DS/ML market actually wants right now,
based on all jobs you've tracked, so you can adjust your profile and targeting.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from job_agent.schemas.job import JobListing


@dataclass
class MarketReport:
    total_jobs: int
    top_skills: list[tuple[str, int]]
    contract_breakdown: dict[str, int]
    language_requirement_pct: float
    remote_pct: float
    salary_range: tuple[int | None, int | None]
    top_companies: list[tuple[str, int]]
    top_locations: list[tuple[str, int]]
    seniority_breakdown: dict[str, int]
    your_match_rate: float

    def to_markdown(self) -> str:
        lines = [
            "# Job Market Intelligence Report",
            "",
            f"**Based on {self.total_jobs} tracked jobs**",
            "",
            "## Top In-Demand Skills",
            "",
        ]
        for skill, count in self.top_skills[:15]:
            pct = round(count / max(self.total_jobs, 1) * 100)
            lines.append(f"- **{skill}** — {count} jobs ({pct}%)")
        lines.append("")

        lines += ["## Contract Type Breakdown", ""]
        for ctype, count in sorted(self.contract_breakdown.items(), key=lambda x: -x[1]):
            lines.append(f"- {ctype}: {count}")
        lines.append("")

        lines += [
            "## Key Statistics",
            "",
            f"- **French language required**: {self.language_requirement_pct:.0f}% of jobs",
            f"- **Remote-friendly**: {self.remote_pct:.0f}% of jobs",
        ]
        if self.salary_range[0] or self.salary_range[1]:
            lo = f"€{self.salary_range[0]:,}" if self.salary_range[0] else "?"
            hi = f"€{self.salary_range[1]:,}" if self.salary_range[1] else "?"
            lines.append(f"- **Salary range (when posted)**: {lo} – {hi}")
        lines.append(f"- **Your profile match rate**: {self.your_match_rate:.0f}% of jobs share ≥1 skill with your profile")
        lines.append("")

        if self.top_companies:
            lines += ["## Top Hiring Companies", ""]
            for company, count in self.top_companies[:10]:
                lines.append(f"- {company}: {count} postings")
            lines.append("")

        lines += ["## Seniority Breakdown", ""]
        for level, count in sorted(self.seniority_breakdown.items(), key=lambda x: -x[1]):
            label = level or "unspecified"
            lines.append(f"- {label.capitalize()}: {count}")
        lines.append("")

        return "\n".join(lines)


def build_market_report(
    tracked_jobs: list[JobListing],
    profile_skills: set[str] | None = None,
) -> MarketReport:
    """Analyse all tracked jobs and return a market intelligence report."""
    if not tracked_jobs:
        return MarketReport(
            total_jobs=0, top_skills=[], contract_breakdown={},
            language_requirement_pct=0, remote_pct=0, salary_range=(None, None),
            top_companies=[], top_locations=[], seniority_breakdown={},
            your_match_rate=0,
        )

    profile_skills_lower = {s.lower() for s in (profile_skills or set())}
    skill_counter: Counter[str] = Counter()
    contract_counter: Counter[str] = Counter()
    company_counter: Counter[str] = Counter()
    location_counter: Counter[str] = Counter()
    seniority_counter: Counter[str] = Counter()
    french_required_count = 0
    remote_count = 0
    salary_mins: list[int] = []
    salary_maxs: list[int] = []
    match_count = 0

    for job in tracked_jobs:
        for skill in job.tech_stack:
            skill_counter[skill] += 1

        contract = (job.job_type or "unspecified").lower()
        if any(t in contract for t in ("stage", "intern", "stagiaire")):
            contract_counter["Stage / Internship"] += 1
        elif any(t in contract for t in ("alternance", "apprentissage", "apprenticeship")):
            contract_counter["Alternance"] += 1
        elif "cdi" in contract or "permanent" in contract:
            contract_counter["CDI / Permanent"] += 1
        elif "cdd" in contract or "fixed" in contract:
            contract_counter["CDD / Fixed-term"] += 1
        else:
            contract_counter["Other / Unknown"] += 1

        if job.remote:
            remote_count += 1

        if "french" in [lang.lower() for lang in (job.languages or [])]:
            french_required_count += 1

        if job.company:
            company_counter[job.company] += 1
        if job.location:
            location_counter[job.location] += 1

        seniority_counter[job.seniority or ""] += 1

        if job.salary_min:
            salary_mins.append(job.salary_min)
        if job.salary_max:
            salary_maxs.append(job.salary_max)

        if profile_skills_lower:
            job_skills_lower = {s.lower() for s in job.tech_stack}
            if job_skills_lower & profile_skills_lower:
                match_count += 1

    n = len(tracked_jobs)
    return MarketReport(
        total_jobs=n,
        top_skills=skill_counter.most_common(20),
        contract_breakdown=dict(contract_counter),
        language_requirement_pct=french_required_count / n * 100,
        remote_pct=remote_count / n * 100,
        salary_range=(
            min(salary_mins) if salary_mins else None,
            max(salary_maxs) if salary_maxs else None,
        ),
        top_companies=company_counter.most_common(10),
        top_locations=location_counter.most_common(10),
        seniority_breakdown=dict(seniority_counter),
        your_match_rate=match_count / n * 100 if profile_skills_lower else 0,
    )
