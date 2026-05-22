"""Endpoint registry for France Travail APIs with local overrides."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class EndpointSpec:
    key: str
    path: str
    rate_per_sec: float
    method: str = "GET"
    params: dict[str, Any] = field(default_factory=dict)
    enabled: bool = True


DEFAULT_ENDPOINTS: dict[str, EndpointSpec] = {
    "job_offers": EndpointSpec("job_offers", "/partenaire/offresdemploi/v2/offres/search", 10),
    "anotea": EndpointSpec("anotea", "", 8, enabled=False),
    "living_environment": EndpointSpec("living_environment", "", 2, enabled=False),
    "my_job_events": EndpointSpec("my_job_events", "", 10, enabled=False),
    "open_training": EndpointSpec("open_training", "", 10, enabled=False),
    "agency_repository": EndpointSpec("agency_repository", "", 1, enabled=False),
    "training_leavers": EndpointSpec("training_leavers", "", 10, enabled=False),
    "territory_info": EndpointSpec("territory_info", "", 10, enabled=False),
    "labour_market": EndpointSpec("labour_market", "", 10, enabled=False),
    "access_to_employment": EndpointSpec("access_to_employment", "", 10, enabled=False),
    "rome_skills": EndpointSpec("rome_skills", "", 1, enabled=False),
    "rome_contexts": EndpointSpec("rome_contexts", "", 1, enabled=False),
    "rome_job_descriptions": EndpointSpec("rome_job_descriptions", "", 1, enabled=False),
    "rome_crafts": EndpointSpec("rome_crafts", "", 1, enabled=False),
    "check_offer_jcmo": EndpointSpec("check_offer_jcmo", "", 10, enabled=False),
    "right_box": EndpointSpec("right_box", "", 2, enabled=False),
    "romeo": EndpointSpec("romeo", "", 3, enabled=False),
    "summary_employer_pages": EndpointSpec("summary_employer_pages", "", 50, enabled=False),
}


def _default_endpoints_file() -> Path:
    return Path.cwd() / ".france_travail.endpoints.local.json"


def load_endpoint_base_url() -> str:
    base_url = os.environ.get("FRANCE_TRAVAIL_API_BASE_URL", "https://api.francetravail.io").strip()
    path_override = os.environ.get("FRANCE_TRAVAIL_ENDPOINTS_FILE", "").strip()
    candidate = Path(path_override).expanduser() if path_override else _default_endpoints_file()
    if not candidate.exists():
        return base_url
    try:
        payload = json.loads(candidate.read_text(encoding="utf-8"))
    except Exception:
        return base_url
    if isinstance(payload, dict) and payload.get("base_url"):
        return str(payload["base_url"]).strip()
    return base_url


def load_endpoint_registry() -> dict[str, EndpointSpec]:
    registry = {key: EndpointSpec(**vars(spec)) for key, spec in DEFAULT_ENDPOINTS.items()}
    path_override = os.environ.get("FRANCE_TRAVAIL_ENDPOINTS_FILE", "").strip()
    candidate = Path(path_override).expanduser() if path_override else _default_endpoints_file()
    if not candidate.exists():
        return registry
    try:
        payload = json.loads(candidate.read_text(encoding="utf-8"))
    except Exception:
        return registry
    endpoints = payload.get("endpoints") if isinstance(payload, dict) else None
    if not isinstance(endpoints, dict):
        return registry
    for key, value in endpoints.items():
        if key not in registry or not isinstance(value, dict):
            continue
        spec = registry[key]
        path_value = None
        if value.get("path") is not None:
            path_value = value.get("path")
            spec.path = str(path_value or "")
        if value.get("rate_per_sec") is not None:
            try:
                spec.rate_per_sec = float(value["rate_per_sec"])
            except (TypeError, ValueError):
                pass
        if value.get("method"):
            spec.method = str(value["method"]).upper()
        if isinstance(value.get("params"), dict):
            spec.params = dict(value["params"])
        if "enabled" in value:
            spec.enabled = bool(value.get("enabled"))
        elif path_value:
            spec.enabled = True
        registry[key] = spec
    return registry
