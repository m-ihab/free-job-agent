"""Referral/contact matching for warm-path outreach."""
from __future__ import annotations

from job_agent.config import AppConfig
from job_agent.db.database import Database
from job_agent.referral import (
    Contact,
    build_referral_ask,
    import_contacts,
    list_contacts,
    match_warm_paths,
)
from job_agent.schemas.job import JobListing


def _config(tmp_path) -> AppConfig:
    config = AppConfig(data_dir=tmp_path, db_path=tmp_path / "jobs.db")
    Database(config.db_path).initialize()  # type: ignore[arg-type]
    return config


def test_import_contacts_round_trips_locally(tmp_path):
    config = _config(tmp_path)
    imported = import_contacts(
        config,
        [
            Contact(name="Amina", company="DataCorp", role="Data Scientist", relationship="alumni"),
            Contact(name="No company", company="", role="Recruiter"),
        ],
    )

    contacts = list_contacts(config)

    assert imported == 2
    assert [c.name for c in contacts] == ["Amina", "No company"]
    assert contacts[0].company == "DataCorp"


def test_match_warm_paths_scores_company_and_notes(tmp_path):
    config = _config(tmp_path)
    import_contacts(
        config,
        [
            Contact(name="Amina", company="DataCorp", role="ML Engineer", relationship="alumni"),
            Contact(name="Leo", company="OtherCo", notes="Worked with DataCorp partner team"),
        ],
    )
    job = JobListing(title="Data Scientist", company="DataCorp", description="Build ML models.")

    matches = match_warm_paths(config, job)

    assert matches[0].contact.name == "Amina"
    assert matches[0].score >= matches[1].score
    assert "company match" in matches[0].reasons


def test_build_referral_ask_is_grounded_and_short(tmp_path):
    config = _config(tmp_path)
    contact = Contact(name="Amina", company="DataCorp", relationship="alumni")
    job = JobListing(title="Data Scientist", company="DataCorp", description="Python and ML role.")

    ask = build_referral_ask(config, job, contact)

    assert "Amina" in ask
    assert "Data Scientist" in ask
    assert "DataCorp" in ask
    assert "[metric]" not in ask
    assert len(ask) < 700
