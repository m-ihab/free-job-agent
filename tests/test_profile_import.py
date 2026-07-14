"""Parse-only JSON Resume and LinkedIn export ingestion."""
from __future__ import annotations

import csv
import io
import json
import zipfile
from pathlib import Path

import pytest
from click.testing import CliRunner

from job_agent.cli.main import app
from job_agent.config import AppConfig
from job_agent.db.database import Database
from job_agent.intake.profile_import import parse_json_resume, parse_linkedin_export


@pytest.fixture
def json_resume() -> dict[str, object]:
    return {
        "basics": {"name": "Ada Example", "email": "ada@example.test"},
        "work": [{
            "name": "Analytical Engines Ltd", "position": "Data Scientist",
            "startDate": "2022-01", "endDate": "2024-03",
            "summary": "Built forecasting models.", "highlights": ["Reduced queue time."],
        }],
        "education": [{
            "institution": "Example University", "studyType": "MSc",
            "area": "Data Science", "startDate": "2020", "endDate": "2021",
            "score": "Distinction", "courses": ["Machine Learning"],
        }],
        "skills": [{"name": "Python", "level": "Advanced", "keywords": ["pandas"]}],
        "certificates": [{
            "name": "Cloud Certificate", "date": "2023-04-01",
            "issuer": "Example Institute", "url": "https://example.test/cert",
        }],
        "languages": [{"language": "English", "fluency": "Fluent"}],
    }


@pytest.fixture
def cli_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AppConfig:
    data_dir = tmp_path / "data"
    monkeypatch.setenv("JOB_AGENT_DATA_DIR", str(data_dir))
    config = AppConfig(data_dir=data_dir)
    config.ensure_dirs()
    Database(config.db_path).initialize()  # type: ignore[arg-type]
    return config


def _write_resume(path: Path, payload: dict[str, object]) -> Path:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _csv_bytes(fieldnames: list[str], row: dict[str, str]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerow(row)
    return stream.getvalue().encode("utf-8-sig")


def _write_linkedin_zip(path: Path) -> Path:
    files = {
        "Positions.csv": (
            ["Company Name", "Title", "Description", "Location", "Started On", "Finished On"],
            {"Company Name": "Example SAS", "Title": "ML Engineer", "Description": "Deployed models.",
             "Location": "Paris", "Started On": "Jan 2024", "Finished On": "Jun 2024"},
        ),
        "Education.csv": (
            ["School Name", "Start Date", "End Date", "Notes", "Degree Name", "Activities"],
            {"School Name": "Example School", "Start Date": "2022", "End Date": "2023",
             "Notes": "Thesis on NLP.", "Degree Name": "MSc AI", "Activities": "Robotics club"},
        ),
        "Skills.csv": (["Name"], {"Name": "PyTorch"}),
        "Certifications.csv": (
            ["Name", "Url", "Authority", "Started On", "Finished On", "License Number"],
            {"Name": "ML Certificate", "Url": "https://example.test/ml", "Authority": "Example Org",
             "Started On": "May 2023", "Finished On": "", "License Number": "CERT-1"},
        ),
        "Languages.csv": (["Name", "Proficiency"], {"Name": "French", "Proficiency": "Elementary"}),
    }
    with zipfile.ZipFile(path, "w") as archive:
        for filename, (headers, row) in files.items():
            archive.writestr(filename, _csv_bytes(headers, row))
    return path


def test_parse_json_resume_preserves_fields_and_provenance(tmp_path: Path, json_resume: dict[str, object]) -> None:
    path = _write_resume(tmp_path / "resume.json", json_resume)

    result = parse_json_resume(path)

    assert result.input_type == "json-resume"
    assert result.section_counts == {
        "basics": 1, "work": 1, "education": 1, "skills": 1, "certificates": 1, "languages": 1,
    }
    work = next(item for item in result.entries if item.kind == "experience")
    assert work.label == "Data Scientist"
    assert json.loads(work.value) == json_resume["work"][0]  # type: ignore[index]
    assert (work.source, work.source_ref) == ("resume.json", "work[0]")
    assert {item.kind for item in result.entries} == {
        "profile", "experience", "education", "skill", "certification", "language",
    }


def test_parse_linkedin_export_uses_real_csv_headers(tmp_path: Path) -> None:
    path = _write_linkedin_zip(tmp_path / "linkedin.zip")

    result = parse_linkedin_export(path)

    assert result.input_type == "linkedin-export"
    assert result.section_counts == {
        "work": 1, "education": 1, "skills": 1, "certifications": 1, "languages": 1,
    }
    position = next(item for item in result.entries if item.kind == "experience")
    assert position.label == "ML Engineer"
    assert json.loads(position.value)["Company Name"] == "Example SAS"
    assert (position.source, position.source_ref) == ("linkedin.zip", "Positions.csv:row[2]")
    assert not result.missing_sections


def test_missing_sections_are_tolerated_and_reported(tmp_path: Path) -> None:
    path = _write_resume(tmp_path / "partial.json", {"basics": {"name": "Ada Example"}, "skills": []})

    result = parse_json_resume(path)

    assert len(result.entries) == 1
    assert result.section_counts["skills"] == 0
    assert set(result.missing_sections) == {"work", "education", "skills", "certificates", "languages"}


def test_malformed_file_has_clear_error_and_no_partial_writes(cli_config: AppConfig, tmp_path: Path) -> None:
    db = Database(cli_config.db_path)
    db.replace_evidence_items([{
        "kind": "skill", "label": "Existing", "value": "verbatim",
        "source": "existing.json", "source_ref": "skills[0]", "confidence": 1.0,
    }])
    path = tmp_path / "broken.json"
    path.write_text('{"work": [', encoding="utf-8")

    result = CliRunner().invoke(app, ["profile-import", str(path)])

    assert result.exit_code != 0
    assert "Malformed JSON Resume" in result.output
    assert db.list_evidence_items() == [{
        "kind": "skill", "label": "Existing", "value": "verbatim",
        "source": "existing.json", "source_ref": "skills[0]", "confidence": 1.0,
    }]


def test_dry_run_previews_missing_sections_without_writing(
    cli_config: AppConfig, tmp_path: Path, json_resume: dict[str, object],
) -> None:
    json_resume.pop("languages")
    path = _write_resume(tmp_path / "resume.data", json_resume)

    result = CliRunner().invoke(app, ["profile-import", str(path), "--dry-run"])

    assert result.exit_code == 0
    assert "Dry run" in result.output
    assert "Would store: 5" in result.output
    assert "Missing sections: languages" in result.output
    assert Database(cli_config.db_path).list_evidence_items() == []


def test_reimport_is_idempotent(cli_config: AppConfig, tmp_path: Path, json_resume: dict[str, object]) -> None:
    path = _write_resume(tmp_path / "resume.json", json_resume)
    runner = CliRunner()

    first = runner.invoke(app, ["profile-import", str(path)])
    second = runner.invoke(app, ["profile-import", str(path)])

    assert first.exit_code == second.exit_code == 0
    assert "Stored 6 new evidence entries" in first.output
    assert "Stored 0 new evidence entries" in second.output
    assert len(Database(cli_config.db_path).list_evidence_items()) == 6
