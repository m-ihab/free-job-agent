from __future__ import annotations

from job_agent.followup import draft_followup
from job_agent.generator.outreach_email import generate_outreach_email
from job_agent.schemas.candidate import CandidateProfile, ContactInfo, MasterCV, Skill
from job_agent.schemas.job import JobListing


def test_outreach_and_followup_stay_grounded():
    profile = CandidateProfile(contact=ContactInfo(name="Candidate", email="c@example.com"), skills=[Skill(name="Python")])
    cv = MasterCV(contact=profile.contact, skills=[Skill(name="Python")])
    job = JobListing(title="Data Scientist Intern", company="Acme", tech_stack=["Python"])

    outreach = generate_outreach_email(job, cv, profile)
    followup = draft_followup(job)

    assert "Acme" in outreach
    assert "Data Scientist Intern" in outreach
    assert "Acme" in followup.body
    assert "certified" not in outreach.casefold()
