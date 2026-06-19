"""Behavioural tests for the free/public job-source API connectors.

Each provider under ``job_agent.intake.sources`` parses a JSON (or XML) API
response into normalized ``JobListing`` objects. These tests monkeypatch the
shared ``job_agent.intake.sources.base.requests`` object so no real network is
performed, then assert that each provider:

* maps the API's title/company/location/url fields onto ``JobListing`` fields,
* survives empty payloads (returns ``[]``), and
* survives malformed/non-list payloads without raising.

Test data uses tech-relevant titles + Paris/Remote locations so the shared
``_post_filter`` keeps the rows (it drops non-tech and off-region jobs).
"""
from __future__ import annotations

import pytest

from job_agent.intake.sources import base
from job_agent.intake.sources.base import FreeApiError, FreeApiSearch
from job_agent.intake.sources.registry import search_free_api_jobs


# ── fake HTTP plumbing ───────────────────────────────────────────────────────


class _FakeResponse:
    def __init__(self, *, json_data=None, text: str = "", status_code: int = 200,
                 content: bytes = b"x", content_type: str = "application/json"):
        self._json_data = json_data
        self.text = text
        self.status_code = status_code
        self.content = content
        self.headers = {"Content-Type": content_type}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        if self._json_data is None:
            raise ValueError("no JSON")
        return self._json_data


def _patch_get(monkeypatch, response: _FakeResponse):
    """Patch the shared requests.get so every provider sees canned data."""
    captured: dict = {}

    def _fake_get(url, params=None, headers=None, timeout=None):
        captured["url"] = url
        captured["params"] = params
        return response

    monkeypatch.setattr(base.requests, "get", _fake_get)
    return captured


# ── per-provider canned JSON payloads ────────────────────────────────────────

_REMOTIVE = {"jobs": [{
    "title": "Data Scientist", "company_name": "Acme", "url": "https://remotive.com/job/1",
    "candidate_required_location": "Remote", "description": "<p>Build ML models</p>",
    "tags": ["python", "ml"], "job_type": "full_time", "publication_date": "2026-01-01",
}]}

_REMOTEOK = [
    {"legal": "ignore me"},  # leading non-job item must be skipped (no "position" key)
    {"position": "Machine Learning Engineer", "company": "Globex", "url": "https://remoteok.com/l/1",
     "apply_url": "https://remoteok.com/apply/1", "location": "Remote",
     "description": "Deep learning", "tags": ["python", "pytorch"], "date": "2026-01-02"},
]

_ARBEITNOW = {"data": [{
    "title": "Data Engineer", "company_name": "Hooli", "url": "https://arbeitnow.com/job/1",
    "location": "Paris", "description": "ETL pipelines", "tags": ["sql", "airflow"],
    "remote": True, "job_types": ["full_time"], "created_at": 1700000000,
}]}

_THEMUSE = {"results": [{
    "name": "Data Analyst", "company": {"name": "Initech"}, "contents": "<p>SQL dashboards</p>",
    "locations": [{"name": "Paris, France"}], "categories": [{"name": "Data Science"}],
    "tags": [{"name": "sql"}], "refs": {"landing_page": "https://themuse.com/job/1"},
    "type": "Full Time", "publication_date": "2026-01-03",
}]}

_GREENHOUSE = {"jobs": [{
    "title": "ML Engineer", "absolute_url": "https://boards.greenhouse.io/x/jobs/1",
    "content": "<p>Train models</p>", "location": {"name": "Paris"},
    "departments": [{"name": "Engineering"}], "offices": [{"name": "Paris"}],
    "updated_at": "2026-01-04",
}]}


@pytest.mark.parametrize(
    "source, board, payload, expected_title, expected_company",
    [
        ("remotive", "", _REMOTIVE, "Data Scientist", "Acme"),
        ("remoteok", "", _REMOTEOK, "Machine Learning Engineer", "Globex"),
        ("arbeitnow", "", _ARBEITNOW, "Data Engineer", "Hooli"),
        ("themuse", "", _THEMUSE, "Data Analyst", "Initech"),
        ("greenhouse", "acme", _GREENHOUSE, "ML Engineer", "acme"),
    ],
)
def test_provider_maps_core_fields(monkeypatch, source, board, payload, expected_title, expected_company):
    # Arrange
    _patch_get(monkeypatch, _FakeResponse(json_data=payload))

    # Act
    jobs = search_free_api_jobs(source, query="", location="", board=board, limit=10)

    # Assert
    assert len(jobs) == 1, f"{source} should parse exactly one listing"
    job = jobs[0]
    assert job.title == expected_title
    assert job.company == expected_company
    assert (job.apply_url or job.source_url), "a usable URL must be mapped"


