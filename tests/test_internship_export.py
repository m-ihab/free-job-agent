from openpyxl import load_workbook

from job_agent.config import AppConfig
from job_agent.exporters.internship_workbook import DEFAULT_WORKBOOK_NAME, export_applied_internships
from job_agent.schemas.job import JobListing, JobStatus
from job_agent.tracker import ApplicationTracker
from job_agent.db.database import Database


def test_export_applied_internships_writes_only_internships(tmp_path):
    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()
    data_dir = tmp_path / "data"
    output_dir = tmp_path / "outputs"
    config = AppConfig(data_dir=data_dir, profiles_dir=profiles_dir, outputs_dir=output_dir)
    Database(config.db_path).initialize()
    tracker = ApplicationTracker(Database(config.db_path))

    internship = JobListing(
        title="Data Science Intern",
        company="ACME",
        description="Join our internship program in Paris.",
        location="Paris",
        apply_url="https://example.com/jobs/1",
        job_type="Internship",
    )
    tracker.add_job(internship)
    tracker.update_status(internship.id, JobStatus.APPLIED, note="submitted")

    regular_job = JobListing(
        title="Data Scientist",
        company="ACME",
        description="Full-time role.",
        location="Paris",
        apply_url="https://example.com/jobs/2",
        job_type="Permanent",
    )
    tracker.add_job(regular_job)
    tracker.update_status(regular_job.id, JobStatus.APPLIED, note="submitted")

    workbook_path, count = export_applied_internships(config)

    assert workbook_path == profiles_dir / DEFAULT_WORKBOOK_NAME
    assert count == 1
    workbook = load_workbook(workbook_path)
    worksheet = workbook.active

    headers = [worksheet.cell(row=1, column=index).value for index in range(1, 9)]
    assert headers == [
        "Company Name",
        "Job Title",
        "Link To Job",
        "Job Description",
        "Location",
        "Status",
        "Company Contact Details",
        "Date Applied",
    ]

    assert worksheet.cell(row=2, column=1).value == "ACME"
    assert worksheet.cell(row=2, column=2).value == "Data Science Intern"
    assert worksheet.cell(row=2, column=6).value == "Applied"
    assert worksheet.cell(row=2, column=8).value
    assert worksheet.cell(row=3, column=1).value is None
