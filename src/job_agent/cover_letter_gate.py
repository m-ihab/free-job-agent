"""Cover-letter gating and on-demand generation."""
from __future__ import annotations

from pathlib import Path

from job_agent.config import AppConfig
from job_agent.db.database import Database
from job_agent.generator.cover_letter import generate_cover_letter
from job_agent.hashutil import sha256_file
from job_agent.renderer.html_render import render_html
from job_agent.renderer.latex_render import _detect_contract_family
from job_agent.renderer.pdf_render import render_pdf
from job_agent.schemas.job import JobListing
from job_agent.schemas.packet import ApplicationPacket, DocumentArtifact
from job_agent.validators import load_profile_bundle


def should_generate_cover_letter(job: JobListing, score: int | float | None, config: AppConfig) -> bool:
    if score is not None and float(score) >= float(config.cover_letter_auto_threshold):
        return True
    contexts = {item.casefold() for item in (config.cover_letter_always_contexts or [])}
    contract = _detect_contract_family(job)
    if contract in contexts:
        return True
    text = " ".join([job.title, job.company, job.source, job.description, job.raw_text]).casefold()
    if "bank" in contexts and _has_bank_context(text):
        return True
    if "formal_fr" in contexts and _has_formal_french_context(text):
        return True
    return False


def generate_cover_letter_on_demand(config: AppConfig, job_id: str) -> ApplicationPacket:
    db = Database(config.db_path)  # type: ignore[arg-type]
    db.initialize()
    job = db.resolve_job(job_id)
    if not job:
        raise ValueError(f"Job not found: {job_id}")
    packets = db.get_packets_for_job(job.id)
    if not packets:
        raise ValueError("Generate a packet before generating an on-demand cover letter.")
    packet = packets[0]
    profile, master_cv, _qa = load_profile_bundle(config)
    letter_md = generate_cover_letter(job, master_cv, profile)
    out_dir = _packet_output_dir(packet, config, job)
    md_path = out_dir / "cover_letter.md"
    html_path = out_dir / "cover_letter.html"
    pdf_path = out_dir / "cover_letter.pdf"
    md_path.write_text(letter_md, encoding="utf-8")
    letter_html = render_html(letter_md, title=f"Cover Letter - {job.title}")
    html_path.write_text(letter_html, encoding="utf-8")
    render_pdf(letter_md, pdf_path, title="Cover Letter")
    packet.cover_letter_md = letter_md
    packet.cover_letter_html = letter_html
    packet.cover_letter_pdf_path = str(pdf_path)
    packet.artifacts = _upsert_artifacts(
        packet.artifacts,
        [
            DocumentArtifact(kind="cover_letter_markdown", path=str(md_path), sha256=sha256_file(md_path)),
            DocumentArtifact(kind="cover_letter_html", path=str(html_path), sha256=sha256_file(html_path)),
            DocumentArtifact(kind="cover_letter_pdf", path=str(pdf_path), sha256=sha256_file(pdf_path)),
        ],
    )
    db.save_packet(packet)
    db.log_event(job.id, "COVER_LETTER_ON_DEMAND", {"packet_id": packet.id}, packet_id=packet.id)
    return packet


def _packet_output_dir(packet: ApplicationPacket, config: AppConfig, job: JobListing) -> Path:
    for artifact in packet.artifacts:
        path = Path(artifact.path)
        if path.name in {"cv.md", "assistant.html"}:
            path.parent.mkdir(parents=True, exist_ok=True)
            return path.parent
    root = config.outputs_dir or (config.data_dir / "outputs")
    safe_company = job.company[:24].replace("/", "-").replace("\\", "-")
    out_dir = root / f"{safe_company}_{job.id[:8]}" / f"packet_v{packet.version}"
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir


def _upsert_artifacts(existing: list[DocumentArtifact], replacements: list[DocumentArtifact]) -> list[DocumentArtifact]:
    replacement_kinds = {item.kind for item in replacements}
    kept = [item for item in existing if item.kind not in replacement_kinds]
    return [*kept, *replacements]


def _has_bank_context(text: str) -> bool:
    needles = ("bank", "banque", "bnp", "société générale", "societe generale", "crédit agricole", "credit agricole", "natixis")
    return any(needle in text for needle in needles)


def _has_formal_french_context(text: str) -> bool:
    needles = ("lettre de motivation", "candidature", "stage", "alternance", "apprentissage")
    return any(needle in text for needle in needles)
