"""Local referral/contact matching for warm-path outreach."""
from __future__ import annotations

from dataclasses import dataclass
import re
import sqlite3

from job_agent.config import AppConfig
from job_agent.db.database import Database
from job_agent.schemas.job import JobListing


@dataclass(frozen=True)
class Contact:
    name: str
    company: str = ""
    role: str = ""
    relationship: str = ""
    shared_school: str = ""
    source: str = "manual"
    notes: str = ""
    id: int | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "name": self.name,
            "company": self.company,
            "role": self.role,
            "relationship": self.relationship,
            "shared_school": self.shared_school,
            "source": self.source,
            "notes": self.notes,
        }


@dataclass(frozen=True)
class WarmPath:
    contact: Contact
    score: int
    reasons: list[str]

    def to_dict(self) -> dict[str, object]:
        return {"contact": self.contact.to_dict(), "score": self.score, "reasons": self.reasons}


def import_contacts(config: AppConfig, contacts: list[Contact]) -> int:
    _ensure_contacts_table(config)
    rows = [_clean_contact(contact) for contact in contacts if contact.name.strip()]
    with _connect(config) as conn:
        for contact in rows:
            conn.execute(
                "INSERT INTO contacts (name, company, role, relationship, shared_school, source, notes) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    contact.name,
                    contact.company,
                    contact.role,
                    contact.relationship,
                    contact.shared_school,
                    contact.source,
                    contact.notes,
                ),
            )
    return len(rows)


def list_contacts(config: AppConfig) -> list[Contact]:
    _ensure_contacts_table(config)
    with _connect(config) as conn:
        rows = conn.execute("SELECT * FROM contacts ORDER BY name COLLATE NOCASE, id").fetchall()
    return [_row_to_contact(row) for row in rows]


def get_contact(config: AppConfig, contact_id: int) -> Contact | None:
    _ensure_contacts_table(config)
    with _connect(config) as conn:
        row = conn.execute("SELECT * FROM contacts WHERE id = ?", (contact_id,)).fetchone()
    return _row_to_contact(row) if row else None


def match_warm_paths(config: AppConfig, job: JobListing, *, limit: int = 5) -> list[WarmPath]:
    matches: list[WarmPath] = []
    for contact in list_contacts(config):
        score, reasons = _score_contact(contact, job)
        if score > 0:
            matches.append(WarmPath(contact, score, reasons))
    matches.sort(key=lambda item: (item.score, item.contact.company, item.contact.name), reverse=True)
    return matches[:limit]


def build_referral_ask(config: AppConfig, job: JobListing, contact: Contact) -> str:
    del config
    first = contact.name.split()[0] if contact.name else "there"
    relationship = f" as a fellow {contact.relationship}" if contact.relationship else ""
    company = job.company or contact.company or "your team"
    role = job.title or "the role"
    return (
        f"Hi {first}, I hope you're doing well. I saw the {role} opportunity at {company} "
        f"and wanted to ask if you might be open to sharing one piece of advice{relationship}. "
        "If it feels appropriate after that, I would also be grateful for a referral or a pointer "
        "to the right recruiter. No pressure either way, and thank you for considering it."
    )


def parse_contacts_payload(items: list[dict]) -> list[Contact]:
    contacts: list[Contact] = []
    for item in items:
        contacts.append(
            Contact(
                name=str(item.get("name") or "").strip(),
                company=str(item.get("company") or "").strip(),
                role=str(item.get("role") or "").strip(),
                relationship=str(item.get("relationship") or "").strip(),
                shared_school=str(item.get("shared_school") or "").strip(),
                source=str(item.get("source") or "manual").strip() or "manual",
                notes=str(item.get("notes") or "").strip(),
            )
        )
    return contacts


def _score_contact(contact: Contact, job: JobListing) -> tuple[int, list[str]]:
    score = 0
    reasons: list[str] = []
    company = _norm(job.company)
    text = _norm(" ".join([contact.company, contact.role, contact.relationship, contact.shared_school, contact.notes]))
    if company and _norm(contact.company) == company:
        score += 100
        reasons.append("company match")
    elif company and company in text:
        score += 55
        reasons.append("company mentioned")
    for token in _tokens(job.title):
        if token in text:
            score += 8
            if "role overlap" not in reasons:
                reasons.append("role overlap")
    if contact.relationship:
        score += 15
        reasons.append(contact.relationship)
    return score, reasons


def _clean_contact(contact: Contact) -> Contact:
    return Contact(
        id=contact.id,
        name=contact.name.strip(),
        company=contact.company.strip(),
        role=contact.role.strip(),
        relationship=contact.relationship.strip(),
        shared_school=contact.shared_school.strip(),
        source=contact.source.strip() or "manual",
        notes=contact.notes.strip(),
    )


def _connect(config: AppConfig) -> sqlite3.Connection:
    if config.db_path is None:
        raise ValueError("Database path is not configured.")
    conn = sqlite3.connect(config.db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_contacts_table(config: AppConfig) -> None:
    db = Database(config.db_path)  # type: ignore[arg-type]
    db.initialize()


def _row_to_contact(row: sqlite3.Row) -> Contact:
    return Contact(
        id=int(row["id"]),
        name=str(row["name"] or ""),
        company=str(row["company"] or ""),
        role=str(row["role"] or ""),
        relationship=str(row["relationship"] or ""),
        shared_school=str(row["shared_school"] or ""),
        source=str(row["source"] or "manual"),
        notes=str(row["notes"] or ""),
    )


def _tokens(value: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9]{3,}", _norm(value)) if token not in {"the", "and", "for"}}


def _norm(value: str | None) -> str:
    return re.sub(r"\s+", " ", (value or "").lower()).strip()
