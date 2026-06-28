"""CV Studio defensibility checks against the local evidence store."""
from __future__ import annotations

import shutil
from pathlib import Path

from job_agent.config import AppConfig
from job_agent.cv_studio import defensibility_report


def _profile_config(tmp_path: Path) -> AppConfig:
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    examples = Path("examples")
    for name in ["candidate_profile.json", "master_cv.json", "master_qa_profile.json"]:
        shutil.copyfile(examples / name, profiles / name)
    return AppConfig(
        data_dir=tmp_path / ".job_agent",
        db_path=tmp_path / ".job_agent" / "jobs.db",
        profiles_dir=profiles,
    )


def test_defensibility_report_flags_invented_numeric_claim(tmp_path):
    config = _profile_config(tmp_path)
    text = "\n".join([
        r"\documentclass{moderncv}",
        r"\begin{document}",
        r"\cvitem{Project}{Built supervised learning models using Python and scikit-learn.}",
        r"\cvitem{Impact}{Reduced cloud costs by 42\% with Kubernetes.}",
        r"\end{document}",
    ])

    report = defensibility_report(config, text)

    assert report["ok"] is True
    assert report["checked"] >= 2
    assert any("supervised learning models" in row["text"] for row in report["backed_lines"])
    assert any("42%" in row["text"] for row in report["unbacked_lines"])
    assert report["score"] < 100


def test_defensibility_report_uses_active_cv_when_text_not_supplied(tmp_path):
    config = _profile_config(tmp_path)
    main = Path(config.profiles_dir) / "main.tex"
    main.write_text(
        "\n".join([
            r"\documentclass{moderncv}",
            r"\begin{document}",
            r"\cvitem{Skills}{Python, SQL, Pandas and Power BI.}",
            r"\end{document}",
        ]),
        encoding="utf-8",
    )

    report = defensibility_report(config)

    assert report["ok"] is True
    assert report["origin"] == "main"
    assert report["checked"] == 1
    assert report["backed"] == 1

