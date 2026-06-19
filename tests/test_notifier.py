"""Behavioural tests for the local packet-ready notifier.

Exercises the email-style local outbox write plus the SMTP dispatch and
fallback branches. The SMTP backend is fully mocked — no real mail is sent.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from job_agent import notifier
from job_agent.config import AppConfig
from job_agent.schemas.job import JobListing
from job_agent.schemas.packet import ApplicationPacket, PacketStatus


@pytest.fixture
def config(tmp_path: Path) -> AppConfig:
    cfg = AppConfig(data_dir=tmp_path / "data", profiles_dir=tmp_path / "profiles",
                    outputs_dir=tmp_path / "outputs")
    cfg.ensure_dirs()
    return cfg


def _job() -> JobListing:
    return JobListing(title="ML Engineer", company="Acme", location="Paris", source="paste",
                      raw_text="x", apply_url="https://example.com/apply", fit_score=88.0)


def _packet(job_id: str) -> ApplicationPacket:
    return ApplicationPacket(id="pkt_n", job_id=job_id, status=PacketStatus.READY,
                            fit_score=88.0, tailored_cv_pdf_path="cv.pdf",
                            cover_letter_pdf_path="cl.pdf")


# ── status reporting ─────────────────────────────────────────────────────────

def test_status_disabled_by_default(monkeypatch):
    for var in ("JOB_AGENT_NOTIFY_EMAIL", "JOB_AGENT_SMTP_HOST", "JOB_AGENT_NOTIFY_TO"):
        monkeypatch.delenv(var, raising=False)
    status = notifier.email_notifier_status()
    assert status["enabled"] is False
    assert status["smtp_configured"] is False
    assert status["local_outbox"] is True


def test_status_enabled_and_configured(monkeypatch):
    monkeypatch.setenv("JOB_AGENT_NOTIFY_EMAIL", "true")
    monkeypatch.setenv("JOB_AGENT_SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("JOB_AGENT_NOTIFY_TO", "me@example.com")
    status = notifier.email_notifier_status()
    assert status["enabled"] is True
    assert status["smtp_configured"] is True


# ── local outbox write (no SMTP) ─────────────────────────────────────────────

def test_notify_writes_local_outbox_when_smtp_disabled(config, monkeypatch):
    monkeypatch.delenv("JOB_AGENT_NOTIFY_EMAIL", raising=False)
    job = _job()
    result = notifier.notify_packet_ready(config, job, _packet(job.id))
    assert result["sent"] is False
    assert result["error"] == ""
    outbox_path = Path(result["outbox_path"])
    assert outbox_path.exists()
    body = outbox_path.read_text(encoding="utf-8")
    assert "ML Engineer" in body
    assert "Acme" in body
    assert "Nothing was submitted automatically" in body


# ── SMTP dispatch success ────────────────────────────────────────────────────

class _FakeSMTP:
    instances: list["_FakeSMTP"] = []

    def __init__(self, host, port, timeout=20):
        self.host = host
        self.port = port
        self.started_tls = False
        self.logged_in = None
        self.sent = False
        _FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self):
        self.started_tls = True

    def login(self, user, pwd):
        self.logged_in = (user, pwd)

    def send_message(self, msg):
        self.sent = True


def test_notify_sends_via_smtp_when_configured(config, monkeypatch):
    _FakeSMTP.instances.clear()
    monkeypatch.setenv("JOB_AGENT_NOTIFY_EMAIL", "true")
    monkeypatch.setenv("JOB_AGENT_SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("JOB_AGENT_NOTIFY_TO", "me@example.com")
    monkeypatch.setenv("JOB_AGENT_SMTP_USERNAME", "user")
    monkeypatch.setenv("JOB_AGENT_SMTP_PASSWORD", "pass")
    monkeypatch.setattr(notifier.smtplib, "SMTP", _FakeSMTP)

    job = _job()
    result = notifier.notify_packet_ready(config, job, _packet(job.id))
    assert result["sent"] is True
    assert result["error"] == ""
    smtp = _FakeSMTP.instances[-1]
    assert smtp.started_tls is True
    assert smtp.logged_in == ("user", "pass")
    assert smtp.sent is True


def test_notify_smtp_failure_is_captured(config, monkeypatch):
    monkeypatch.setenv("JOB_AGENT_NOTIFY_EMAIL", "true")
    monkeypatch.setenv("JOB_AGENT_SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("JOB_AGENT_NOTIFY_TO", "me@example.com")

    def _broken_smtp(*a, **k):
        raise OSError("connection refused")

    monkeypatch.setattr(notifier.smtplib, "SMTP", _broken_smtp)
    job = _job()
    result = notifier.notify_packet_ready(config, job, _packet(job.id))
    assert result["sent"] is False
    assert "connection refused" in result["error"]
    # The local outbox is still written even when SMTP fails.
    assert Path(result["outbox_path"]).exists()


def test_notify_uses_job_score_when_packet_score_missing(config, monkeypatch):
    monkeypatch.delenv("JOB_AGENT_NOTIFY_EMAIL", raising=False)
    job = _job()
    packet = ApplicationPacket(id="pkt_noscore", job_id=job.id, status=PacketStatus.READY,
                               fit_score=None)
    result = notifier.notify_packet_ready(config, job, packet)
    body = Path(result["outbox_path"]).read_text(encoding="utf-8")
    # job.fit_score (88.0) is used when packet.fit_score is None.
    assert "88.0" in body
