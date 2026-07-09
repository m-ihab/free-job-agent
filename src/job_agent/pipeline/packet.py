"""Packet orchestration (split from pipeline.py, R1 2026-07-09).

G-3 seam rule: the AI trio (analyze_fit/classify_job/summarize_job),
generate_cover_letter, and generate_packet_for_job are resolved through the
``job_agent.pipeline`` facade AT CALL TIME — tests patch those names on the
facade, and patching must keep working after this split. Do not "optimize"
them into direct imports.
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from job_agent.config import AppConfig
from job_agent.cover_letter_gate import should_generate_cover_letter
from job_agent.filters import FilterConfig, apply_filters
from job_agent.generator.application_brief import build_application_brief
from job_agent.generator.cv import tailor_cv
from job_agent.generator.interview_prep import generate_interview_prep
from job_agent.generator.outreach_email import generate_outreach_email
from job_agent.generator.qa import build_screening_answers_for_job, screening_answers_to_dict
from job_agent.hashutil import sha256_file, sha256_json
from job_agent.pipeline.artifacts import (
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
from job_agent.pipeline.intake_ops import _tracker, add_file_job, score_and_save
from job_agent.polish import PolishOptions
from job_agent.renderer.assistant_render import render_assistant_page
from job_agent.renderer.html_render import render_html
from job_agent.renderer.latex_render import copy_latex_assets, render_latex_source
from job_agent.renderer.pdf_render import render_pdf
from job_agent.schemas.job import JobListing, JobStatus
from job_agent.schemas.packet import ApplicationPacket, DocumentArtifact, PacketStatus

logger = logging.getLogger(__name__)


def _seams():
    """The facade module — patch target for tests (G-3). Imported lazily to
    avoid a circular import at package load."""
    from job_agent import pipeline
    return pipeline


def generate_packet_for_job(
    config: AppConfig,
    job_id: str,
    force: bool = False,
    fast_mode: bool = False,
    profile_bundle: "tuple | None" = None,
) -> ApplicationPacket:
    """Generate a full application packet for one job.

    ``fast_mode=True`` is used by the autopilot background loop:
    - AI calls run in parallel (analyze_fit + classify + summarize concurrently).
    - LaTeX compilation is skipped; a quick reportlab PDF is used instead.
    - CV/cover HTML renders and the assistant page are skipped.
    This cuts per-packet time from ~45 s (with LaTeX) to ~8–15 s.

    ``profile_bundle`` may be passed in from the autopilot to avoid reloading
    profile JSON files for every packet in a cycle.
    """
    seams = _seams()
    tracker = _tracker(config)
    job = tracker.get_job(job_id)
    if not job:
        raise ValueError(f"Job not found: {job_id}")
    if profile_bundle is not None:
        profile, master_cv, qa_profile = profile_bundle
    else:
        # Facade lookup — tests patch pipeline.load_profile_bundle (G-3 seam).
        profile, master_cv, qa_profile = seams.load_profile_bundle(config)

    # Suggestion C: duplicate packet guard — warn loudly but proceed when force=True
    existing_packets = tracker.db.get_packets_for_job(job.id)
    if existing_packets and not force:
        raise RuntimeError(
            f"A packet already exists for this job (version {existing_packets[-1].version}). "
            "Pass --force to regenerate."
        )

    filter_result = apply_filters(job, FilterConfig(), profile)
    if not filter_result.passed and not force:
        job.status = JobStatus.FILTERED
        tracker.db.save_job(job)
        tracker.db.log_event(job.id, "FILTER_FAILED", {"reasons": filter_result.reasons, "risk_flags": filter_result.risk_flags})
        raise RuntimeError("Job failed hard filters: " + "; ".join(filter_result.reasons))

    job = score_and_save(config, job, profile)

    # Suggestion B: language mismatch warning — flag when a French-only job
    # will receive an English cover letter from a non-French-speaking candidate.
    profile_langs_lower = {lang.lower() for lang in (profile.languages or [])}
    job_langs_lower = {lang.lower() for lang in (job.languages or [])}
    if "french" in job_langs_lower and "french" not in profile_langs_lower:
        if "LANGUAGE_MISMATCH" not in job.risk_flags:
            job.risk_flags.append("LANGUAGE_MISMATCH")
            tracker.db.save_job(job)

    polish_opts = PolishOptions.from_env()
    model_name = ""
    try:
        from job_agent.polish import resolve_ollama_model
        model_name = resolve_ollama_model(polish_opts)
    except Exception:
        logger.debug("Ollama model resolution failed; AI phase runs without a model name", exc_info=True)
        model_name = ""

    # Run AI calls in parallel — analyze_fit + classify + summarize concurrently.
    # Resolved via the facade so test patches on job_agent.pipeline.* hit (G-3).
    fit_analysis = None
    classification = None
    tldr = None
    with ThreadPoolExecutor(max_workers=3, thread_name_prefix="ai") as ai_pool:
        f_fit = ai_pool.submit(seams.analyze_fit, job, master_cv, profile, polish_opts)
        f_cls = ai_pool.submit(seams.classify_job, job, polish_opts)
        f_tldr = ai_pool.submit(seams.summarize_job, job, polish_opts)
        try:
            fit_analysis = f_fit.result()
        except Exception:
            logger.warning("AI fit analysis failed for job %s; continuing without it.", job.id, exc_info=True)
            fit_analysis = None
        try:
            classification = f_cls.result()
        except Exception:
            logger.warning("AI job classification failed for job %s; continuing without it.", job.id, exc_info=True)
            classification = None
        try:
            tldr = f_tldr.result()
        except Exception:
            logger.warning("AI job summary failed for job %s; continuing without it.", job.id, exc_info=True)
            tldr = None

    if fit_analysis is not None:
        ai_lines = [
            f"AI verdict: {fit_analysis.verdict} ({fit_analysis.score}/100, confidence {int(fit_analysis.confidence * 100)}%)",
        ]
        if fit_analysis.strengths:
            ai_lines.append("AI strengths: " + "; ".join(fit_analysis.strengths[:4]))
        if fit_analysis.gaps:
            ai_lines.append("AI gaps: " + "; ".join(fit_analysis.gaps[:4]))
        if fit_analysis.suggested_emphasis:
            ai_lines.append("Suggested emphasis: " + ", ".join(fit_analysis.suggested_emphasis[:6]))
        for line in ai_lines:
            if line not in job.fit_notes:
                job.fit_notes.append(line)
        tracker.db.save_job(job)
        tracker.db.save_ai_cache(job.id, "fit", fit_analysis.to_dict(), model_name)
    if classification:
        tracker.db.save_ai_cache(job.id, "classify", classification, model_name)
    if tldr:
        tracker.db.save_ai_cache(job.id, "summary", tldr, model_name)
    cv_md = tailor_cv(job, master_cv, profile)
    template_path = (config.profiles_dir / "main.tex") if config.profiles_dir else None  # type: ignore[operator]
    cv_tex = render_latex_source(
        cv_md,
        title=f"CV - {job.title}",
        template_path=template_path,
        job=job,
        master_cv=master_cv,
        profile=profile,
    )
    include_cover_letter = should_generate_cover_letter(job, job.fit_score, config)
    letter_md = seams.generate_cover_letter(job, master_cv, profile) if include_cover_letter else ""
    screening_answers = build_screening_answers_for_job(job, qa_profile)
    qa_answers = screening_answers_to_dict(screening_answers)
    needs_screening_review = any(answer.needs_review for answer in screening_answers)

    # In fast mode (autopilot background): skip heavy HTML renders and LaTeX
    # compilation so a 5-packet batch finishes in ~15 s instead of ~3 min.
    if not fast_mode:
        outreach_md = generate_outreach_email(job, master_cv, profile)
        interview_md = generate_interview_prep(job, master_cv, profile)
        interview_md += _story_bank_section(tracker, master_cv, job)
        cv_html = render_html(cv_md, title=f"CV - {job.title}")
        letter_html = render_html(letter_md, title=f"Cover Letter - {job.title}") if letter_md else ""
    else:
        outreach_md = ""
        interview_md = ""
        cv_html = ""
        letter_html = ""

    next_version = len(tracker.db.get_packets_for_job(job.id)) + 1
    safe_company = job.company[:24].replace("/", "-").replace("\\", "-").strip() or "company"
    out_dir = (config.outputs_dir or (config.data_dir / "outputs")) / f"{safe_company}_{job.id[:8]}" / f"packet_v{next_version}"
    out_dir.mkdir(parents=True, exist_ok=True)
    artifacts: list[DocumentArtifact] = []
    cv_md_path = out_dir / "cv.md"
    cv_tex_path = out_dir / "cv.tex"
    cv_html_path = out_dir / "cv.html"
    letter_md_path = out_dir / "cover_letter.md"
    letter_html_path = out_dir / "cover_letter.html"
    cv_pdf_path = out_dir / "cv.pdf"
    letter_pdf_path = out_dir / "cover_letter.pdf"
    temp_packet_id = f"pkt_{job.id[:8]}_v{next_version}"

    artifacts.append(_write_text(cv_md_path, cv_md))
    artifacts.append(_write_text(cv_tex_path, cv_tex))
    copy_latex_assets(config.profiles_dir, out_dir)

    master_cv_pdf = None
    if config.profiles_dir:
        candidate_pdf = Path(config.profiles_dir) / "CV.pdf"
        if candidate_pdf.exists():
            master_cv_pdf = candidate_pdf

    if fast_mode:
        # Skip LaTeX compilation — use quick reportlab PDF directly.
        # LaTeX .tex is already written above; user can compile manually or
        # click "Regenerate PDF" in the dashboard to get the full LaTeX version.
        render_pdf(cv_md, cv_pdf_path, title="Tailored CV")
        cv_pdf_artifact = DocumentArtifact(kind="cv_pdf", path=str(cv_pdf_path), sha256=sha256_file(cv_pdf_path))
        latex_warning: str | None = (
            "Fast-mode PDF: generated with reportlab (not LaTeX). "
            "Open the packet and click 'Regenerate PDF' for the full LaTeX-compiled version."
        )
        artifacts.append(cv_pdf_artifact)
    else:
        artifacts.append(_write_text(cv_html_path, cv_html))
        cv_pdf_artifact, latex_warning = _write_cv_pdf(cv_md, cv_tex_path, cv_pdf_path, master_cv_pdf=master_cv_pdf)
        artifacts.append(cv_pdf_artifact)

    if letter_md:
        artifacts.append(_write_text(letter_md_path, letter_md))

    if not fast_mode and letter_md:
        artifacts.append(_write_text(letter_html_path, letter_html))
        artifacts.append(_write_pdf(letter_md, letter_pdf_path, "cover_letter_pdf", "Cover Letter"))
        artifacts.append(_write_text(out_dir / "outreach_email.md", outreach_md))
        artifacts.append(_write_text(out_dir / "interview_prep.md", interview_md))
    elif not fast_mode:
        artifacts.append(_write_text(out_dir / "outreach_email.md", outreach_md))
        artifacts.append(_write_text(out_dir / "interview_prep.md", interview_md))

    if fit_analysis is not None:
        artifacts.append(_write_text(out_dir / "ai_fit_brief.md", _render_ai_brief(job, fit_analysis)))

    # G1: post-render ATS-parse self-check on the CV PDF we just wrote (fail-soft).
    artifacts.extend(_write_ats_check_artifacts(job, cv_md, cv_pdf_path, out_dir))

    # Per-application brief (deterministic, grounded): headline, summary, keywords.
    brief = build_application_brief(job, master_cv, profile)

    risk_flags = sorted(set(job.risk_flags + filter_result.risk_flags + (["screening_question_needs_manual_review"] if needs_screening_review else [])))
    if latex_warning:
        artifacts.append(_write_text(out_dir / "latex_warning.txt", latex_warning))
    artifacts.append(_write_text(out_dir / "external_agent_prompt.md", _render_external_agent_prompt(job, temp_packet_id, artifacts)))

    if fast_mode:
        assistant_html = ""
    else:
        assistant_html = render_assistant_page(
            packet_id=temp_packet_id,
            job=job,
            profile=profile,
            artifacts=artifacts,
            screening_answers=screening_answers,
            fit_score=job.fit_score,
            fit_decision=job.fit_decision,
            risk_flags=risk_flags,
        )
        assistant_art = _write_text(out_dir / "assistant.html", assistant_html)
        artifacts.append(assistant_art)

    packet = ApplicationPacket(
        id=temp_packet_id,
        job_id=job.id,
        job_fingerprint=job.fingerprint,
        version=next_version,
        status=PacketStatus.READY if not risk_flags else PacketStatus.NEEDS_REVIEW,
        fit_score=job.fit_score,
        fit_confidence=job.fit_confidence,
        fit_decision=job.fit_decision,
        fit_notes=job.fit_notes,
        risk_flags=risk_flags,
        profile_hash=sha256_json(profile.dict()),
        master_cv_hash=sha256_json(master_cv.dict()),
        qa_profile_hash=sha256_json(qa_profile.dict()),
        artifacts=artifacts,
        screening_answers=screening_answers,
        tailored_cv_md=cv_md,
        tailored_cv_html=cv_html,
        tailored_cv_pdf_path=str(cv_pdf_path),
        cover_letter_md=letter_md,
        cover_letter_html=letter_html,
        cover_letter_pdf_path=str(letter_pdf_path) if (letter_md and not fast_mode) else "",
        qa_answers=qa_answers,
        assistant_page_html=assistant_html,
        headline=brief["headline"],
        summary=brief["summary"],
        keywords=brief["keywords"],
    )
    preflight_artifact = _write_preflight_artifact(config, job, profile, packet, out_dir)
    if preflight_artifact is not None:
        packet.artifacts.append(preflight_artifact)
    proof_pack_artifact = _write_proof_pack_artifact(config, job, profile, packet, out_dir)
    if proof_pack_artifact is not None:
        packet.artifacts.append(proof_pack_artifact)
    packet.artifacts.extend(_write_evaluation_artifacts(config, job, profile, packet, out_dir, tracker))

    # In full mode, rewrite assistant page with the finalised packet ID.
    if not fast_mode:
        assistant_html = render_assistant_page(
            packet_id=packet.id,
            job=job,
            profile=profile,
            artifacts=artifacts,
            screening_answers=screening_answers,
            fit_score=job.fit_score,
            fit_decision=job.fit_decision,
            risk_flags=risk_flags,
        )
        (out_dir / "assistant.html").write_text(assistant_html, encoding="utf-8")
        packet.assistant_page_html = assistant_html
        for idx, art in enumerate(packet.artifacts):
            if art.path == str(out_dir / "assistant.html"):
                packet.artifacts[idx].sha256 = sha256_file(out_dir / "assistant.html")

    tracker.save_packet(packet)
    job.status = JobStatus.PACKET_READY if packet.status == PacketStatus.READY else JobStatus.NEEDS_REVIEW
    tracker.db.save_job(job)
    tracker.db.log_event(job.id, "PACKET_READY", {"packet_id": packet.id, "status": packet.status.value}, packet_id=packet.id)
    return packet


def process_file(config: AppConfig, path: Path | str, title: str | None = None, company: str | None = None, url: str | None = None, force: bool = False) -> tuple[JobListing, ApplicationPacket | None, bool]:
    job, created = add_file_job(config, path, title=title, company=company, url=url)
    if not created:
        return job, None, False
    # Facade lookup so tests patching pipeline.generate_packet_for_job still hit (G-3).
    packet = _seams().generate_packet_for_job(config, job.id, force=force)
    return job, packet, True
