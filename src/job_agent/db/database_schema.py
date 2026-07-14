"""SQLite schema DDL + additive migrations for the job-agent database.

Kept separate from the CRUD logic so the table definitions live in one place and
``Database.initialize`` stays small.
"""
from __future__ import annotations

SCHEMA_SQL = """
    CREATE TABLE IF NOT EXISTS jobs (
        id TEXT PRIMARY KEY,
        fingerprint TEXT NOT NULL DEFAULT '',
        source TEXT NOT NULL DEFAULT 'manual',
        source_url TEXT,
        raw_text TEXT NOT NULL DEFAULT '',
        title TEXT NOT NULL,
        company TEXT NOT NULL,
        location TEXT,
        remote INTEGER NOT NULL DEFAULT 0,
        work_mode TEXT,
        seniority TEXT,
        job_type TEXT,
        salary_min INTEGER,
        salary_max INTEGER,
        salary_currency TEXT NOT NULL DEFAULT 'USD',
        description TEXT NOT NULL DEFAULT '',
        requirements_json TEXT NOT NULL DEFAULT '[]',
        responsibilities_json TEXT NOT NULL DEFAULT '[]',
        tech_stack_json TEXT NOT NULL DEFAULT '[]',
        benefits_json TEXT NOT NULL DEFAULT '[]',
        languages_json TEXT NOT NULL DEFAULT '[]',
        risk_flags_json TEXT NOT NULL DEFAULT '[]',
        apply_url TEXT,
        posted_date TEXT,
        deadline TEXT,
        status TEXT NOT NULL DEFAULT 'NEW',
        fit_score REAL,
        fit_confidence REAL,
        fit_decision TEXT,
        fit_notes_json TEXT NOT NULL DEFAULT '[]',
        missing_requirements_json TEXT NOT NULL DEFAULT '[]',
        notes TEXT NOT NULL DEFAULT '',
        recruiter_name TEXT,
        recruiter_email TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_fingerprint_unique
        ON jobs(fingerprint) WHERE fingerprint != '';
    CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);

    CREATE TABLE IF NOT EXISTS job_feedback (
        job_id TEXT PRIMARY KEY,
        verdict TEXT NOT NULL CHECK(verdict IN ('up', 'down')),
        created_at TEXT NOT NULL,
        company TEXT NOT NULL DEFAULT '',
        title_keywords_json TEXT NOT NULL DEFAULT '[]',
        source TEXT NOT NULL DEFAULT '',
        FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE
    );
    CREATE INDEX IF NOT EXISTS idx_job_feedback_company ON job_feedback(company);
    CREATE INDEX IF NOT EXISTS idx_job_feedback_source ON job_feedback(source);

    CREATE TABLE IF NOT EXISTS application_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        job_id TEXT,
        event_type TEXT NOT NULL,
        stage TEXT NOT NULL DEFAULT '',
        note TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE
    );
    CREATE INDEX IF NOT EXISTS idx_application_events_job ON application_events(job_id);
    CREATE INDEX IF NOT EXISTS idx_application_events_stage ON application_events(stage);

    CREATE TABLE IF NOT EXISTS followup_tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        job_id TEXT NOT NULL,
        kind TEXT NOT NULL,
        due_at TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'due',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE(job_id, kind, due_at),
        FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE
    );
    CREATE INDEX IF NOT EXISTS idx_followup_tasks_due ON followup_tasks(status, due_at);

    CREATE TABLE IF NOT EXISTS packets (
        id TEXT PRIMARY KEY,
        job_id TEXT NOT NULL,
        job_fingerprint TEXT NOT NULL DEFAULT '',
        version INTEGER NOT NULL DEFAULT 1,
        status TEXT NOT NULL DEFAULT 'DRAFT',
        fit_score REAL,
        fit_confidence REAL,
        fit_decision TEXT,
        fit_notes_json TEXT NOT NULL DEFAULT '[]',
        risk_flags_json TEXT NOT NULL DEFAULT '[]',
        profile_hash TEXT,
        master_cv_hash TEXT,
        qa_profile_hash TEXT,
        artifacts_json TEXT NOT NULL DEFAULT '[]',
        screening_answers_json TEXT NOT NULL DEFAULT '[]',
        tailored_cv_md TEXT NOT NULL DEFAULT '',
        tailored_cv_html TEXT NOT NULL DEFAULT '',
        tailored_cv_pdf_path TEXT,
        cover_letter_md TEXT NOT NULL DEFAULT '',
        cover_letter_html TEXT NOT NULL DEFAULT '',
        cover_letter_pdf_path TEXT,
        qa_answers_json TEXT NOT NULL DEFAULT '{}',
        assistant_page_html TEXT NOT NULL DEFAULT '',
        notes TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE
    );
    CREATE INDEX IF NOT EXISTS idx_packets_job_id ON packets(job_id);
    CREATE INDEX IF NOT EXISTS idx_packets_status ON packets(status);

    CREATE TABLE IF NOT EXISTS events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        job_id TEXT,
        packet_id TEXT,
        event_type TEXT NOT NULL,
        event_data_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL,
        FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE,
        FOREIGN KEY(packet_id) REFERENCES packets(id) ON DELETE SET NULL
    );

    CREATE TABLE IF NOT EXISTS enrichments (
        job_id TEXT PRIMARY KEY,
        payload_json TEXT NOT NULL DEFAULT '{}',
        updated_at TEXT NOT NULL,
        FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS ai_cache (
        job_id TEXT NOT NULL,
        kind TEXT NOT NULL,
        payload_json TEXT NOT NULL DEFAULT '{}',
        model TEXT NOT NULL DEFAULT '',
        updated_at TEXT NOT NULL,
        PRIMARY KEY (job_id, kind),
        FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE
    );
    CREATE INDEX IF NOT EXISTS idx_ai_cache_kind ON ai_cache(kind);

    -- Sources (ATS slugs etc.) that have recently 404'd. The autopilot consults
    -- this to skip dead boards without nagging the user. Auto-expires after
    -- broken_until passes.
    CREATE TABLE IF NOT EXISTS broken_sources (
        source TEXT NOT NULL,
        slug TEXT NOT NULL,
        status_code INTEGER,
        reason TEXT NOT NULL DEFAULT '',
        broken_at TEXT NOT NULL,
        broken_until TEXT NOT NULL,
        PRIMARY KEY (source, slug)
    );

    CREATE TABLE IF NOT EXISTS evidence_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        kind TEXT NOT NULL,
        label TEXT NOT NULL,
        value TEXT NOT NULL DEFAULT '',
        source TEXT NOT NULL,
        source_ref TEXT,
        confidence REAL NOT NULL DEFAULT 1.0,
        created_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_evidence_kind_label ON evidence_items(kind, label);
    CREATE INDEX IF NOT EXISTS idx_evidence_source ON evidence_items(source);

    -- Local semantic vectors for jobs ('job' kind, owner_id = job id) and the
    -- candidate profile ('profile' kind). No FK: vectors may be computed for
    -- jobs before they are tracked, and the profile has no jobs row.
    CREATE TABLE IF NOT EXISTS embeddings (
        owner_id TEXT NOT NULL,
        kind TEXT NOT NULL,
        model TEXT NOT NULL DEFAULT '',
        text_hash TEXT NOT NULL DEFAULT '',
        vector_json TEXT NOT NULL DEFAULT '[]',
        updated_at TEXT NOT NULL,
        PRIMARY KEY (owner_id, kind)
    );
    CREATE INDEX IF NOT EXISTS idx_embeddings_kind ON embeddings(kind);

    -- ATS boards discovered by slug probing (intake/discovery.py). One row per
    -- verified (source, slug); re-discovery refreshes verified_at.
    CREATE TABLE IF NOT EXISTS company_boards (
        company TEXT NOT NULL,
        source TEXT NOT NULL,
        slug TEXT NOT NULL,
        verified_at TEXT NOT NULL,
        PRIMARY KEY (source, slug)
    );
    CREATE INDEX IF NOT EXISTS idx_company_boards_company ON company_boards(company);

    -- STAR(+Reflection) interview stories. Seeded verbatim from master_cv.json
    -- and then user-editable; sync only inserts missing ids.
    CREATE TABLE IF NOT EXISTS stories (
        id TEXT PRIMARY KEY,
        title TEXT NOT NULL DEFAULT '',
        skills_json TEXT NOT NULL DEFAULT '[]',
        situation TEXT NOT NULL DEFAULT '',
        task TEXT NOT NULL DEFAULT '',
        action TEXT NOT NULL DEFAULT '',
        result TEXT NOT NULL DEFAULT '',
        reflection TEXT NOT NULL DEFAULT '',
        source TEXT NOT NULL DEFAULT 'manual',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS contacts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        company TEXT NOT NULL DEFAULT '',
        role TEXT NOT NULL DEFAULT '',
        relationship TEXT NOT NULL DEFAULT '',
        shared_school TEXT NOT NULL DEFAULT '',
        source TEXT NOT NULL DEFAULT 'manual',
        notes TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_contacts_company ON contacts(company);
"""

# Additive column migrations — run after CREATE TABLE so new DBs get the column
# inline and existing DBs get it here. Each is wrapped in try/except by the
# caller since SQLite raises OperationalError on a duplicate column.
MIGRATIONS = [
    "ALTER TABLE jobs ADD COLUMN recruiter_name TEXT",
    "ALTER TABLE jobs ADD COLUMN recruiter_email TEXT",
    "ALTER TABLE jobs ADD COLUMN notes TEXT NOT NULL DEFAULT ''",
]