@pytest.mark.parametrize("source, board", [
    ("remotive", ""), ("arbeitnow", ""), ("themuse", ""), ("greenhouse", "acme"),
])
def test_provider_returns_empty_on_empty_payload(monkeypatch, source, board):
    # Arrange — dict-shaped sources see an empty list of items.
    _patch_get(monkeypatch, _FakeResponse(json_data={"jobs": [], "data": [], "results": []}))

    # Act
    jobs = search_free_api_jobs(source, query="", location="", board=board, limit=10)

    # Assert
    assert jobs == []


@pytest.mark.parametrize("source, board", [
    ("remotive", ""), ("arbeitnow", ""), ("themuse", ""), ("greenhouse", "acme"),
])
def test_provider_tolerates_unexpected_shape(monkeypatch, source, board):
    # Arrange — API returns a bare list/None where a dict was expected.
    _patch_get(monkeypatch, _FakeResponse(json_data=["unexpected"]))

    # Act
    jobs = search_free_api_jobs(source, query="", location="", board=board, limit=10)

    # Assert — provider degrades to an empty result rather than raising.
    assert jobs == []


def test_remoteok_skips_non_job_leading_item(monkeypatch):
    # Arrange — RemoteOK's feed leads with a non-job metadata object.
    _patch_get(monkeypatch, _FakeResponse(json_data=_REMOTEOK))

    # Act
    jobs = search_free_api_jobs("remoteok", query="", location="", limit=10)

    # Assert — only the real posting survives; remote flag is set.
    assert len(jobs) == 1
    assert jobs[0].remote is True


def test_greenhouse_without_board_raises_free_api_error():
    # Arrange / Act / Assert — board is mandatory for Greenhouse.
    with pytest.raises(FreeApiError):
        search_free_api_jobs("greenhouse", query="", board="", limit=10)


def test_unknown_source_raises_free_api_error():
    with pytest.raises(FreeApiError):
        search_free_api_jobs("not-a-real-source", query="data", limit=5)


def test_source_alias_resolves_to_canonical(monkeypatch):
    # Arrange — "remote-ok" is an alias for "remoteok".
    _patch_get(monkeypatch, _FakeResponse(json_data=_REMOTEOK))

    # Act
    jobs = search_free_api_jobs("remote-ok", query="", location="", limit=10)

    # Assert
    assert len(jobs) == 1
    assert jobs[0].source == "api:remoteok"


def test_query_filter_drops_off_topic_titles(monkeypatch):
    # Arrange — a non-tech retail role must be filtered out of a "data" search.
    payload = {"jobs": [
        {"title": "Vendeur en magasin", "company_name": "Shop", "url": "https://x/1",
         "candidate_required_location": "Paris", "description": "POS data terminal"},
        {"title": "Data Scientist", "company_name": "Acme", "url": "https://x/2",
         "candidate_required_location": "Remote", "description": "ML"},
    ]}
    _patch_get(monkeypatch, _FakeResponse(json_data=payload))

    # Act
    jobs = search_free_api_jobs("remotive", query="data", location="", limit=10)

    # Assert — only the tech-relevant title remains.
    titles = [job.title for job in jobs]
    assert titles == ["Data Scientist"]


# ── XML provider (Personio) ──────────────────────────────────────────────────

_PERSONIO_XML = """<?xml version="1.0" encoding="UTF-8"?>
<workzag-jobs>
  <position>
    <id>42</id>
    <name>Data Scientist</name>
    <office>Paris</office>
    <department>Engineering</department>
    <recruitingCategory>Data</recruitingCategory>
    <employmentType>permanent</employmentType>
    <jobDescriptions>
      <jobDescription><name>Role</name><value>Build models</value></jobDescription>
    </jobDescriptions>
  </position>
</workzag-jobs>
"""


def test_personio_parses_xml_position(monkeypatch):
    # Arrange
    _patch_get(monkeypatch, _FakeResponse(text=_PERSONIO_XML, content_type="application/xml"))

    # Act
    jobs = search_free_api_jobs("personio", query="", location="", board="acme", limit=10)

    # Assert
    assert len(jobs) == 1
    job = jobs[0]
    assert job.title == "Data Scientist"
    assert job.company == "acme"
    assert "42" in (job.apply_url or "")


