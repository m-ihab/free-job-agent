from __future__ import annotations

import base64

import pytest

from job_agent.config import AppConfig
from job_agent.cv_template import import_cv_template_upload


def test_import_tex_template_backs_up_existing_main(tmp_path):
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    (profiles / "main.tex").write_text("old", encoding="utf-8")
    config = AppConfig(data_dir=tmp_path / "data", profiles_dir=profiles)
    payload = base64.b64encode(b"new tex").decode("ascii")

    result = import_cv_template_upload(config, filename="resume.tex", content_base64=payload)

    assert (profiles / "main.tex").read_text(encoding="utf-8") == "new tex"
    assert result["backups"]


def test_import_pdf_goes_to_cv_pdf(tmp_path):
    profiles = tmp_path / "profiles"
    config = AppConfig(data_dir=tmp_path / "data", profiles_dir=profiles)
    payload = base64.b64encode(b"%PDF fake").decode("ascii")

    result = import_cv_template_upload(config, filename="cv.pdf", content_base64=payload)

    assert result["target"].endswith("CV.pdf")
    assert (profiles / "CV.pdf").read_bytes() == b"%PDF fake"


def test_import_rejects_unsupported_type(tmp_path):
    config = AppConfig(data_dir=tmp_path / "data", profiles_dir=tmp_path / "profiles")
    payload = base64.b64encode(b"hello").decode("ascii")

    with pytest.raises(ValueError):
        import_cv_template_upload(config, filename="secret.exe", content_base64=payload)
