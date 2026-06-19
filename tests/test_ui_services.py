from job_agent.schemas.job import JobListing, JobStatus
from job_agent.ui.services import (
    APP_DESCRIPTION,
    APP_NAME,
    build_manual_search_groups,
    job_to_dict,
    status_options,
)


def _job(**overrides) -> JobListing:
    base = dict(title="Data Scientist", company="ACME", source="paste")
    base.update(overrides)
    return JobListing(**base)


def test_ui_manual_search_groups_are_curated_by_default():
    groups = build_manual_search_groups("data scientist", "Paris", language="english", limit=2, boards="recommended")
    assert len(groups) == 2
    boards = {link["board_key"] for group in groups for link in group["links"]}
    assert "welcome-to-the-jungle" in boards
    assert "france-travail-web" in boards
    assert "glassdoor-fr" not in boards
    assert "indeed-fr" not in boards


def test_ui_api_application_text_is_portfolio_friendly():
    assert "Career Copilot" in APP_NAME
    assert "data science" in APP_DESCRIPTION.lower()
    assert "manual review" in APP_DESCRIPTION.lower()


def test_status_options_lists_every_job_status():
    options = status_options()
    assert options == [s.value for s in JobStatus]


def test_job_to_dict_maps_core_fields_and_short_id():
    job = _job(fit_score=82, tech_stack=["python", "sql"])

    data = job_to_dict(job)

    assert data["id"] == job.id
    assert data["short_id"] == job.id[:8]
    assert data["company_display"] == "ACME"  # usable company left untouched
    assert data["company_unresolved"] is False
    assert data["fit_score"] == 82
    assert data["tech_stack"] == ["python", "sql"]


def test_job_to_dict_flags_undisclosed_employer_for_aggregator_company():
    # "France Travail" is an aggregator; with no real employer in the text the
    # UI must surface that the employer is not disclosed rather than show it.
    job = _job(company="France Travail", description="", raw_text="")

    data = job_to_dict(job)

    assert data["company_display"] == "Employer not disclosed"
    assert data["company_unresolved"] is True
    assert data["company_source"] == "France Travail"


def test_job_to_dict_uses_source_url_when_apply_url_missing():
    job = _job(apply_url=None, source_url="https://board/job/1")

    assert job_to_dict(job)["apply_url"] == "https://board/job/1"

