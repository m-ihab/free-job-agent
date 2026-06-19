"""Strict recruiter profile audit — surfaces every reason a candidate gets rejected.

Acts as a harsh but fair Paris tech recruiter reviewing the profile holistically:
language gaps, auth clarity, skill gaps, seniority alignment, ATS keywords,
profile completeness, and 2025 trend alignment.

Output: a scored report with actionable fix instructions.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from job_agent.schemas.candidate import CandidateProfile, Education, MasterCV
from job_agent.schemas.job import JobListing
from job_agent.skill_extractor import extract_implied_skills, mine_job_keywords, suggest_trend_gaps


@dataclass
class AuditIssue:
    severity: str  # CRITICAL / HIGH / MEDIUM / LOW
    category: str
    title: str
    detail: str
    fix: str


@dataclass
class ProfileAuditReport:
    strength_score: int
    grade: str
    issues: list[AuditIssue] = field(default_factory=list)
    implied_skills: list[str] = field(default_factory=list)
    keyword_gaps: list[str] = field(default_factory=list)
    trend_gaps: list[str] = field(default_factory=list)
    strengths: list[str] = field(default_factory=list)
    focus_areas: list[str] = field(default_factory=list)

    def to_markdown(self) -> str:
        lines: list[str] = [
            "# Profile Audit Report",
            "",
            f"**Strength Score**: {self.strength_score}/100  |  **Grade**: {self.grade}",
            "",
        ]
        if self.strengths:
            lines += ["## Strengths", ""]
            for s in self.strengths:
                lines.append(f"- {s}")
            lines.append("")

        by_sev: dict[str, list[AuditIssue]] = {}
        for issue in self.issues:
            by_sev.setdefault(issue.severity, []).append(issue)

        for sev in ["CRITICAL", "HIGH", "MEDIUM", "LOW"]:
            if sev not in by_sev:
                continue
            lines += [f"## {sev} Issues", ""]
            for issue in by_sev[sev]:
                lines += [
                    f"### {issue.title}",
                    f"**Category**: {issue.category}",
                    "",
                    issue.detail,
                    "",
                    f"**Fix**: {issue.fix}",
                    "",
                ]

        if self.implied_skills:
            lines += ["## Implied Skills to Add", ""]
            lines.append("These skills are directly implied by your listed experience but absent from your profile:")
            for s in self.implied_skills[:15]:
                lines.append(f"- {s}")
            lines.append("")

        if self.keyword_gaps:
            lines += ["## ATS Keyword Gaps", ""]
            lines.append("High-frequency terms in your tracked jobs not in your profile:")
            for k in self.keyword_gaps[:10]:
                lines.append(f"- {k}")
            lines.append("")

        if self.trend_gaps:
            lines += ["## 2025 Trend Skill Gaps", ""]
            for t in self.trend_gaps[:10]:
                lines.append(f"- {t}")
            lines.append("")

        if self.focus_areas:
            lines += ["## Focus Areas (Priority Order)", ""]
            for i, area in enumerate(self.focus_areas, 1):
                lines.append(f"{i}. {area}")
            lines.append("")

        return "\n".join(lines)


def _check_language(profile: CandidateProfile) -> list[AuditIssue]:
    issues: list[AuditIssue] = []
    langs_lower = [lang.lower() for lang in (profile.languages or [])]
    has_french = any("french" in lang or "français" in lang for lang in langs_lower)
    levels = getattr(profile, "language_levels", {}) or {}
    french_level = (levels.get("French") or levels.get("french") or "").upper()

    if not has_french:
        issues.append(AuditIssue(
            severity="HIGH",
            category="Language",
            title="French not listed",
            detail="French-language job postings will trigger FRENCH_REQUIRED penalties, capping your score at 25/100.",
            fix="Add French to your languages. Even A2 is better than absent — be honest about level.",
        ))
    elif french_level in ("A1", "A2") or "a2" in " ".join(langs_lower) or "a1" in " ".join(langs_lower):
        issues.append(AuditIssue(
            severity="HIGH",
            category="Language",
            title="French level A2 — will fail most Paris job requirements",
            detail=(
                "85%+ of Paris employers posting in French require B1 minimum, most prefer B2-C1. "
                "With A2, you will be auto-filtered by ATS and mentally filtered by recruiters. "
                "This is your #1 barrier to callbacks from French companies."
            ),
            fix=(
                "Strategy A (immediate): Target English-first international companies in Paris "
                "(BNP tech, Capgemini, Thales, Airbus, startups). "
                "Strategy B (medium-term): Reach B1 within 6 months (Duolingo + italki + immersion). "
                "Strategy C: Explicitly state your level and target bilingual or English-ok roles."
            ),
        ))
    return issues


def _check_work_auth(profile: CandidateProfile) -> list[AuditIssue]:
    issues: list[AuditIssue] = []
    auths = profile.work_authorizations or []
    vague = any(
        ("manual" in a.lower() or "required" in a.lower() or "placeholder" in a.lower())
        for a in auths
    )
    if not auths or vague:
        issues.append(AuditIssue(
            severity="CRITICAL",
            category="Work Authorization",
            title="Work authorization unclear or placeholder",
            detail=(
                "Recruiters see ambiguous authorization as a hard stop. They skip ambiguous profiles. "
                "For a student in France seeking a stage, the answer needs to be explicit about: "
                "(1) visa type, (2) convention de stage availability, (3) hours limit."
            ),
            fix=(
                "Replace with: 'Student visa holder. Convention de stage available from [school name]. "
                "Authorized to work up to 964h/year. No employer visa sponsorship required for stage.'"
            ),
        ))
    return issues


def _check_skills(profile: CandidateProfile, tracked_jobs: list[JobListing]) -> list[AuditIssue]:
    issues: list[AuditIssue] = []
    existing = {s.lower() for s in profile.all_skill_names()}

    # Check for high-value 2025 skills that most DS/ML job postings include
    priority_missing = [
        s for s in ["hugging face", "mlops", "feature engineering", "rest api", "docker", "ci/cd"]
        if s not in existing
    ]
    if priority_missing:
        issues.append(AuditIssue(
            severity="MEDIUM",
            category="Skills",
            title=f"High-demand skills absent: {', '.join(priority_missing[:4])}",
            detail="These appear in 40-70% of Paris DS/ML job postings and are likely in your experience.",
            fix="Add them from experience: Docker from containerization, REST API from Flask/Django, etc.",
        ))

    # Check tech stack breadth
    categories_present = {s.get("category") if isinstance(s, dict) else getattr(s, "category", "") for s in (profile.skills or [])}
    if "tools" not in categories_present or len(profile.skills or []) < 15:
        issues.append(AuditIssue(
            severity="LOW",
            category="Skills",
            title="Skills list may appear thin",
            detail="Profiles with fewer than 15 explicitly listed skills often lose ATS scoring.",
            fix="Run 'job-agent suggest-skills' to find and add implied skills automatically.",
        ))
    return issues


def _check_experience_metrics(master_cv: MasterCV) -> list[AuditIssue]:
    issues: list[AuditIssue] = []
    metric_re = re.compile(r"\d+\s*%|\d+\s*x\b|\d+\s*(records?|users?|jobs?|hours?|minutes?|rows?|GB|TB|ms)", re.IGNORECASE)
    no_metrics_count = 0
    for exp in (master_cv.experience or []):
        bullets = exp.get("bullet_points", []) if isinstance(exp, dict) else getattr(exp, "bullet_points", [])
        for bullet in bullets:
            if not metric_re.search(bullet):
                no_metrics_count += 1
    if no_metrics_count > 3:
        issues.append(AuditIssue(
            severity="MEDIUM",
            category="CV Quality",
            title=f"{no_metrics_count} bullet points lack quantifiable metrics",
            detail=(
                "Recruiters spend 6–10 seconds on a CV. Bullets without numbers blend in. "
                "'Built X using Y' is forgettable. 'Automated 15 workflows, reducing manual time by 40%' is not."
            ),
            fix=(
                "Add numbers to at least 3 bullets: processing time saved, accuracy achieved, "
                "records processed, hours automated, files handled, etc. Estimate conservatively if exact figures unavailable."
            ),
        ))
    return issues


def _check_seniority_alignment(profile: CandidateProfile, tracked_jobs: list[JobListing]) -> list[AuditIssue]:
    issues: list[AuditIssue] = []
    senior_jobs = [j for j in tracked_jobs if j.seniority in ("senior", "lead", "principal")]
    if len(senior_jobs) > len(tracked_jobs) * 0.2:
        issues.append(AuditIssue(
            severity="HIGH",
            category="Seniority",
            title=f"{len(senior_jobs)} tracked jobs are senior-level",
            detail="Applying to senior roles as a master's student will result in near-zero callbacks.",
            fix="Filter tracked jobs to intern/junior/stage/alternance. Use --min-relevance 50 to auto-clean.",
        ))
    return issues


def _check_profile_completeness(profile: CandidateProfile, master_cv: MasterCV) -> list[AuditIssue]:
    issues: list[AuditIssue] = []
    contact = profile.contact
    missing: list[str] = []
    if not (contact and contact.linkedin_url):
        missing.append("linkedin_url")
    if not (contact and contact.github_url):
        missing.append("github_url")
    if not profile.summary or "EDIT" in profile.summary:
        missing.append("summary (still contains placeholder)")
    if not master_cv.experience:
        missing.append("experience entries in master_cv.json")
    if not master_cv.education:
        missing.append("education entries in master_cv.json")
    if missing:
        issues.append(AuditIssue(
            severity="HIGH" if len(missing) > 2 else "MEDIUM",
            category="Profile Completeness",
            title=f"Missing profile fields: {', '.join(missing)}",
            detail="Incomplete profiles are deprioritized by ATS systems and look unprepared to recruiters.",
            fix=f"Fill in: {', '.join(missing)}. Run 'job-agent validate-profile' to check all fields.",
        ))
    return issues


def audit_profile(
    profile: CandidateProfile,
    master_cv: MasterCV,
    tracked_jobs: list[JobListing] | None = None,
) -> ProfileAuditReport:
    """Run a full strict-recruiter audit and return a scored report."""
    tracked_jobs = tracked_jobs or []
    issues: list[AuditIssue] = []
    issues.extend(_check_language(profile))
    issues.extend(_check_work_auth(profile))
    issues.extend(_check_skills(profile, tracked_jobs))
    issues.extend(_check_experience_metrics(master_cv))
    if tracked_jobs:
        issues.extend(_check_seniority_alignment(profile, tracked_jobs))
    issues.extend(_check_profile_completeness(profile, master_cv))

    # Scoring: start at 100, deduct per issue
    score = 100
    deductions = {"CRITICAL": 20, "HIGH": 12, "MEDIUM": 6, "LOW": 2}
    for issue in issues:
        score -= deductions.get(issue.severity, 0)
    score = max(10, min(100, score))
    grade = "A" if score >= 85 else "B" if score >= 70 else "C" if score >= 55 else "D" if score >= 40 else "F"

    # Implied skills
    implied = extract_implied_skills(profile, master_cv)
    implied_names = [i.name for i in implied]

    # Keyword gaps from tracked jobs
    gaps = mine_job_keywords(tracked_jobs, profile, top_n=15) if tracked_jobs else []
    gap_names = [g.skill for g in gaps]

    # Trend gaps
    trends = suggest_trend_gaps(profile)

    # Strengths
    strengths: list[str] = []
    if len(profile.skills or []) >= 20:
        strengths.append("Strong skills breadth — 20+ skills listed")
    if master_cv.education:
        edu: Education | dict = master_cv.education[0] if master_cv.education else {}
        school = edu.get("institution", "") if isinstance(edu, dict) else getattr(edu, "institution", "")
        if "dsti" in school.lower() or "engineering" in school.lower():
            strengths.append("MSc at DSTI Paris — well-regarded for DS/AI in France")
    if any(s.lower() in {sk.lower() for sk in profile.all_skill_names()} for s in ["transformers", "bert", "deep learning", "hugging face"]):
        strengths.append("Transformer/NLP experience — highly valued in 2025 DS market")
    if master_cv.projects and len(master_cv.projects) >= 3:
        strengths.append(f"{len(master_cv.projects)} GitHub projects — demonstrates initiative")
    contact = profile.contact
    if contact and contact.github_url:
        strengths.append("GitHub profile present — recruiters can verify skills")
    if "survival analysis" in {s.lower() for s in profile.all_skill_names()}:
        strengths.append("Survival analysis (rare, high-value for pharma/biotech)")
    if master_cv.experience and len(master_cv.experience) >= 2:
        strengths.append("Real work experience (not just academic projects)")
    if "sap btp" in {s.lower() for s in profile.all_skill_names()}:
        strengths.append("SAP BTP (rare enterprise skill, differentiates from pure academics)")

    # Focus areas
    focus_areas = [
        "Improve French to B1+ — unlocks 3× more Paris opportunities",
        "Clarify work authorization with explicit text",
        "Add metrics to 3+ CV bullet points",
        "Add Hugging Face, MLOps, and REST API to skills list",
        "Target English-first international companies until French improves",
        "Use 'suggest-skills' to find and add all implied skills",
    ]

    return ProfileAuditReport(
        strength_score=score,
        grade=grade,
        issues=issues,
        implied_skills=implied_names,
        keyword_gaps=gap_names,
        trend_gaps=trends,
        strengths=strengths,
        focus_areas=focus_areas,
    )
