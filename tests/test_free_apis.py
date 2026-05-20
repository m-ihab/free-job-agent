"""Tests for free/read-only public API source connectors."""
from click.testing import CliRunner
import pytest

from job_agent.cli.main import app
from job_agent.intake import free_apis
from job_agent.intake.free_apis import FreeApiError, search_free_api_jobs
from job_agent.schemas.job import JobListing


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


def test_remotive_search_maps_jobs_and_client_filters(monkeypatch):
    calls = []

    def fake_get(url, params=None, headers=None, timeout=None):
        calls.append((url, params, timeout))
        return FakeResponse({
            "jobs": [
                {
                    "title": "Python Platform Engineer",
                    "company_name": "RemoteCo",
                    "candidate_required_location": "Worldwide",
                    "description": "<p>Build Python APIs with Docker.</p>",
                    "url": "https://remotive.com/job/1",
                    "tags": ["python", "docker"],
                    "publication_date": "2026-05-01",
                },
                {
                    "title": "Sales Lead",
                    "company_name": "RemoteCo",
                    "description": "Sell enterprise software.",
                    "url": "https://remotive.com/job/2",
                },
            ]
        })

    monkeypatch.setattr(free_apis.requests, "get", fake_get)
    jobs = search_free_api_jobs("remotive", query="python", limit=10)

    assert len(jobs) == 1
    assert jobs[0].title == "Python Platform Engineer"
    assert jobs[0].company == "RemoteCo"
    assert jobs[0].remote is True
    assert "python" in jobs[0].tech_stack
    assert calls[0][0] == "https://remotive.com/api/remote-jobs"
    assert calls[0][1]["search"] == "python"


def test_remoteok_skips_legal_row_and_maps_salary(monkeypatch):
    def fake_get(url, params=None, headers=None, timeout=None):
        return FakeResponse([
            {"legal": "terms"},
            {
                "position": "Backend Engineer",
                "company": "OK Corp",
                "description": "<p>Go and Postgres.</p>",
                "tags": ["go", "postgres"],
                "apply_url": "https://remoteok.com/jobs/1",
                "salary_min": 150000,
                "salary_max": 180000,
                "date": "2026-05-01T00:00:00+00:00",
            },
        ])

    monkeypatch.setattr(free_apis.requests, "get", fake_get)
    jobs = search_free_api_jobs("remote-ok", query="backend", limit=5)

    assert len(jobs) == 1
    assert jobs[0].salary_min == 150000
    assert jobs[0].salary_max == 180000
    assert jobs[0].apply_url == "https://remoteok.com/jobs/1"


def test_greenhouse_requires_board():
    with pytest.raises(FreeApiError):
        search_free_api_jobs("greenhouse", limit=1)


def test_cli_search_api_can_save_without_profiles(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))

    def fake_search(*args, **kwargs):
        return [JobListing(
            title="Python Engineer",
            company="ExampleCo",
            location="Remote",
            remote=True,
            raw_text="Python Engineer\nBuild APIs with Python.",
            description="Build APIs with Python.",
            tech_stack=["python"],
            apply_url="https://example.com/apply",
            source="api:test",
        )]

    monkeypatch.setattr("job_agent.cli.main.search_free_api_jobs", fake_search)
    result = CliRunner().invoke(app, ["search-api", "remotive", "--query", "python", "--save"])

    assert result.exit_code == 0, result.output
    assert "Python Engineer" in result.output
    assert "Saved 1 new jobs" in result.output


def test_public_api_cache_reuses_response(tmp_path, monkeypatch):
    monkeypatch.setenv("JOB_AGENT_API_CACHE_DIR", str(tmp_path / "cache"))
    calls = []

    def fake_get(url, params=None, headers=None, timeout=None):
        calls.append((url, params))
        return FakeResponse({
            "jobs": [{
                "title": "Python Engineer",
                "company_name": "CacheCo",
                "candidate_required_location": "Worldwide",
                "description": "Python role",
                "url": "https://remotive.com/job/cache",
                "tags": ["python"],
            }]
        })

    monkeypatch.setattr(free_apis.requests, "get", fake_get)
    first = search_free_api_jobs("remotive", query="python", limit=1, use_cache=True, cache_ttl_hours=12)
    second = search_free_api_jobs("remotive", query="python", limit=1, use_cache=True, cache_ttl_hours=12)

    assert len(first) == 1
    assert len(second) == 1
    assert len(calls) == 1



def test_france_travail_requires_free_credentials(monkeypatch):
    monkeypatch.delenv("FRANCE_TRAVAIL_CLIENT_ID", raising=False)
    monkeypatch.delenv("FRANCE_TRAVAIL_CLIENT_SECRET", raising=False)
    with pytest.raises(FreeApiError):
        search_free_api_jobs("francetravail", query="data", location="Paris", limit=1)


def test_france_travail_maps_search_result(monkeypatch):
    monkeypatch.setenv("FRANCE_TRAVAIL_CLIENT_ID", "client")
    monkeypatch.setenv("FRANCE_TRAVAIL_CLIENT_SECRET", "secret")
    calls = []

    def fake_post(url, data=None, timeout=None):
        calls.append(("POST", url, data, None))
        return FakeResponse({"access_token": "token-123"})

    def fake_get(url, params=None, headers=None, timeout=None):
        calls.append(("GET", url, params, headers))
        return FakeResponse({
            "resultats": [
                {
                    "id": "123ABC",
                    "intitule": "Data Scientist Stage H/F",
                    "description": "Python, machine learning et SQL. Télétravail partiel.",
                    "entreprise": {"nom": "Paris Data Lab"},
                    "lieuTravail": {"libelle": "75 - PARIS 09"},
                    "typeContrat": "MIS",
                    "typeContratLibelle": "Stage",
                    "dateCreation": "2026-05-01T10:00:00Z",
                    "competences": [
                        {"libelle": "Python"},
                        {"libelle": "Machine learning"},
                        {"libelle": "SQL"},
                    ],
                    "origineOffre": {"urlOrigine": "https://candidat.francetravail.fr/offres/recherche/detail/123ABC"},
                }
            ]
        })

    monkeypatch.setattr(free_apis.requests, "post", fake_post)
    monkeypatch.setattr(free_apis.requests, "get", fake_get)
    jobs = search_free_api_jobs("france-travail", query="data scientist stage", location="Paris", limit=1)

    assert len(jobs) == 1
    assert jobs[0].title == "Data Scientist Stage H/F"
    assert jobs[0].company == "Paris Data Lab"
    assert jobs[0].location == "75 - PARIS 09"
    assert jobs[0].salary_currency == "EUR"
    assert jobs[0].apply_url.endswith("123ABC")
    assert "python" in [x.lower() for x in jobs[0].tech_stack]
    assert calls[0][0] == "POST"
    assert calls[1][0] == "GET"
    assert calls[1][2]["motsCles"] == "data scientist stage"
    assert calls[1][2]["departement"] == "75"
    assert calls[1][3]["Authorization"] == "Bearer token-123"
