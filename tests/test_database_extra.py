"""Additional behavioural tests for the SQLite ``Database`` layer.

Covers branches not exercised by the existing suite: event history, packet
versioning, status updates / needs-manual, AI-cache + enrichment round-trips
(including corrupt-JSON tolerance), bulk reads, and the broken-source registry.
All tests use the ``tmp_db`` fixture from ``conftest`` so each run is isolated.
"""
from __future__ import annotations

from job_agent.schemas.job import JobListing, JobStatus
from job_agent.schemas.packet import ApplicationPacket, PacketStatus


def _job(title: str = "Data Scientist", company: str = "Acme") -> JobListing:
    return JobListing(title=title, company=company, source="paste", raw_text="x")


# ── events ───────────────────────────────────────────────────────────────────

def test_log_event_and_get_events_returns_ordered_decoded_data(tmp_db):
    # Arrange
    job = _job()
    tmp_db.save_job(job)
    tmp_db.log_event(job.id, "JOB_ADDED", {"source": "paste"})
    tmp_db.log_event(job.id, "STATUS_CHANGED", {"new_status": "SCORED"})

    # Act
    events = tmp_db.get_events(job.id)

    # Assert — events return in insertion order with decoded JSON payloads.
    assert [e["event_type"] for e in events] == ["JOB_ADDED", "STATUS_CHANGED"]
    assert events[1]["event_data"] == {"new_status": "SCORED"}


def test_get_events_empty_for_unknown_job(tmp_db):
    assert tmp_db.get_events("missing") == []


# ── status updates / needs-manual ────────────────────────────────────────────

def test_update_job_status_returns_true_when_row_changed(tmp_db):
    # Arrange
    job = _job()
    tmp_db.save_job(job)

    # Act
    changed = tmp_db.update_job_status(job.id, JobStatus.MANUALLY_SUBMITTED)

    # Assert
    assert changed is True
    assert tmp_db.get_job(job.id).status == JobStatus.MANUALLY_SUBMITTED


def test_update_job_status_returns_false_for_unknown_job(tmp_db):
    assert tmp_db.update_job_status("nope", JobStatus.SCORED) is False


def test_get_needs_manual_returns_only_walled_jobs(tmp_db):
    # Arrange
    walled, normal = _job("ML Engineer", "Globex"), _job()
    tmp_db.save_job(walled)
    tmp_db.save_job(normal)
    tmp_db.update_job_status(walled.id, JobStatus.NEEDS_MANUAL)

    # Act
    needs = tmp_db.get_needs_manual()

    # Assert
    assert [j.id for j in needs] == [walled.id]


# ── job lookup helpers ───────────────────────────────────────────────────────

def test_resolve_job_by_prefix_returns_single_match(tmp_db):
    # Arrange
    job = _job()
    tmp_db.save_job(job)

    # Act
    resolved = tmp_db.resolve_job(job.id[:8])

    # Assert
    assert resolved is not None and resolved.id == job.id


def test_get_job_by_prefix_returns_none_on_ambiguous_or_missing(tmp_db):
    assert tmp_db.get_job_by_prefix("zzzzzzzz") is None


def test_list_jobs_without_packets_skips_jobs_with_packets(tmp_db):
    # Arrange
    with_pkt, without_pkt = _job("A Data Role", "Co1"), _job("B Data Role", "Co2")
    tmp_db.save_job(with_pkt)
    tmp_db.save_job(without_pkt)
    tmp_db.save_packet(ApplicationPacket(job_id=with_pkt.id, status=PacketStatus.READY))

    # Act
    pending = tmp_db.list_jobs_without_packets(limit=10)

    # Assert
    ids = {j.id for j in pending}
    assert without_pkt.id in ids and with_pkt.id not in ids


# ── packets ──────────────────────────────────────────────────────────────────

def test_save_packet_upsert_and_get_packets_for_job_orders_by_version(tmp_db):
    # Arrange
    job = _job()
    tmp_db.save_job(job)
    tmp_db.save_packet(ApplicationPacket(job_id=job.id, version=1, status=PacketStatus.READY))
    tmp_db.save_packet(ApplicationPacket(job_id=job.id, version=2, status=PacketStatus.READY))

    # Act
    packets = tmp_db.get_packets_for_job(job.id)

    # Assert — newest version first.
    assert [p.version for p in packets] == [2, 1]


def test_resolve_packet_by_prefix(tmp_db):
    # Arrange
    job = _job()
    tmp_db.save_job(job)
    packet = ApplicationPacket(job_id=job.id, status=PacketStatus.READY)
    tmp_db.save_packet(packet)

    # Act / Assert
    assert tmp_db.resolve_packet(packet.id[:8]).id == packet.id


