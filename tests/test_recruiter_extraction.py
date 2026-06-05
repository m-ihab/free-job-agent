"""Tests for recruiter/contact extraction in the normalizer."""
from __future__ import annotations

from job_agent.normalizer import _extract_recruiter, normalize
from job_agent.schemas.job import JobListing


class TestExtractRecruiter:
    def test_extracts_email_from_description(self) -> None:
        name, email = _extract_recruiter("Send your CV to marie.dupont@acme.fr for this role.")
        assert email == "marie.dupont@acme.fr"

    def test_extracts_recruiter_name_after_contact_label(self) -> None:
        name, email = _extract_recruiter("Contact: Marie Dupont — please reach out.")
        assert name is not None
        assert "Marie" in name

    def test_extracts_hiring_manager_label(self) -> None:
        name, email = _extract_recruiter("Hiring Manager: Jean-Pierre Martin will be in touch.")
        assert name is not None
        assert "Jean" in name or "Martin" in name

    def test_extracts_french_rh_label(self) -> None:
        name, email = _extract_recruiter("Responsable RH: Sophie Legrand pour postuler.")
        assert name is not None
        assert "Sophie" in name

    def test_returns_none_when_no_contact_found(self) -> None:
        name, email = _extract_recruiter("Great role in data science at a leading company.")
        assert name is None
        assert email is None

    def test_skips_generic_noreply_email(self) -> None:
        name, email = _extract_recruiter("Apply via noreply@jobs.acme.com.")
        assert email is None

    def test_skips_generic_jobs_email(self) -> None:
        name, email = _extract_recruiter("Send to jobs@bigcorp.com or careers@bigcorp.com.")
        assert email is None

    def test_recruiter_name_and_email_together(self) -> None:
        name, email = _extract_recruiter(
            "Recruiter: Alice Morel\nContact her at alice.morel@techco.fr for questions."
        )
        assert name is not None
        assert "Alice" in name
        assert email == "alice.morel@techco.fr"

    def test_normalize_populates_recruiter_fields(self) -> None:
        job = JobListing(
            title="Data Scientist",
            company="TechCo",
            raw_text="Contact: Pierre Bernard\nSend CV to pierre.bernard@techco.fr",
        )
        result = normalize(job)
        assert result.recruiter_email == "pierre.bernard@techco.fr"

    def test_normalize_does_not_overwrite_existing_recruiter(self) -> None:
        job = JobListing(
            title="Data Analyst",
            company="Corp",
            raw_text="Contact: Paul Simon\nemail: paul@corp.fr",
            recruiter_name="Pre-set Name",
            recruiter_email="preset@corp.fr",
        )
        result = normalize(job)
        assert result.recruiter_name == "Pre-set Name"
        assert result.recruiter_email == "preset@corp.fr"
