"""Rate-limited client for France Travail partner APIs."""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import requests

from job_agent.intake.api_cache import read_cached_json, write_cached_json
from job_agent.intake.france_travail_auth import france_travail_env, france_travail_token
from job_agent.intake.france_travail_endpoints import EndpointSpec, load_endpoint_base_url, load_endpoint_registry


@dataclass
class ClientConfig:
    timeout: int = 20
    use_cache: bool = True
    cache_ttl_hours: float = 6.0


class RateLimiter:
    def __init__(self) -> None:
        self._next_allowed: dict[str, float] = {}

    def wait(self, key: str, rate_per_sec: float) -> None:
        if rate_per_sec <= 0:
            return
        now = time.monotonic()
        next_allowed = self._next_allowed.get(key, now)
        delay = next_allowed - now
        if delay > 0:
            time.sleep(delay)
        self._next_allowed[key] = max(next_allowed, now) + (1.0 / rate_per_sec)


class FranceTravailClient:
    def __init__(self, config: ClientConfig | None = None) -> None:
        self.config = config or ClientConfig()
        self._registry = load_endpoint_registry()
        self._limiter = RateLimiter()

    def endpoint(self, key: str) -> EndpointSpec | None:
        return self._registry.get(key)

    def request(self, key: str, *, params: dict[str, Any] | None = None, json_body: dict[str, Any] | None = None) -> Any:
        spec = self.endpoint(key)
        if not spec or not spec.enabled or not spec.path:
            raise ValueError(f"France Travail endpoint '{key}' is not configured.")
        base_url = load_endpoint_base_url()
        url = spec.path if spec.path.startswith("http") else base_url.rstrip("/") + "/" + spec.path.lstrip("/")

        method = spec.method.upper()
        payload_params = {**spec.params, **(params or {})}
        cache_params = payload_params if method == "GET" else {**payload_params, **(json_body or {})}

        if self.config.use_cache:
            cached = read_cached_json(url, cache_params, self.config.cache_ttl_hours)
            if cached is not None:
                return cached

        token = france_travail_token(
            timeout=self.config.timeout,
            use_cache=self.config.use_cache,
            cache_ttl_hours=self.config.cache_ttl_hours,
        )
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}

        self._limiter.wait(key, spec.rate_per_sec)
        if method == "POST":
            response = requests.post(url, params=payload_params, json=json_body, headers=headers, timeout=self.config.timeout)
        else:
            response = requests.get(url, params=payload_params, headers=headers, timeout=self.config.timeout)
        response.raise_for_status()
        payload = response.json()
        if self.config.use_cache:
            write_cached_json(url, cache_params, payload)
        return payload
