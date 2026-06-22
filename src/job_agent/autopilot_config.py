"""Configuration and runtime-state dataclasses for the autopilot loop."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AutopilotConfig:
    queries: list[str] = field(default_factory=lambda: [
        "data scientist", "data science", "machine learning",
        "data analyst", "data engineer",
    ])
    location: str = "Paris"
    language: str = "both"
    interval_minutes: int = 30
    auto_packet_threshold: int = 75
    multi_source_limit: int = 8
    france_travail_limit: int = 15
    radius_km: int = 25
    min_relevance: int = 20
    france_eu_only: bool = True
    use_france_travail: bool = True
    use_multi_source: bool = True
    use_cac40_sweep: bool = True
    cac40_limit_per_company: int = 3
    max_packets_per_cycle: int = 5
    contract_type: str = "stage_and_alternance"  # "all"|"stage"|"alternance"|"stage_and_alternance"
    email_notify: bool = False
    auto_apply: bool = False
    auto_apply_mode: str = "fill_and_confirm"
    auto_apply_min_score: int = 75


@dataclass
class AutopilotState:
    running: bool = False
    last_run_at: str | None = None
    last_error: str | None = None
    cycles_completed: int = 0
    jobs_added_total: int = 0
    packets_built_total: int = 0
    last_summary: dict[str, Any] | None = None
    started_at: str | None = None
    queries_count: int = 0
