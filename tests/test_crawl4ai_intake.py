"""Tests for the crawl4AI careers-page intake (deterministic core, mocked I/O)."""
from __future__ import annotations

import pytest

import job_agent.intake.crawl4ai_intake as c4a
from job_agent.schemas.job import JobStatus


MARKDOWN = """
# Careers at ExampleAI

[About us](/about) [Privacy Policy](/privacy)

## Open roles

- [Data Scientist - NLP](/jobs/data-scientist-nlp)
- [**Machine Learning Engineer**](https://exampleai.fr/jobs/mle)
- [Stage - Data Analyst (H/F)](/jobs/stage-data)
- [Data Scientist - NLP](/jobs/data-scientist-nlp)
- [Office Manager](/jobs/office-manager)
- [See all openings](/jobs)
- [Follow us on LinkedIn](https://linkedin.com/company/exampleai)
"""


def test_looks_like_job_title_accepts_data_roles():
    assert c4a.looks_like_job_title("Data Scientist - NLP")
    assert c4a.looks_like_job_title("Stage - Data Analyst (H/F)")
    assert c4a.looks_like_job_title("Ingénieur Machine Learning")


def test_looks_like_job_title_rejects_nav_and_unrelated():
    assert not c4a.looks_like_job_title("Privacy Policy")
    assert not c4a.looks_like_job_title("Office Manager")
    assert not c4a.looks_like_job_title("")
    assert not c4a.looks_like_job_title("Follow us on LinkedIn")


def test_extract_job_links_resolves_dedupes_and_filters():
    links = c4a.extract_job_links(MARKDOWN, "https://exampleai.fr/careers")
    urls = [u for _, u in links]
    titles = [t for t, _ in links]
    assert "https://exampleai.fr/jobs/data-scientist-nlp" in urls  # relative resolved
    assert "https://exampleai.fr/jobs/mle" in urls
    assert urls.count("https://exampleai.fr/jobs/data-scientist-nlp") == 1  # deduped
    assert "Machine Learning Engineer" in titles  # ** stripped
    assert all("linkedin" not in u for u in urls)
    assert all("privacy" not in u for u in urls)


def test_listings_have_discovered_status_and_source():
    links = [("Data Scientist", "https://exampleai.fr/jobs/ds")]
    listings = c4a.listings_from_links(links, company="ExampleAI", source_url="https://exampleai.fr/careers")
    job = listings[0]
    assert job.status == JobStatus.DISCOVERED
    assert job.source == "crawl4ai"
    assert job.company == "ExampleAI"
    assert job.apply_url == "https://exampleai.fr/jobs/ds"
    assert job.source_url == "https://exampleai.fr/careers"


def test_fetch_page_markdown_none_when_lib_missing(monkeypatch):
    monkeypatch.setattr(c4a, "_load_crawl4ai", lambda: None)
    assert c4a.fetch_page_markdown("https://exampleai.fr/careers") is None


def test_crawl_careers_page_happy_path(monkeypatch):
    monkeypatch.setattr(c4a, "robots_allows", lambda url, **kw: True)
    monkeypatch.setattr(c4a, "fetch_page_markdown", lambda url, timeout=40: MARKDOWN)
    listings = c4a.crawl_careers_page("https://exampleai.fr/careers")
    assert len(listings) == 3
    assert listings[0].company == "Exampleai"  # derived from netloc
    assert all(job.status == JobStatus.DISCOVERED for job in listings)


def test_crawl_careers_page_respects_robots(monkeypatch):
    monkeypatch.setattr(c4a, "robots_allows", lambda url, **kw: False)
    monkeypatch.setattr(
        c4a, "fetch_page_markdown",
        lambda url, timeout=40: pytest.fail("must not fetch when robots disallows"),
    )
    assert c4a.crawl_careers_page("https://exampleai.fr/careers") == []


def test_crawl_careers_page_empty_on_fetch_failure(monkeypatch):
    monkeypatch.setattr(c4a, "robots_allows", lambda url, **kw: True)
    monkeypatch.setattr(c4a, "fetch_page_markdown", lambda url, timeout=40: None)
    assert c4a.crawl_careers_page("https://exampleai.fr/careers") == []


def test_crawl_careers_page_caps_max_jobs(monkeypatch):
    many = "\n".join(f"- [Data Engineer {i}](/jobs/{i})" for i in range(60))
    monkeypatch.setattr(c4a, "robots_allows", lambda url, **kw: True)
    monkeypatch.setattr(c4a, "fetch_page_markdown", lambda url, timeout=40: many)
    listings = c4a.crawl_careers_page("https://exampleai.fr/careers", max_jobs=10)
    assert len(listings) == 10


def test_robots_allows_fail_open_on_error(monkeypatch):
    import job_agent.utils.net as net

    def _boom(*a, **k):
        raise RuntimeError("network down")

    monkeypatch.setattr(net, "safe_get", _boom)
    assert c4a.robots_allows("https://exampleai.fr/careers") is True


def test_robots_allows_fail_closed_on_disallow(monkeypatch):
    import job_agent.utils.net as net

    class _Resp:
        status_code = 200
        text = "User-agent: *\nDisallow: /careers"

    monkeypatch.setattr(net, "safe_get", lambda *a, **k: _Resp())
    assert c4a.robots_allows("https://exampleai.fr/careers") is False
