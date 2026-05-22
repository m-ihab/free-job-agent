"""End-to-end orchestration helpers used by the CLI."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from job_agent.config import AppConfig
from job_agent.db.database import Database
from job_agent.filters import FilterConfig, apply_filters
from job_agent.fingerprint import set_fingerprint
from job_agent.generator.cover_letter import generate_cover_letter
from job_agent.generator.cv import tailor_cv
from job_agent.generator.qa import build_screening_answers_for_job, screening_answers_to_dict
from job_agent.hashutil import sha256_file, sha256_json
from job_agent.intake.file import ingest_file
from job_agent.intake.paste import ingest_paste
from job_agent.intake.url import ingest_url
from job_agent.normalizer import normalize
from job_agent.renderer.assistant_render import render_assistant_page
from job_agent.renderer.html_render import render_html
from job_agent.renderer.latex_render import LatexCompileError, compile_latex_to_pdf, copy_latex_assets, render_latex_source
from job_agent.renderer.pdf_render import render_pdf
from job_agent.schemas.candidate import CandidateProfile, MasterCV, QAProfile
from job_agent.schemas.job import JobListing, JobStatus
from job_agent.schemas.packet import ApplicationPacket, DocumentArtifact, PacketStatus
from job_agent.scorer import score_job
from job_agent.tracker import ApplicationTracker
from job_agent.validators import load_profile_bundle


def _tracker(config: AppConfig) -> ApplicationTracker:
    db = Database(config.db_path)  # type: ignore[arg-type]
    db.initialize()
    return ApplicationTracker(db)


def add_job_to_tracker(config: AppConfig, job: JobListing) -> tuple[JobListing, bool]:
    tracker = _tracker(config)
    job = normalize(job)
    job = set_fingerprint(job)
    existing = tracker.db.get_job_by_fingerprint(job.fingerprint) if job.fingerprint else None
    if existing:
        return existing, False
    tracker.add_job(job)
    return job, True


def add_file_job(config: AppConfig, path: Path | str, title: str | None = None, company: str | None = None, url: str | None = None) -> tuple[JobListing, bool]:
    return add_job_to_tracker(config, ingest_file(path, title=title, company=company, url=url))


def add_text_job(config: AppConfig, text: str, title: str | None = None, company: str | None = None, url: str | None = None) -> tuple[JobListing, bool]:
    return add_job_to_tracker(config, ingest_paste(text, title=title, company=company, url=url))


def add_url_job(config: AppConfig, url: str) -> tuple[JobListing, bool]:
    return add_job_to_tracker(config, ingest_url(url))


def score_and_save(config: AppConfig, job: JobListing, profile: CandidateProfile) -> JobListing:
    tracker = _tracker(config)
    breakdown = score_job(job, profile)
    job.fit_score = breakdown.total_score
    job.fit_confidence = breakdown.confidence
    job.fit_decision = breakdown.decision
    job.fit_notes = breakdown.notes
    job.missing_requirements = breakdown.missing_requirements
    job.risk_flags = sorted(set(job.risk_flags + breakdown.risk_flags))
    tracker.db.save_job(job)
    tracker.update_status(job.id, JobStatus.SCORED)
    return job


def _write_text(path: Path, content: str) -> DocumentArtifact:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    suffix = path.suffix.lower()
    name = path.name.lower()
    if name == "assistant.html":
        kind = "assistant_html"
    elif "cover" in name and suffix == ".md":
        kind = "cover_letter_markdown"
    elif "cover" in name and suffix == ".html":
        kind = "cover_letter_html"
    elif "cv" in name and suffix == ".md":
        kind = "cv_markdown"
    elif "cv" in name and suffix == ".html":
        kind = "cv_html"
    elif "cv" in name and suffix == ".tex":
        kind = "cv_latex"
    elif name == "latex_warning.txt":
        kind = "latex_warning"
    else:
        kind = suffix.lstrip(".") or "file"
    return DocumentArtifact(kind=kind, path=str(path), sha256=sha256_file(path))


def _write_pdf(markdown: str, path: Path, kind: str, title: str) -> DocumentArtifact:
    render_pdf(markdown, path, title=title)
    return DocumentArtifact(kind=kind, path=str(path), sha256=sha256_file(path))


def _write_cv_pdf(cv_md: str, cv_tex_path: Path, cv_pdf_path: Path, fallback_pdf: Path | None = None) -> tuple[DocumentArtifact, str | None]:
    try:
        compile_latex_to_pdf(cv_tex_path, cv_pdf_path)
        return DocumentArtifact(kind="cv_pdf", path=str(cv_pdf_path), sha256=sha256_file(cv_pdf_path)), None
    except LatexCompileError as exc:
        if fallback_pdf and fallback_pdf.exists():
            shutil.copyfile(fallback_pdf, cv_pdf_path)
            warning = (
                "LaTeX CV PDF fallback used: copied profiles/CV.pdf because cv.tex could not be compiled. "
                "This PDF preserves your main.tex visual format but is not role-tailored; install MiKTeX or TeX Live and rerun with --force for a tailored LaTeX PDF. "
                f"Compiler issue: {exc}"
            )
        else:
            render_pdf(cv_md, cv_pdf_path, title="Tailored CV")
            warning = f"LaTeX CV PDF fallback used: {exc}"
        return (
            DocumentArtifact(kind="cv_pdf", path=str(cv_pdf_path), sha256=sha256_file(cv_pdf_path)),
            warning,
        )


def generate_packet_for_job(config: AppConfig, job_id: str, force: bool = False) -> ApplicationPacket:
    tracker = _tracker(config)
    job = tracker.get_job(job_id)
    if not job:
        raise ValueError(f"Job not found: {job_id}")
    profile, master_cv, qa_profile = load_profile_bundle(config)

    filter_result = apply_filters(job, FilterConfig(), profile)
    if not filter_result.passed and not force:
        job.status = JobStatus.FILTERED
        tracker.db.save_job(job)
        tracker.db.log_event(job.id, "FILTER_FAILED", {"reasons": filter_result.reasons, "risk_flags": filter_result.risk_flags})
        raise RuntimeError("Job failed hard filters: " + "; ".join(filter_result.reasons))

    job = score_and_save(config, job, profile)
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
    letter_md = generate_cover_letter(job, master_cv, profile)
    cv_html = render_html(cv_md, title=f"CV - {job.title}")
    letter_html = render_html(letter_md, title=f"Cover Letter - {job.title}")
    screening_answers = build_screening_answers_for_job(job, qa_profile)
    qa_answers = screening_answers_to_dict(screening_answers)
    needs_screening_review = any(answer.needs_review for answer in screening_answers)

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

    artifacts.append(_write_text(cv_md_path, cv_md))
    artifacts.append(_write_text(cv_tex_path, cv_tex))
    copy_latex_assets(config.profiles_dir, out_dir)
    artifacts.append(_write_text(cv_html_path, cv_html))
    fallback_cv_pdf = (config.profiles_dir / "CV.pdf") if config.profiles_dir else None  # type: ignore[operator]
    cv_pdf_artifact, latex_warning = _write_cv_pdf(cv_md, cv_tex_path, cv_pdf_path, fallback_cv_pdf)
    artifacts.append(cv_pdf_artifact)
    artifacts.append(_write_text(letter_md_path, letter_md))
    artifacts.append(_write_text(letter_html_path, letter_html))
    artifacts.append(_write_pdf(letter_md, letter_pdf_path, "cover_letter_pdf", "Cover Letter"))

    risk_flags = sorted(set(job.risk_flags + filter_result.risk_flags + (["screening_question_needs_manual_review"] if needs_screening_review else [])))
    if latex_warning:
        artifacts.append(_write_text(out_dir / "latex_warning.txt", latex_warning))
    temp_packet_id = f"pkt_{job.id[:8]}_v{next_version}"
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
        cover_letter_pdf_path=str(letter_pdf_path),
        qa_answers=qa_answers,
        assistant_page_html=assistant_html,
    )
    # Rewrite assistant with final packet ID in case a custom ID strategy changes later.
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
    packet = generate_packet_for_job(config, job.id, force=force)
    return job, packet, True
