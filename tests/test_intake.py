"""Tests for intake modules."""
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from job_agent.intake.file import ingest_file
from job_agent.intake.paste import ingest_paste
from job_agent.intake.rss import ingest_rss
from job_agent.intake.url import ingest_url


def test_ingest_paste_source():
    job = ingest_paste("Software Engineer at ACME\n\nWe are hiring.")
    assert job.source == "paste"
    assert "Software Engineer" in job.raw_text


def test_ingest_paste_strips_whitespace():
    job = ingest_paste("  \n  Job text  \n  ")
    assert job.raw_text == "Job text"


def test_ingest_paste_placeholders():
    job = ingest_paste("Some text")
    assert job.title == "[To Be Parsed]"
    assert job.company == "[To Be Parsed]"


def test_ingest_file(tmp_path):
    job_file = tmp_path / "job.txt"
    job_file.write_text("Senior Engineer at BigCorp\n\nJob details here.", encoding="utf-8")
    job = ingest_file(job_file)
    assert job.source == "file"
    assert "Senior Engineer" in job.raw_text
    assert job.title == "[To Be Parsed]"


def test_ingest_file_path_string(tmp_path):
    job_file = tmp_path / "job.md"
    job_file.write_text("# Engineer Role\n\nDescription.", encoding="utf-8")
    job = ingest_file(str(job_file))
    assert job.source == "file"
    assert "Engineer Role" in job.raw_text


def test_ingest_url_mock():
    mock_response = MagicMock()
    mock_response.text = "<html><body><h1>Python Dev</h1><p>Join us!</p></body></html>"
    mock_response.raise_for_status = MagicMock()

    with patch("job_agent.intake.url.requests.get", return_value=mock_response):
        job = ingest_url("https://example.com/job/123")

    assert job.source == "url"
    assert job.source_url == "https://example.com/job/123"
    assert "Python Dev" in job.raw_text


def test_ingest_url_raises_on_http_error():
    import requests as req

    mock_response = MagicMock()
    mock_response.raise_for_status.side_effect = req.HTTPError("404")

    with patch("job_agent.intake.url.requests.get", return_value=mock_response):
        with pytest.raises(req.HTTPError):
            ingest_url("https://example.com/bad-url")


def test_ingest_rss_mock():
    mock_feed = MagicMock()
    entry = MagicMock()
    entry.get = lambda k, default="": {
        "title": "Backend Engineer",
        "summary": "<p>We need a backend engineer.</p>",
        "link": "https://example.com/job/1",
    }.get(k, default)
    # Make hasattr(entry, "content") False
    del entry.content
    mock_feed.entries = [entry]

    with patch("job_agent.intake.rss.feedparser.parse", return_value=mock_feed):
        jobs = ingest_rss("https://example.com/feed.rss")

    assert len(jobs) == 1
    assert jobs[0].source == "rss"
    assert jobs[0].title == "Backend Engineer"
    assert jobs[0].source_url == "https://example.com/job/1"


def test_ingest_rss_limit():
    mock_feed = MagicMock()
    entries = []
    for i in range(5):
        e = MagicMock()
        e.get = lambda k, default="", i=i: {
            "title": f"Job {i}", "summary": f"Description {i}", "link": f"https://example.com/{i}"
        }.get(k, default)
        del e.content
        entries.append(e)
    mock_feed.entries = entries

    with patch("job_agent.intake.rss.feedparser.parse", return_value=mock_feed):
        jobs = ingest_rss("https://example.com/feed.rss", limit=2)

    assert len(jobs) == 2
