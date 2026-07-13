"""Curated free-first project specifications for the Career Engine."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProjectTemplate:
    name: str
    problem: str
    dataset_suggestion: str
    stack: list[str]
    hard_part: str
    deliverable: str
    readme_demo_requirements: list[str]
    time_budget_h: int
    gap_tags: list[str]
    recruiter_visibility: int


PROJECT_TEMPLATES = (
    ProjectTemplate(
        name="Free Job Agent: production reliability case study",
        problem="Make a local job-search agent observable, reproducible, and safe under partial failures.",
        dataset_suggestion="Synthetic job listings and synthetic candidate fixtures committed with the project.",
        stack=["Python", "SQLite", "Playwright", "pytest", "structured logging"],
        hard_part="Design fail-closed automation, traceable decisions, recovery paths, and regression tests.",
        deliverable="A production-system case study with an architecture diagram, test receipts, and failure postmortem.",
        readme_demo_requirements=[
            "Synthetic-data quickstart",
            "architecture diagram",
            "failure-mode demo",
            "test evidence",
        ],
        time_budget_h=24,
        gap_tags=["MLOps / deployment", "Data engineering", "Cloud platforms"],
        recruiter_visibility=3,
    ),
    ProjectTemplate(
        name="Production ML monitoring service",
        problem="Detect model and data drift before prediction quality silently degrades.",
        dataset_suggestion="Evidently AI synthetic drift data or a time-split public tabular dataset.",
        stack=["Python", "FastAPI", "MLflow", "Docker", "Prometheus"],
        hard_part="Define service-level indicators, drift thresholds, retraining gates, and rollback behavior.",
        deliverable="Containerized inference and monitoring services with a small operational dashboard.",
        readme_demo_requirements=[
            "One-command local run",
            "drift scenario",
            "runbook",
            "latency and quality metrics",
        ],
        time_budget_h=32,
        gap_tags=["MLOps / deployment", "Machine learning", "Cloud platforms"],
        recruiter_visibility=3,
    ),
    ProjectTemplate(
        name="EU job-market data platform",
        problem="Turn heterogeneous public job feeds into trustworthy skill-demand trends.",
        dataset_suggestion="Small snapshots from no-auth public job APIs plus generated fixtures for tests.",
        stack=["Python", "SQL", "Spark", "Airflow", "dbt"],
        hard_part="Handle schema drift, deduplication, data-quality checks, and incremental backfills.",
        deliverable="Tested batch pipeline, dimensional model, and decision-focused trend dashboard.",
        readme_demo_requirements=[
            "Data lineage",
            "quality report",
            "incremental-run demo",
            "metric definitions",
        ],
        time_budget_h=36,
        gap_tags=["Data engineering", "Analytics / BI", "Cloud platforms"],
        recruiter_visibility=3,
    ),
    ProjectTemplate(
        name="Model evaluation and error-analysis lab",
        problem="Show when a strong aggregate model score hides costly segment failures.",
        dataset_suggestion="UCI Adult, OpenML credit data, or another documented public classification dataset.",
        stack=["Python", "pandas", "scikit-learn", "Jupyter", "pytest"],
        hard_part="Build leakage checks, calibrated baselines, slice metrics, and uncertainty analysis.",
        deliverable="Reproducible evaluation package plus a concise model card and decision memo.",
        readme_demo_requirements=[
            "Baseline comparison",
            "error slices",
            "reproduction command",
            "model card",
        ],
        time_budget_h=20,
        gap_tags=["Machine learning"],
        recruiter_visibility=2,
    ),
    ProjectTemplate(
        name="Decision-grade analytics product",
        problem="Give an operator one reliable view of a business decision rather than a gallery of charts.",
        dataset_suggestion="NYC Taxi, Olist commerce, or another public event-level dataset.",
        stack=["SQL", "dbt", "Python", "Power BI"],
        hard_part="Specify metric contracts, reconcile edge cases, and prove dashboard numbers back to source rows.",
        deliverable="Analytics model, dashboard, metric dictionary, and stakeholder decision brief.",
        readme_demo_requirements=[
            "Metric definitions",
            "source reconciliation",
            "interactive demo",
            "decision narrative",
        ],
        time_budget_h=24,
        gap_tags=["Analytics / BI", "Data engineering"],
        recruiter_visibility=2,
    ),
    ProjectTemplate(
        name="Evidence-grounded AI assistant",
        problem="Answer domain questions with citations while refusing unsupported factual claims.",
        dataset_suggestion="Public technical documentation plus a synthetic evaluation question set.",
        stack=["Python", "FastAPI", "vector search", "Docker", "evaluation harness"],
        hard_part="Measure retrieval quality, groundedness, abstention, latency, and adversarial failure modes.",
        deliverable="Local retrieval service, evaluation report, and recorded failure-aware demo.",
        readme_demo_requirements=[
            "Threat model",
            "evaluation set",
            "groundedness results",
            "failure examples",
        ],
        time_budget_h=30,
        gap_tags=["Machine learning", "MLOps / deployment", "Cloud platforms"],
        recruiter_visibility=3,
    ),
)
