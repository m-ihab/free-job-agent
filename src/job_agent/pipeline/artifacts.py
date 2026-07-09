"""Artifact writers/renderers for packet generation (split from pipeline.py, R1 2026-07-09).

Everything here is a leaf helper: given inputs, write files and return
DocumentArtifact records. Fail-soft helpers log and degrade instead of raising.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from job_agent import embeddings, story_bank
from job_agent.config import AppConfig
from job_agent.evidence import EvidenceStore
from job_agent.generator.evaluation import evaluate_job, salary_comparables
from job_agent.generator.preflight import run_preflight
from job_agent.generator.proof_pack import render_proof_pack_markdown
from job_agent.hashutil import sha256_file
from job_agent.renderer.latex_render import (
    LatexCompileError,
    compact_cv_source,
    compile_latex_to_pdf,
    count_pdf_pages,
)
from job_agent.renderer.pdf_render import render_pdf
from job_agent.schemas.candidate import CandidateProfile
from job_agent.schemas.job import JobListing
from job_agent.schemas.packet import ApplicationPacket, DocumentArtifact
from job_agent.tracker import ApplicationTracker

logger = logging.getLogger(__name__)


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
        logger.debug("One-page CV fitting skipped", exc_info=True)
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


def _write_preflight_artifact(
    config: AppConfig,
    job: JobListing,
    profile: CandidateProfile,
    packet: ApplicationPacket,
    out_dir: Path,
) -> DocumentArtifact | None:
    try:
        evidence = EvidenceStore.load(config)
        if not evidence.all():
            evidence.rebuild(config)
        result = run_preflight(job, profile, evidence, config, packet)
        path = out_dir / "preflight.json"
        path.write_text(json.dumps(result.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        return DocumentArtifact(kind="preflight_json", path=str(path), sha256=sha256_file(path))
    except Exception as exc:
        logger.warning("Could not write preflight artifact for job %s: %s", job.id, exc)
        return None


def _story_bank_section(tracker: ApplicationTracker, master_cv, job: JobListing) -> str:
    """Seed the persistent story bank from the CV, then render the most relevant
    STAR stories for this job. Fail-soft: packet generation never depends on it."""
    try:
        story_bank.sync_story_bank(tracker.db, master_cv)
        stories = [story_bank.Story.from_row(row) for row in tracker.db.list_stories()]
        picked = story_bank.relevant_stories(job, stories, limit=5)
        return "\n" + story_bank.render_story_bank_markdown(job, picked, job.missing_requirements)
    except Exception:
        logger.warning("Story bank section skipped for job %s", job.id, exc_info=True)
        return ""


def _write_evaluation_artifacts(
    config: AppConfig,
    job: JobListing,
    profile: CandidateProfile,
    packet: ApplicationPacket,
    out_dir: Path,
    tracker: ApplicationTracker,
) -> list[DocumentArtifact]:
    """Write evaluation.md + evaluation.json (A-F rubric + local salary context)."""
    try:
        preflight = None
        try:
            evidence = EvidenceStore.load(config)
            if not evidence.all():
                evidence.rebuild(config)
            preflight = run_preflight(job, profile, evidence, config, packet)
        except Exception:
            logger.debug("Evaluation runs without preflight coverage", exc_info=True)
        semantic = None
        try:
            semantic = embeddings.semantic_similarity(job, profile, tracker.db)
        except Exception:
            logger.debug("Semantic similarity skipped in evaluation artifacts", exc_info=True)
            semantic = None
        evaluation = evaluate_job(job, profile, preflight=preflight, semantic_score=semantic, config=config)
        salary_lines = salary_comparables(tracker.db, job)
        md_path = out_dir / "evaluation.md"
        md_path.write_text(evaluation.to_markdown(salary_lines), encoding="utf-8")
        json_path = out_dir / "evaluation.json"
        payload = {**evaluation.to_dict(), "salary_context": salary_lines}
        json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return [
            DocumentArtifact(kind="evaluation_markdown", path=str(md_path), sha256=sha256_file(md_path)),
            DocumentArtifact(kind="evaluation_json", path=str(json_path), sha256=sha256_file(json_path)),
        ]
    except Exception as exc:
        logger.warning("Could not write evaluation artifacts for job %s: %s", job.id, exc)
        return []


def _write_proof_pack_artifact(
    config: AppConfig,
    job: JobListing,
    profile: CandidateProfile,
    packet: ApplicationPacket,
    out_dir: Path,
) -> DocumentArtifact | None:
    try:
        evidence = EvidenceStore.load(config)
        if not evidence.all():
            evidence.rebuild(config)
        preflight = run_preflight(job, profile, evidence, config, packet)
        path = out_dir / "proof_pack.md"
        path.write_text(render_proof_pack_markdown(job, preflight), encoding="utf-8")
        return DocumentArtifact(kind="proof_pack_markdown", path=str(path), sha256=sha256_file(path))
    except Exception as exc:
        logger.warning("Could not write proof pack artifact for job %s: %s", job.id, exc)
        return None


def _write_ats_check_artifacts(
    job: JobListing,
    cv_md: str,
    cv_pdf_path: Path,
    out_dir: Path,
) -> list[DocumentArtifact]:
    """Write ats_check.md + ats_check.json — the G1 local ATS-parse self-check.

    Re-reads the rendered CV PDF the way a naive ATS would and reports keyword
    readability + render-loss. Fail-soft: this diagnostic must never block packet
    generation, so any error degrades to "no artifact" with a warning.
    """
    from job_agent.generator.ats_selfcheck import run_ats_selfcheck

    try:
        if not cv_pdf_path.exists():
            return []
        report = run_ats_selfcheck(job, cv_md, cv_pdf_path)
        md_path = out_dir / "ats_check.md"
        md_path.write_text(report.to_markdown(), encoding="utf-8")
        json_path = out_dir / "ats_check.json"
        json_path.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        return [
            DocumentArtifact(kind="ats_check_markdown", path=str(md_path), sha256=sha256_file(md_path)),
            DocumentArtifact(kind="ats_check_json", path=str(json_path), sha256=sha256_file(json_path)),
        ]
    except Exception as exc:
        logger.warning("Could not write ATS self-check artifacts for job %s: %s", job.id, exc)
        return []
