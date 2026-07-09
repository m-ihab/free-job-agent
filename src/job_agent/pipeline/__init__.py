"""End-to-end orchestration helpers used by the CLI and dashboard.

R1 split (2026-07-09): the 685-line ``pipeline.py`` module became this package —
``intake_ops`` (add/score jobs), ``artifacts`` (packet file writers), and
``packet`` (generate_packet_for_job / process_file). This facade preserves the
COMPLETE import surface of the old module: every name that was reachable as
``job_agent.pipeline.X`` still is.

G-3 patch-seam contract: tests (and only tests) patch these names ON THIS
FACADE — ``analyze_fit``, ``classify_job``, ``summarize_job``,
``generate_cover_letter``, ``generate_packet_for_job``, and the ``embeddings``
module. ``packet.py`` deliberately resolves them through this module at call
time; keep it that way or the patches silently stop hitting real code paths.
"""
from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from job_agent.ai_agent import (
    analyze_fit,
    classify_job,
    summarize_job,
)
from job_agent.config import AppConfig
from job_agent.cover_letter_gate import should_generate_cover_letter
from job_agent.db.database import Database
from job_agent.evidence import EvidenceStore
from job_agent.filters import FilterConfig, apply_filters
from job_agent.fingerprint import set_fingerprint
from job_agent.generator.application_brief import build_application_brief
from job_agent.generator.cover_letter import generate_cover_letter
from job_agent.generator.cv import tailor_cv
from job_agent.generator.interview_prep import generate_interview_prep
from job_agent.generator.outreach_email import generate_outreach_email
from job_agent.generator.preflight import run_preflight
from job_agent.generator.proof_pack import render_proof_pack_markdown
from job_agent.generator.qa import build_screening_answers_for_job, screening_answers_to_dict
from job_agent.hashutil import sha256_file, sha256_json
from job_agent.intake.file import ingest_file
from job_agent import embeddings, story_bank
from job_agent.generator.evaluation import evaluate_job, salary_comparables
from job_agent.intake.paste import ingest_paste
from job_agent.intake.url import ingest_url
from job_agent.normalizer import normalize
from job_agent.polish import PolishOptions
from job_agent.renderer.assistant_render import render_assistant_page
from job_agent.renderer.html_render import render_html
from job_agent.renderer.latex_render import (
    LatexCompileError,
    compact_cv_source,
    compile_latex_to_pdf,
    copy_latex_assets,
    count_pdf_pages,
    render_latex_source,
)
from job_agent.renderer.pdf_render import render_pdf
from job_agent.schemas.candidate import CandidateProfile
from job_agent.schemas.job import JobListing, JobStatus
from job_agent.schemas.packet import ApplicationPacket, DocumentArtifact, PacketStatus
from job_agent.scorer import score_job
from job_agent.tracker import ApplicationTracker
from job_agent.validators import load_profile_bundle

from job_agent.pipeline.artifacts import (
    _enforce_single_page,
    _render_ai_brief,
    _render_external_agent_prompt,
    _story_bank_section,
    _write_ats_check_artifacts,
    _write_cv_pdf,
    _write_evaluation_artifacts,
    _write_pdf,
    _write_preflight_artifact,
    _write_proof_pack_artifact,
    _write_text,
)
from job_agent.pipeline.intake_ops import (
    _semantic_duplicate,
    _tracker,
    add_file_job,
    add_job_to_tracker,
    add_text_job,
    add_url_job,
    score_and_save,
)
from job_agent.pipeline.packet import generate_packet_for_job, process_file

logger = logging.getLogger(__name__)

__all__ = [
    # orchestration API
    "add_file_job", "add_job_to_tracker", "add_text_job", "add_url_job",
    "score_and_save", "generate_packet_for_job", "process_file",
    # patchable seams (G-3)
    "analyze_fit", "classify_job", "summarize_job", "generate_cover_letter",
    "embeddings",
    # helpers kept importable for tests/back-compat
    "_tracker", "_semantic_duplicate", "_write_text", "_write_pdf",
    "_render_ai_brief", "_render_external_agent_prompt", "_enforce_single_page",
    "_write_cv_pdf", "_write_preflight_artifact", "_story_bank_section",
    "_write_evaluation_artifacts", "_write_proof_pack_artifact",
    "_write_ats_check_artifacts",
    # original import surface (kept for pipeline.<name> back-compat)
    "AppConfig", "should_generate_cover_letter", "Database", "EvidenceStore",
    "FilterConfig", "apply_filters", "set_fingerprint", "build_application_brief",
    "tailor_cv", "generate_interview_prep", "generate_outreach_email",
    "run_preflight", "render_proof_pack_markdown",
    "build_screening_answers_for_job", "screening_answers_to_dict",
    "sha256_file", "sha256_json", "ingest_file", "story_bank", "evaluate_job",
    "salary_comparables", "ingest_paste", "ingest_url", "normalize",
    "PolishOptions", "render_assistant_page", "render_html",
    "LatexCompileError", "compact_cv_source", "compile_latex_to_pdf",
    "copy_latex_assets", "count_pdf_pages", "render_latex_source", "render_pdf",
    "CandidateProfile", "JobListing", "JobStatus", "ApplicationPacket",
    "DocumentArtifact", "PacketStatus", "score_job", "ApplicationTracker",
    "load_profile_bundle",
    "json", "logging", "ThreadPoolExecutor", "Path", "logger",
]
