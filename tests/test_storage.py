"""Unit tests for SQLite storage and deduplication."""

from datetime import datetime, timezone
from pathlib import Path
import pytest

from crawler.models import JobRecord, JobStatus
from crawler.storage import JobStorage


@pytest.fixture
def temp_storage(tmp_path: Path):
    db_file = tmp_path / "test_jobs.db"
    return JobStorage(db_file)


def make_sample_job(
    job_id: str = "id-101",
    source: str = "greenhouse:test",
    company: str = "Acme Corp",
    title: str = "Backend Go Engineer",
    fuzzy_key: str = "acme|backend go engineer|remote",
    score: float = 6.0,
) -> JobRecord:
    return JobRecord(
        id=job_id,
        source=source,
        source_job_id="101",
        title=title,
        company=company,
        location="Remote",
        is_remote=True,
        url="https://example.com/job/101",
        description="Write Go microservices.",
        matched_keywords=["Go Engineer", "Golang"],
        score=score,
        fuzzy_key=fuzzy_key,
        status=JobStatus.NEW,
    )


def test_upsert_new_and_exact_dedup(temp_storage: JobStorage):
    job = make_sample_job(job_id="id-101")

    # First insert: is_new should be True
    is_new, saved = temp_storage.upsert_job(job)
    assert is_new is True
    assert saved.status == JobStatus.NEW

    # Mark as APPLIED by user
    temp_storage.update_status(job.id, JobStatus.APPLIED)

    # Re-crawled identical job: should NOT reset status back to NEW
    job_updated = make_sample_job(job_id="id-101", score=7.5)
    is_new2, saved2 = temp_storage.upsert_job(job_updated)
    assert is_new2 is False
    assert saved2.status == JobStatus.APPLIED


def test_fuzzy_deduplication_cross_source(temp_storage: JobStorage):
    job_source_a = make_sample_job(
        job_id="gh-101",
        source="greenhouse:acme",
        fuzzy_key="acme|backend engineer|remote",
    )
    is_new1, _ = temp_storage.upsert_job(job_source_a)
    assert is_new1 is True

    # Same company and title from Lever
    job_source_b = make_sample_job(
        job_id="lv-999",
        source="lever:acme",
        fuzzy_key="acme|backend engineer|remote",
    )
    is_new2, existing = temp_storage.upsert_job(job_source_b)
    # Detected as fuzzy duplicate
    assert is_new2 is False
    assert existing.id == "gh-101"


def test_closed_jobs_marking(temp_storage: JobStorage):
    run_time = datetime.now(timezone.utc)
    job = make_sample_job(job_id="id-closing", source="greenhouse:old")
    temp_storage.upsert_job(job)

    # Mark closed with a cutoff after first_seen_at
    future_time = datetime.now(timezone.utc)
    closed_count = temp_storage.mark_closed_jobs("greenhouse:old", future_time)
    assert closed_count == 1

    fetched = temp_storage.get_job("id-closing")
    assert fetched.status == JobStatus.CLOSED


def test_export_csv_and_json(temp_storage: JobStorage, tmp_path: Path):
    job = make_sample_job(job_id="id-export")
    temp_storage.upsert_job(job)

    csv_out = tmp_path / "out.csv"
    json_out = tmp_path / "out.json"

    assert temp_storage.export_csv(csv_out) == 1
    assert temp_storage.export_json(json_out) == 1
    assert csv_out.exists()
    assert json_out.exists()
