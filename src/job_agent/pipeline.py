"""End-to-end orchestration helpers used by the CLI."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from job_agent.ai_agent import (
    analyze_fit,
    classify_job,
    summarize_job,
)
from job_agent.config import AppConfig
from job_agent.db.database import Database
from job_agent.filters import FilterConfig, apply_filters
from job_agent.fingerprint import set_fingerprint
from job_agent.generator.cover_letter import generate_cover_letter
from job_agent.generator.cv import tailor_cv
from job_agent.generator.interview_prep import generate_interview_prep
from job_agent.generator.outreach_email import generate_outreach_email
from job_agent.generator.qa import build_screening_answers_for_job, screening_answers_to_dict
from job_agent.hashutil import sha256_file, sha256_json
from job_agent.intake.file import ingest_file
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


def _render_ai_brief(job, fit_analysis) -> str:
    lines = [
        f"# AI Fit Brief - {job.title} at {job.company}",
        "",
        f"Verdict: **{fit_analysis.verdict}**",
        f"AI score: **{fit_analysis.score}/100**",
        f"Confidence: **{int(fit_analysis.confidence * 100)}%**",
        "",
        "## Summary",
        fit_analysis.summary,
        "",
        "## Strengths",
    ]
    lines.extend(f"- {item}" for item in fit_analysis.strengths or ["None."])
    lines.extend(["", "## Gaps"])
    lines.extend(f"- {item}" for item in fit_analysis.gaps or ["None."])
    lines.extend(["", "## Suggested Emphasis"])
    lines.extend(f"- {item}" for item in fit_analysis.suggested_emphasis or ["None."])
    lines.append("")
    return "\n".join(lines)


def _render_external_agent_prompt(job, packet_id: str, artifacts: list[DocumentArtifact]) -> str:
    artifact_lines = "\n".join(f"- {artifact.kind}: {artifact.path}" for artifact in artifacts)
    return f"""# External Agent Review Prompt

You are reviewing an application packet before manual submission.

Strict rules:
- Do not invent candidate facts, metrics, dates, certifications, legal/visa claims, salary expectations, or availability.
- Do not submit the application or automate a login.
- Only suggest improvements grounded in the listed files and the job posting.
- Flag any missing factual answer that should be added to `profiles/master_qa_profile.json`.

Packet: {packet_id}
Job: {job.title} at {job.company}
Location: {job.location or "-"}
Apply URL: {job.apply_url or job.source_url or "-"}

Files to review:
{artifact_lines}

