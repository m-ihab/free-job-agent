"""Tests for adding several jobs in one shot."""
from __future__ import annotations

from types import SimpleNamespace

import job_agent.intake.bulk_add as bulk_add
from job_agent.intake.bulk_add import bulk_add_jobs
from job_agent.utils.net import UnsafeUrlError


def _stub_text(monkeypatch, *, created=True):
    calls = []

    def _add_text(config, text, **kwargs):
        calls.append(text)
        return SimpleNamespace(id=f"job-{len(calls)}"), created

    monkeypatch.setattr(bulk_add, "add_text_job", _add_text)
    return calls


def _stub_url(monkeypatch, *, created=True):
    calls = []

    def _add_url(config, url):
        calls.append(url)
        return SimpleNamespace(id=f"url-{len(calls)}"), created

    monkeypatch.setattr(bulk_add, "add_url_job", _add_url)
    return calls


def test_splits_text_on_dashed_separators(monkeypatch) -> None:
    calls = _stub_text(monkeypatch)
    blob = "First job posting body\n---\nSecond job posting body\n---\nThird"
    result = bulk_add_jobs(None, text=blob)
    assert len(calls) == 3
    assert result["added"] == 3
    assert result["duplicates"] == 0


def test_splits_text_on_blank_lines_when_no_separators(monkeypatch) -> None:
    calls = _stub_text(monkeypatch)
    blob = "Job one\nmore detail\n\nJob two\nmore detail"
    result = bulk_add_jobs(None, text=blob)
    assert len(calls) == 2
    assert result["added"] == 2


def test_url_lines_are_added_as_urls(monkeypatch) -> None:
    url_calls = _stub_url(monkeypatch)
    text_calls = _stub_text(monkeypatch)
    blob = "https://acme.jobs/ds\nhttps://beta.jobs/ml"
    result = bulk_add_jobs(None, text=blob)
    assert url_calls == ["https://acme.jobs/ds", "https://beta.jobs/ml"]
    assert text_calls == []
    assert result["added"] == 2


def test_explicit_urls_list(monkeypatch) -> None:
    url_calls = _stub_url(monkeypatch)
    result = bulk_add_jobs(None, urls=["https://a.co/1", "  ", "https://a.co/2"])
    assert url_calls == ["https://a.co/1", "https://a.co/2"]
    assert result["added"] == 2


def test_duplicates_are_counted_separately(monkeypatch) -> None:
    _stub_text(monkeypatch, created=False)
    result = bulk_add_jobs(None, text="One\n---\nTwo")
    assert result["added"] == 0
    assert result["duplicates"] == 2


def test_unsafe_url_is_captured_as_error(monkeypatch) -> None:
    def _boom(config, url):
        raise UnsafeUrlError("blocked private address")

    monkeypatch.setattr(bulk_add, "add_url_job", _boom)
    result = bulk_add_jobs(None, urls=["https://169.254.0.1/x"])
    assert result["added"] == 0
    assert len(result["errors"]) == 1
    assert "blocked" in result["errors"][0]


def test_empty_input_returns_zeros(monkeypatch) -> None:
    result = bulk_add_jobs(None, text="   ")
    assert result == {"added": 0, "duplicates": 0, "errors": [], "job_ids": [], "total": 0}
