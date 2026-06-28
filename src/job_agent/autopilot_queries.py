"""Smart search-query expansion for an autopilot cycle.

Expansion collaborators (``expand_role_family``, ``suggest_search_queries``,
``load_profile_bundle``, ``expand_france_search_queries``) are reached through
the :mod:`job_agent.autopilot` module object so the autopilot tests'
``monkeypatch.setattr(ap, ...)`` seams keep working after the split.
"""
from __future__ import annotations

import logging
from typing import Any

import job_agent.autopilot as ap

# Hard cap so cycles stay reasonably fast.
_MAX_PLANNED_QUERIES = 24
logger = logging.getLogger(__name__)


def plan_queries(pilot: Any) -> list[str]:
    """Role-family + AI + bilingual fallback query expansion.

    Order of expansion (best-recall mix):
    1. ``expand_role_family`` — deterministic data/AI synonyms (works without
       Ollama; e.g. "data scientist" -> data engineer, ml engineer, ai
       engineer, data analyst).
    2. AI ``suggest_search_queries`` if Ollama is reachable.
    3. ``expand_france_search_queries`` bilingual stage/alternance pack so we
       always test French internship terms.
    """
    planned: list[str] = []

    def _add(query: str) -> None:
        key = (query or "").casefold().strip()
        if not key or len(query) > 70:
            return
        seen = {item.casefold() for item in planned}
        if key in seen:
            return
        planned.append(query.strip())

    # 1) Deterministic role-family expansion always runs.
    for seed in pilot.opts.queries:
        for sibling in ap.expand_role_family(seed):
            _add(sibling)

    # 2) Local-AI plan when reachable.
    try:
        profile, master_cv, _ = ap.load_profile_bundle(pilot.config)
        for seed in pilot.opts.queries[:3]:
            plan = ap.suggest_search_queries(
                profile,
                master_cv,
                seed_query=seed,
                location=pilot.opts.location,
                language=pilot.opts.language,
                internships_only=(pilot.opts.contract_type != "all"),
                limit=4,
            )
            for query in plan.get("queries", []):
                _add(str(query))
    except Exception:
        logger.warning("Autopilot AI query planning failed; using deterministic query expansion.", exc_info=True)

    # 3) French stage/alternance variants as the final safety net.
    for seed in pilot.opts.queries[:4]:
        for query in ap.expand_france_search_queries(seed, limit=4, language=pilot.opts.language):
            _add(query)
            if len(planned) >= _MAX_PLANNED_QUERIES:
                break
    return planned[:_MAX_PLANNED_QUERIES] or pilot.opts.queries