Review tasks:
1. Check whether the CV PDF and `cv.tex` preserve the master CV layout and photo.
2. Check whether the role-specific summary is specific but factual.
3. Check whether the cover letter is concise, relevant, and grounded.
4. Identify missing keywords that are present in the candidate facts and safe to emphasize.
5. Return a short prioritized list of edits, with file names and exact text suggestions.
"""


def _enforce_single_page(cv_tex_path: Path, cv_pdf_path: Path) -> None:
    """Recompile with escalating compaction until the tailored CV fits one page.

    The master template is one page, but tailoring pulls richer experience and
    project content from ``master_cv.json`` and can spill onto a second page.
    This keeps every generated packet to a single page. Best-effort: it never
    raises, and on any compaction-compile failure it restores the original tex.
    """
    try:
        pages = count_pdf_pages(cv_pdf_path)
        if not pages or pages <= 1:
            return
        original = cv_tex_path.read_text(encoding="utf-8")
        if r"\documentclass" not in original or "moderncv" not in original:
            return
        for level in (1, 2):
            compacted = compact_cv_source(original, level)
            if compacted == original:
                continue
            cv_tex_path.write_text(compacted, encoding="utf-8")
            try:
                compile_latex_to_pdf(cv_tex_path, cv_pdf_path)
            except LatexCompileError:
                cv_tex_path.write_text(original, encoding="utf-8")
                compile_latex_to_pdf(cv_tex_path, cv_pdf_path)
                return
            if (count_pdf_pages(cv_pdf_path) or 2) <= 1:
                return
    except Exception:
        # One-page fitting is a nicety; never let it break packet generation.
        return


def _write_cv_pdf(cv_md: str, cv_tex_path: Path, cv_pdf_path: Path, master_cv_pdf: Path | None = None) -> tuple[DocumentArtifact, str | None]:
    try:
        compile_latex_to_pdf(cv_tex_path, cv_pdf_path)
        _enforce_single_page(cv_tex_path, cv_pdf_path)
        return DocumentArtifact(kind="cv_pdf", path=str(cv_pdf_path), sha256=sha256_file(cv_pdf_path)), None
    except LatexCompileError as exc:
        # If the user has a master CV.pdf next to main.tex, prefer copying it
        # over generating an ugly Markdown PDF. The copy keeps the user's
        # professional design even though it isn't role-tailored.
        if master_cv_pdf is not None and master_cv_pdf.exists():
            import shutil as _sh
            cv_pdf_path.parent.mkdir(parents=True, exist_ok=True)
            _sh.copyfile(master_cv_pdf, cv_pdf_path)
            warning = (
                f"LaTeX CV PDF fallback used: copied {master_cv_pdf.name} because cv.tex could not be compiled. "
                "This PDF preserves your main.tex visual format but is NOT role-tailored. "
                "Install MiKTeX/TeX Live or fix the compiler path and rerun with --force for a tailored LaTeX PDF. "
                f"Compiler issue: {exc}"
            )
            return (
                DocumentArtifact(kind="cv_pdf", path=str(cv_pdf_path), sha256=sha256_file(cv_pdf_path)),
                warning,
            )
        render_pdf(cv_md, cv_pdf_path, title="Tailored CV")
        warning = (
            "LaTeX CV PDF fallback used: generated a role-tailored plain PDF because cv.tex could not be compiled. "
            "Place a master CV.pdf in your profiles directory to get a design-preserving fallback. "
            "Or set JOB_AGENT_LATEX_COMPILER / install pdflatex, then regenerate. "
            f"Compiler issue: {exc}"
        )
        return (
            DocumentArtifact(kind="cv_pdf", path=str(cv_pdf_path), sha256=sha256_file(cv_pdf_path)),
            warning,
        )


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
    tracker = _tracker(config)
    job = tracker.get_job(job_id)
    if not job:
        raise ValueError(f"Job not found: {job_id}")
    if profile_bundle is not None:
        profile, master_cv, qa_profile = profile_bundle
    else:
        profile, master_cv, qa_profile = load_profile_bundle(config)

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
        model_name = ""

    # Run AI calls in parallel — analyze_fit + classify + summarize concurrently.
    fit_analysis = None
    classification = None
    tldr = None
    with ThreadPoolExecutor(max_workers=3, thread_name_prefix="ai") as ai_pool:
        f_fit = ai_pool.submit(analyze_fit, job, master_cv, profile, polish_opts)
        f_cls = ai_pool.submit(classify_job, job, polish_opts)
        f_tldr = ai_pool.submit(summarize_job, job, polish_opts)
        try:
            fit_analysis = f_fit.result()
        except Exception:
            fit_analysis = None
        try:
            classification = f_cls.result()
        except Exception:
            classification = None
        try:
            tldr = f_tldr.result()
        except Exception:
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
    letter_md = generate_cover_letter(job, master_cv, profile)
    screening_answers = build_screening_answers_for_job(job, qa_profile)
    qa_answers = screening_answers_to_dict(screening_answers)
    needs_screening_review = any(answer.needs_review for answer in screening_answers)

    # In fast mode (autopilot background): skip heavy HTML renders and LaTeX
    # compilation so a 5-packet batch finishes in ~15 s instead of ~3 min.
    if not fast_mode:
        outreach_md = generate_outreach_email(job, master_cv, profile)
        interview_md = generate_interview_prep(job, master_cv, profile)
        cv_html = render_html(cv_md, title=f"CV - {job.title}")
        letter_html = render_html(letter_md, title=f"Cover Letter - {job.title}")
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
        latex_warning = (
            "Fast-mode PDF: generated with reportlab (not LaTeX). "
            "Open the packet and click 'Regenerate PDF' for the full LaTeX-compiled version."
        )
        artifacts.append(cv_pdf_artifact)
    else:
        artifacts.append(_write_text(cv_html_path, cv_html))
        cv_pdf_artifact, latex_warning = _write_cv_pdf(cv_md, cv_tex_path, cv_pdf_path, master_cv_pdf=master_cv_pdf)
        artifacts.append(cv_pdf_artifact)

    artifacts.append(_write_text(letter_md_path, letter_md))

    if not fast_mode:
        artifacts.append(_write_text(letter_html_path, letter_html))
        artifacts.append(_write_pdf(letter_md, letter_pdf_path, "cover_letter_pdf", "Cover Letter"))
        artifacts.append(_write_text(out_dir / "outreach_email.md", outreach_md))
        artifacts.append(_write_text(out_dir / "interview_prep.md", interview_md))

    if fit_analysis is not None:
        artifacts.append(_write_text(out_dir / "ai_fit_brief.md", _render_ai_brief(job, fit_analysis)))

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
        cover_letter_pdf_path=str(letter_pdf_path) if not fast_mode else "",
        qa_answers=qa_answers,
        assistant_page_html=assistant_html,
    )
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
    packet = generate_packet_for_job(config, job.id, force=force)
    return job, packet, True
