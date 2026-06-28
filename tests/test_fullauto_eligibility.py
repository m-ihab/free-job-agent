from __future__ import annotations

import json

from job_agent.auto_apply.eligibility import evaluate_fullauto_eligibility
from job_agent.config import AppConfig
from job_agent.schemas.job import JobListing
from job_agent.schemas.packet import ApplicationPacket, DocumentArtifact, PacketStatus, ScreeningAnswer


def _packet(tmp_path, verdict: str = "APPLY", score: float = 88) -> ApplicationPacket:
    path = tmp_path / "preflight.json"
    path.write_text(json.dumps({"verdict": verdict}), encoding="utf-8")
    return ApplicationPacket(
        job_id="job1",
        status=PacketStatus.READY,
        fit_score=score,
        artifacts=[DocumentArtifact(kind="preflight_json", path=str(path), sha256="x")],
    )


def test_fullauto_eligibility_accepts_apply_verdict_above_threshold(tmp_path):
    job = JobListing(title="Data Intern", company="Acme", apply_url="https://apply.example")
    config = AppConfig(data_dir=tmp_path, fullauto_min_score=75)

    result = evaluate_fullauto_eligibility(job, _packet(tmp_path), config=config)

    assert result.eligible is True
    assert result.reasons == []


def test_fullauto_eligibility_fails_closed_on_unknown_screening(tmp_path):
    job = JobListing(title="Data Intern", company="Acme", apply_url="https://apply.example")
    packet = _packet(tmp_path)
    packet.screening_answers = [ScreeningAnswer(question="Do you need sponsorship?", answer="", needs_review=True)]

    result = evaluate_fullauto_eligibility(job, packet, config=AppConfig(data_dir=tmp_path))

    assert result.eligible is False
    assert "unknown_screening_answers" in result.reasons


def test_fullauto_eligibility_requires_preflight_apply_when_configured(tmp_path):
    job = JobListing(title="Data Intern", company="Acme", apply_url="https://apply.example")
    result = evaluate_fullauto_eligibility(job, _packet(tmp_path, verdict="APPLY_WITH_EDITS"), config=AppConfig(data_dir=tmp_path))

    assert result.eligible is False
    assert "preflight_apply_with_edits" in result.reasons