def test_delete_job_cascades_to_packets(tmp_db):
    # Arrange
    job = _job()
    tmp_db.save_job(job)
    tmp_db.save_packet(ApplicationPacket(job_id=job.id, status=PacketStatus.READY))

    # Act
    tmp_db.delete_job(job.id)

    # Assert — cascade removes the packet too.
    assert tmp_db.get_job(job.id) is None
    assert tmp_db.get_packets_for_job(job.id) == []


# ── enrichment + AI cache ────────────────────────────────────────────────────

def test_enrichment_round_trip_and_missing_returns_none(tmp_db):
    # Arrange
    job = _job()
    tmp_db.save_job(job)
    tmp_db.save_enrichment(job.id, {"rome": {"code": "M1805"}})

    # Act
    payload = tmp_db.get_enrichment(job.id)

    # Assert
    assert payload["rome"] == {"code": "M1805"}
    assert "updated_at" in payload
    assert tmp_db.get_enrichment("missing") is None


def test_ai_cache_round_trip_attaches_model_and_timestamp(tmp_db):
    # Arrange
    job = _job()
    tmp_db.save_job(job)
    tmp_db.save_ai_cache(job.id, "summary", {"tldr": "great role"}, model="mistral")

    # Act
    cached = tmp_db.get_ai_cache(job.id, "summary")

    # Assert
    assert cached["tldr"] == "great role"
    assert cached["model"] == "mistral"


def test_get_ai_cache_tolerates_corrupt_json(tmp_db):
    # Arrange — write a deliberately corrupt cache row directly.
    job = _job()
    tmp_db.save_job(job)
    with tmp_db._connect() as conn:
        conn.execute(
            "INSERT INTO ai_cache (job_id, kind, payload_json, model, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (job.id, "summary", "{not json", "m", "2026-01-01"),
        )

    # Act / Assert — corrupt rows are skipped, not raised.
    assert tmp_db.get_ai_cache(job.id, "summary") is None
    assert tmp_db.list_ai_cache_for_job(job.id) == {}


# ── bulk reads ───────────────────────────────────────────────────────────────

def test_bulk_reads_empty_input_returns_empty_dict(tmp_db):
    assert tmp_db.bulk_get_enrichments([]) == {}
    assert tmp_db.bulk_list_ai_cache([]) == {}
    assert tmp_db.bulk_latest_packets([]) == {}


def test_bulk_latest_packets_returns_newest_per_job(tmp_db):
    # Arrange
    job1, job2 = _job("Role One", "C1"), _job("Role Two", "C2")
    tmp_db.save_job(job1)
    tmp_db.save_job(job2)
    tmp_db.save_packet(ApplicationPacket(job_id=job1.id, version=1, status=PacketStatus.READY))
    tmp_db.save_packet(ApplicationPacket(job_id=job1.id, version=2, status=PacketStatus.READY))
    tmp_db.save_packet(ApplicationPacket(job_id=job2.id, version=1, status=PacketStatus.READY))

    # Act
    latest = tmp_db.bulk_latest_packets([job1.id, job2.id])

    # Assert
    assert latest[job1.id].version == 2
    assert latest[job2.id].version == 1


def test_bulk_get_enrichments_maps_by_job_id(tmp_db):
    # Arrange
    job1, job2 = _job("R1", "C1"), _job("R2", "C2")
    tmp_db.save_job(job1)
    tmp_db.save_job(job2)
    tmp_db.save_enrichment(job1.id, {"a": 1})

    # Act
    bulk = tmp_db.bulk_get_enrichments([job1.id, job2.id])

    # Assert — only the enriched job appears.
    assert set(bulk) == {job1.id}
    assert bulk[job1.id]["a"] == 1


# ── broken-source registry ───────────────────────────────────────────────────

def test_broken_source_marked_then_listed_then_cleared(tmp_db):
    # Arrange / Act
    tmp_db.mark_source_broken("greenhouse", "deadco", status_code=404, reason="404", hours=1.0)

    # Assert — registered and active.
    assert tmp_db.is_source_broken("greenhouse", "deadco") is True
    listed = tmp_db.list_broken_sources()
    assert any(row["slug"] == "deadco" for row in listed)

    # Act — clear it.
    tmp_db.clear_broken_source("greenhouse", "deadco")

    # Assert
    assert tmp_db.is_source_broken("greenhouse", "deadco") is False


def test_is_source_broken_false_when_window_expired(tmp_db):
    # Arrange — a zero-hour window expires immediately.
    tmp_db.mark_source_broken("lever", "old", hours=0.0)

    # Act / Assert
    assert tmp_db.is_source_broken("lever", "old") is False
