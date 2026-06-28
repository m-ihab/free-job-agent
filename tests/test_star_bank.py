from __future__ import annotations

from job_agent.generator.star_bank import build_star_bank, render_star_bank_markdown
from job_agent.schemas.candidate import ContactInfo, MasterCV, Project, Skill, WorkExperience
from job_agent.schemas.job import JobListing


def _cv() -> MasterCV:
    return MasterCV(
        contact=ContactInfo(name="Candidate", email="c@example.com"),
        skills=[Skill(name="Python"), Skill(name="Deep Learning")],
        experience=[
            WorkExperience(
                company="Clinic",
                title="AI Research Assistant",
                start_date="2025",
                bullet_points=["Trained deep learning models for image classification", "Built reproducible Python notebooks"],
                technologies=["Python", "TensorFlow"],
            )
        ],
        projects=[
            Project(
                name="Deep Learning Project",
                description="CNN model training project",
                bullet_points=["Prepared datasets and model training loops"],
                technologies=["Python", "TensorFlow"],
            )
        ],
    )


def test_star_bank_is_grounded_and_does_not_invent_metrics():
    job = JobListing(title="Deep Learning Intern", company="Acme", description="Python TensorFlow deep learning", tech_stack=["Python", "TensorFlow"])

    stories = build_star_bank(job, _cv())
    markdown = render_star_bank_markdown(job, _cv())

    assert stories
    assert any("Deep Learning" in story.title or "AI Research" in story.title for story in stories)
    assert "50%" not in markdown
    assert "invent" not in markdown.casefold()
    assert "Python" in markdown