def test_personio_without_board_raises():
    with pytest.raises(FreeApiError):
        search_free_api_jobs("personio", query="", board="", limit=10)


def test_personio_malformed_xml_raises_free_api_error(monkeypatch):
    # Arrange — broken XML must surface a clear FreeApiError, not a raw ParseError.
    _patch_get(monkeypatch, _FakeResponse(text="<not-valid", content_type="application/xml"))

    # Act / Assert
    with pytest.raises(FreeApiError):
        search_free_api_jobs("personio", query="", board="acme", limit=10)


# ── additional board/keyword providers ──────────────────────────────────────

_HIMALAYAS = {"jobs": [{
    "title": "Data Scientist", "companyName": "Remote Co", "applicationLink": "https://himalayas.app/j/1",
    "jobUrl": "https://himalayas.app/j/1", "locationRestrictions": ["Worldwide"],
    "category": ["Data Science"], "description": "ML role", "employmentType": "Full Time",
}]}

_JOBICY = {"jobs": [{
    "jobTitle": "Machine Learning Engineer", "companyName": "Jobicy Co", "url": "https://jobicy.com/j/1",
    "jobGeo": "Remote", "jobDescription": "Build models", "jobIndustry": ["AI"], "jobType": ["Full Time"],
}]}

_LEVER = [{
    "text": "Data Engineer", "hostedUrl": "https://jobs.lever.co/x/1",
    "description": "Pipelines", "categories": {"team": "Data", "location": "Paris", "commitment": "Full-time"},
}]

_ASHBY = {"jobs": [{
    "title": "ML Engineer", "jobUrl": "https://jobs.ashbyhq.com/x/1", "applyUrl": "https://jobs.ashbyhq.com/x/1/apply",
    "descriptionPlain": "Train models", "location": "Paris", "isRemote": False,
    "department": "Engineering", "team": "ML",
}]}

_RECRUITEE = {"offers": [{
    "title": "Data Scientist", "careers_url": "https://x.recruitee.com/o/1",
    "description": "Analytics", "location": "Paris", "tags": ["python"], "employment_type": "Full-time",
}]}

_SMARTRECRUITERS = {"content": [{
    "name": "Data Analyst", "ref": {"postingUrl": "https://jobs.smartrecruiters.com/x/1"},
    "location": {"city": "Paris", "country": "France"}, "description": "SQL dashboards",
    "department": {"label": "Data"}, "function": {"label": "Analytics"},
}]}

_WORKABLE = {"results": [{
    "title": "Data Engineer", "url": "https://apply.workable.com/x/1",
    "location": {"city": "Paris", "country": "France"}, "description": "ETL", "department": "Engineering",
}]}


@pytest.mark.parametrize(
    "source, board, payload, expected_title",
    [
        ("himalayas", "", _HIMALAYAS, "Data Scientist"),
        ("jobicy", "", _JOBICY, "Machine Learning Engineer"),
        ("lever", "x", _LEVER, "Data Engineer"),
        ("ashby", "x", _ASHBY, "ML Engineer"),
        ("recruitee", "x", _RECRUITEE, "Data Scientist"),
        ("smartrecruiters", "x", _SMARTRECRUITERS, "Data Analyst"),
        ("workable", "x", _WORKABLE, "Data Engineer"),
    ],
)
def test_more_providers_map_title_and_url(monkeypatch, source, board, payload, expected_title):
    # Arrange
    _patch_get(monkeypatch, _FakeResponse(json_data=payload))

    # Act
    jobs = search_free_api_jobs(source, query="", location="", board=board, limit=10)

    # Assert
    assert len(jobs) == 1
    assert jobs[0].title == expected_title
    assert (jobs[0].apply_url or jobs[0].source_url)


@pytest.mark.parametrize("source", ["lever", "ashby", "recruitee", "smartrecruiters", "workable"])
def test_board_providers_require_board(source):
    with pytest.raises(FreeApiError):
        search_free_api_jobs(source, query="", board="", limit=10)


def test_freeapisearch_is_frozen():
    # Arrange
    search = FreeApiSearch(source="remotive")

    # Act / Assert — value object must be immutable.
    with pytest.raises(Exception):
        search.query = "mutated"  # type: ignore[misc]
