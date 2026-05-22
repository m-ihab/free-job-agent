"""France Travail OAuth token helpers shared across endpoints."""
from __future__ import annotations

import os
from typing import Any

import requests

from job_agent.intake.api_cache import read_cached_json, write_cached_json


def france_travail_env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _scope_candidates(client_id: str) -> list[str]:
    configured = france_travail_env("FRANCE_TRAVAIL_SCOPE")
    app_scope = f"application_{client_id}"
    candidates = [
        configured,
        f"{app_scope} api_offresdemploiv2 o2dsoffre",
        f"api_offresdemploiv2 o2dsoffre {app_scope}",
        f"o2dsoffre api_offresdemploiv2 {app_scope}",
        "api_offresdemploiv2 o2dsoffre",
        "o2dsoffre api_offresdemploiv2",
    ]
    unique: list[str] = []
    for scope in candidates:
        scope = scope.strip()
        if scope and scope not in unique:
            unique.append(scope)
    return unique


def france_travail_token(*, timeout: int, use_cache: bool, cache_ttl_hours: float) -> str:
    client_id = france_travail_env("FRANCE_TRAVAIL_CLIENT_ID")
    client_secret = france_travail_env("FRANCE_TRAVAIL_CLIENT_SECRET")
    token_url = france_travail_env(
        "FRANCE_TRAVAIL_TOKEN_URL",
        "https://entreprise.francetravail.fr/connexion/oauth2/access_token?realm=/partenaire",
    )
    if not client_id or not client_secret:
        raise ValueError("Missing France Travail OAuth credentials.")
    last_error: Exception | None = None
    for scope in _scope_candidates(client_id):
        cache_params: dict[str, Any] = {"client_id": client_id, "scope": scope, "kind": "oauth_token"}
        if use_cache:
            cached = read_cached_json(token_url, cache_params, min(cache_ttl_hours, 0.75))
            if isinstance(cached, dict) and cached.get("access_token"):
                return str(cached["access_token"])
        response = requests.post(
            token_url,
            data={
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
                "scope": scope,
            },
            timeout=timeout,
        )
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            last_error = exc
            if response.status_code in {400, 401, 403}:
                continue
            raise
        try:
            payload = response.json()
        except ValueError:
            content_type = response.headers.get("Content-Type", "unknown")
            last_error = ValueError(
                "France Travail OAuth returned a non-JSON response "
                f"(HTTP {response.status_code}, Content-Type: {content_type}). "
                "Check that the token URL, realm, client id, secret, and scope match the France Travail portal."
            )
            continue
        token = payload.get("access_token")
        if token:
            if use_cache:
                write_cached_json(token_url, cache_params, {"access_token": token})
            return str(token)
        last_error = ValueError("France Travail OAuth response did not contain access_token")
    if last_error:
        raise last_error
    raise ValueError("No France Travail OAuth scope candidates were available.")
