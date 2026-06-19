"""Behavioural tests for job_agent.profile_audit.

Asserts the recruiter audit surfaces the right findings/recommendations for
complete vs incomplete profiles and that scoring/grading is deterministic.
"""
from __future__ import annotations

import copy


from job_agent.profile_audit import (
    ProfileAuditReport,
    audit_profile,
)
from job_agent.schemas.candidate import CandidateProfile
from job_agent.schemas.job import JobListing


def _issue_categories(report: ProfileAuditReport) -> set[str]:
    return {issue.category for issue in report.issues}


def test_audit_returns_report_with_score_and_grade(sample_profile, sample_master_cv):
    # Act
    report = audit_profile(sample_profile, sample_master_cv)

    # Assert
    assert isinstance(report, ProfileAuditReport)
    assert 10 <= report.strength_score <= 100
    assert report.grade in {"A", "B", "C", "D", "F"}


def test_audit_flags_empty_work_auth_as_critical(sample_profile, sample_master_cv):
    # Arrange: a profile with no work authorization listed at all.
    data = sample_profile.dict()
    data["work_authorizations"] = []
    profile = CandidateProfile(**data)

    # Act
    report = audit_profile(profile, sample_master_cv)

    # Assert: a CRITICAL Work Authorization issue is raised.
    auth_issues = [i for i in report.issues if i.category == "Work Authorization"]
    assert auth_issues
    assert auth_issues[0].severity == "CRITICAL"


def test_audit_flags_placeholder_work_auth_as_critical(sample_profile, sample_master_cv):
    # Arrange: an authorization that still carries a "required"/placeholder marker.
    data = sample_profile.dict()
    data["work_authorizations"] = ["WORK_AUTH_REQUIRED placeholder"]
    profile = CandidateProfile(**data)

    # Act
    report = audit_profile(profile, sample_master_cv)

    # Assert
    auth_issues = [i for i in report.issues if i.category == "Work Authorization"]
    assert auth_issues
    assert auth_issues[0].severity == "CRITICAL"


def test_audit_flags_summary_placeholder_in_completeness(sample_profile, sample_master_cv):
    # The example summary contains "EDIT THIS SUMMARY".
    report = audit_profile(sample_profile, sample_master_cv)
    completeness = [i for i in report.issues if i.category == "Profile Completeness"]
    assert completeness
    assert "summary" in completeness[0].title.lower()


def test_audit_no_french_listed_raises_high_language_issue(sample_profile, sample_master_cv):
    # Arrange: a profile with no French language.
    data = sample_profile.dict()
    data["languages"] = ["English"]
    profile = CandidateProfile(**data)

    # Act
    report = audit_profile(profile, sample_master_cv)

    # Assert
    lang_issues = [i for i in report.issues if i.category == "Language"]
    assert lang_issues
    assert lang_issues[0].severity == "HIGH"
    assert "French not listed" in lang_issues[0].title


def test_audit_complete_profile_scores_higher_than_incomplete(sample_profile, sample_master_cv):
    # Arrange: a "fixed" profile with explicit auth (no trigger words) and a
    # real summary, vs a broken profile with empty auth + placeholder summary.
    fixed_data = sample_profile.dict()
    fixed_data["work_authorizations"] = [
        "EU citizen. Convention de stage available. Authorized to work in France."
    ]
    fixed_data["contact"]["work_authorization"] = fixed_data["work_authorizations"][0]
    fixed_data["summary"] = (
        "Data scientist with two years building ML pipelines in Python and SQL "
        "for analytics teams across finance and operations."
    )
    fixed_profile = CandidateProfile(**fixed_data)

    broken_data = sample_profile.dict()
    broken_data["work_authorizations"] = []
    broken_profile = CandidateProfile(**broken_data)

    # Act
    fixed_report = audit_profile(fixed_profile, sample_master_cv)
    broken_report = audit_profile(broken_profile, sample_master_cv)

    # Assert: fixing the CRITICAL auth gap raises the score and removes it.
    assert fixed_report.strength_score > broken_report.strength_score
    assert "Work Authorization" not in _issue_categories(fixed_report)


def test_audit_seniority_alignment_flags_too_many_senior_jobs(sample_profile, sample_master_cv):
    # Arrange: a tracked-jobs list that is mostly senior-level.
    senior = [
        JobListing(title="Senior Data Scientist", company="Co", seniority="senior")
        for _ in range(4)
    ]
    junior = [JobListing(title="Data Intern", company="Co", seniority="intern")]

    # Act
    report = audit_profile(sample_profile, sample_master_cv, tracked_jobs=senior + junior)

    # Assert
    seniority_issues = [i for i in report.issues if i.category == "Seniority"]
    assert seniority_issues
    assert seniority_issues[0].severity == "HIGH"


def test_audit_scoring_is_deterministic(sample_profile, sample_master_cv):
    # Act: two runs over identical inputs.
    first = audit_profile(sample_profile, sample_master_cv)
    second = audit_profile(copy.deepcopy(sample_profile), copy.deepcopy(sample_master_cv))

    # Assert
    assert first.strength_score == second.strength_score
    assert first.grade == second.grade
    assert len(first.issues) == len(second.issues)


def test_audit_reports_implied_skills_from_known_technologies(sample_profile, sample_master_cv):
    # The example profile lists scikit-learn / pandas -> implied skills exist.
    report = audit_profile(sample_profile, sample_master_cv)
    assert report.implied_skills  # non-empty
    # scikit-learn implies "Feature Engineering" per the implication map.
    assert any("Feature Engineering" == s for s in report.implied_skills)


def test_audit_lists_strengths_for_github_and_experience(sample_profile, sample_master_cv):
    report = audit_profile(sample_profile, sample_master_cv)
    joined = " ".join(report.strengths).lower()
    assert "github" in joined


def test_to_markdown_includes_score_and_issue_sections(sample_profile, sample_master_cv):
    # Arrange: empty work auth guarantees a CRITICAL issue section.
    data = sample_profile.dict()
    data["work_authorizations"] = []
    profile = CandidateProfile(**data)

    # Act
    report = audit_profile(profile, sample_master_cv)
    md = report.to_markdown()

    # Assert
    assert "# Profile Audit Report" in md
    assert f"{report.strength_score}/100" in md
    assert "## CRITICAL Issues" in md


def test_audit_focus_areas_are_priority_ordered_strings(sample_profile, sample_master_cv):
    report = audit_profile(sample_profile, sample_master_cv)
    assert report.focus_areas
    assert all(isinstance(area, str) and area for area in report.focus_areas)
