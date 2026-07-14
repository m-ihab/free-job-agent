"""SQLite database layer (facade).

``Database`` is composed from focused CRUD mixins so each table family lives in
its own module while the public surface (``from job_agent.db.database import
Database``) and every method name stay exactly as before:
  * :mod:`job_agent.db.database_schema` — table DDL + additive migrations
  * :mod:`job_agent.db.database_jobs` — job rows (``JobsMixin``)
  * :mod:`job_agent.db.database_packets` — packet rows (``PacketsMixin``)
  * :mod:`job_agent.db.database_meta` — events, enrichment, AI cache, broken sources
  * :mod:`job_agent.db.database_conversion` — follow-up tasks and conversion state

This file keeps the connection management + schema bootstrap that the mixins
rely on (``self._connect`` / ``initialize``).
"""
from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

from job_agent.db.database_boards import BoardsMixin
from job_agent.db.database_conversion import ConversionMixin
from job_agent.db.database_embeddings import EmbeddingsMixin
from job_agent.db.database_feedback import FeedbackMixin
from job_agent.db.database_jobs import JobsMixin
from job_agent.db.database_meta import MetaMixin
from job_agent.db.database_packets import PacketsMixin
from job_agent.db.database_schema import MIGRATIONS, SCHEMA_SQL
from job_agent.db.database_stories import StoriesMixin

logger = logging.getLogger(__name__)


class Database(
    JobsMixin,
    PacketsMixin,
    MetaMixin,
    ConversionMixin,
    EmbeddingsMixin,
    StoriesMixin,
    BoardsMixin,
    FeedbackMixin,
):
    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)

    @contextmanager
    def _connect(self) -> Generator[sqlite3.Connection, None, None]:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def initialize(self) -> None:
        """Create all tables and indexes, then run additive column migrations."""
        with self._connect() as conn:
            conn.executescript(SCHEMA_SQL)
            # Additive column migrations — safe to re-run; SQLite raises
            # OperationalError on a duplicate column, which we treat as a no-op.
            for _migration in MIGRATIONS:
                try:
                    conn.execute(_migration)
                except sqlite3.OperationalError:
                    logger.debug("Migration skipped (column already exists): %s", _migration)
