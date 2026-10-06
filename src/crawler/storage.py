"""SQLite storage engine and deduplication for Job Crawler."""

from __future__ import annotations

import csv
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from crawler.models import JobRecord, JobStatus


class JobStorage:
    """Manages SQLite storage, queries, and deduplication for jobs."""

    def __init__(self, db_path: str | Path | None = None):
        if db_path is None:
            db_path = Path(__file__).resolve().parent.parent.parent / "data" / "jobs.db"
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        """Create tables and indexes if they do not exist."""
        with self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    source_job_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    company TEXT NOT NULL,
                    location TEXT NOT NULL,
                    is_remote INTEGER NOT NULL DEFAULT 0,
                    url TEXT NOT NULL,
                    description TEXT NOT NULL,
                    matched_keywords TEXT NOT NULL,
                    score REAL NOT NULL DEFAULT 0.0,
                    fuzzy_key TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'new',
                    posted_at TEXT,
                    first_seen_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_score ON jobs(score)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_fuzzy ON jobs(fuzzy_key)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_company ON jobs(company)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_last_seen ON jobs(last_seen_at)")

    def upsert_job(self, job: JobRecord) -> tuple[bool, JobRecord]:
        """
        Upsert a job into the database.
        Returns (is_new, updated_or_existing_record).
        Handles both exact ID deduplication and fuzzy key deduplication.
        """
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            # 1. Exact duplicate check by ID
            cursor = conn.execute("SELECT * FROM jobs WHERE id = ?", (job.id,))
            row = cursor.fetchone()
            if row:
                # Existing job: update last_seen_at, score, matched_keywords, but PRESERVE user status
                existing_status = row["status"]
                conn.execute(
                    """
                    UPDATE jobs
                    SET last_seen_at = ?,
                        score = ?,
                        matched_keywords = ?,
                        url = ?,
                        location = ?,
                        is_remote = ?
                    WHERE id = ?
                    """,
                    (
                        now_iso,
                        job.score,
                        json.dumps(job.matched_keywords),
                        job.url,
                        job.location,
                        1 if job.is_remote else 0,
                        job.id,
                    ),
                )
                updated_job = self._row_to_record(row)
                updated_job.last_seen_at = datetime.fromisoformat(now_iso)
                updated_job.status = JobStatus(existing_status)
                return False, updated_job

            # 2. Fuzzy duplicate check: same company & title already exists
            cursor = conn.execute(
                "SELECT * FROM jobs WHERE fuzzy_key = ? AND status != 'closed' LIMIT 1",
                (job.fuzzy_key,),
            )
            fuzzy_row = cursor.fetchone()
            if fuzzy_row:
                # Job found from another source or slightly different URL.
                # Update last_seen_at of the existing record to keep active
                conn.execute(
                    "UPDATE jobs SET last_seen_at = ? WHERE id = ?",
                    (now_iso, fuzzy_row["id"]),
                )
                existing_job = self._row_to_record(fuzzy_row)
                return False, existing_job

            # 3. Completely new job: insert
            conn.execute(
                """
                INSERT INTO jobs (
                    id, source, source_job_id, title, company, location, is_remote,
                    url, description, matched_keywords, score, fuzzy_key, status,
                    posted_at, first_seen_at, last_seen_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job.id,
                    job.source,
                    job.source_job_id,
                    job.title,
                    job.company,
                    job.location,
                    1 if job.is_remote else 0,
                    job.url,
                    job.description,
                    json.dumps(job.matched_keywords),
                    job.score,
                    job.fuzzy_key,
                    job.status.value,
                    job.posted_at.isoformat() if job.posted_at else None,
                    job.first_seen_at.isoformat(),
                    job.last_seen_at.isoformat(),
                ),
            )
            return True, job

    def get_job(self, job_id: str) -> Optional[JobRecord]:
        """Fetch a single job by ID or partial ID prefix."""
        with self._get_connection() as conn:
            cursor = conn.execute("SELECT * FROM jobs WHERE id = ? OR id LIKE ? LIMIT 1", (job_id, f"{job_id}%"))
            row = cursor.fetchone()
            return self._row_to_record(row) if row else None

    def list_jobs(
        self,
        status: Optional[str] = None,
        min_score: Optional[float] = None,
        search_query: Optional[str] = None,
        source: Optional[str] = None,
        remote_only: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> list[JobRecord]:
        """Query jobs with flexible filtering and score ranking."""
        clauses = []
        params: list[Any] = []

        if status:
            clauses.append("status = ?")
            params.append(status)
        if min_score is not None:
            clauses.append("score >= ?")
            params.append(min_score)
        if source:
            clauses.append("source = ?")
            params.append(source)
        if remote_only:
            clauses.append("is_remote = 1")
        if search_query:
            clauses.append("(title LIKE ? OR company LIKE ? OR matched_keywords LIKE ?)")
            like_pattern = f"%{search_query}%"
            params.extend([like_pattern, like_pattern, like_pattern])

        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        query = f"""
            SELECT * FROM jobs
            {where_sql}
            ORDER BY score DESC, first_seen_at DESC
            LIMIT ? OFFSET ?
        """
        params.extend([limit, offset])

        with self._get_connection() as conn:
            cursor = conn.execute(query, params)
            return [self._row_to_record(row) for row in cursor.fetchall()]

    def update_status(self, job_id: str, new_status: JobStatus) -> bool:
        """Update job status (e.g. 'applied', 'seen', 'ignored')."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                "UPDATE jobs SET status = ? WHERE id = ? OR id LIKE ?",
                (new_status.value, job_id, f"{job_id}%"),
            )
            return cursor.rowcount > 0

    def mark_closed_jobs(self, source: str, run_start_time: datetime) -> int:
        """
        Mark jobs as CLOSED if they were not seen during this run for the given source.
        """
        iso_cutoff = run_start_time.isoformat()
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                UPDATE jobs
                SET status = 'closed'
                WHERE source = ? AND last_seen_at < ? AND status != 'closed'
                """,
                (source, iso_cutoff),
            )
            return cursor.rowcount

    def get_stats(self) -> dict[str, Any]:
        """Aggregate stats on total jobs, status counts, and top sources."""
        with self._get_connection() as conn:
            total_jobs = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
            status_counts = dict(
                conn.execute("SELECT status, COUNT(*) FROM jobs GROUP BY status").fetchall()
            )
            source_counts = dict(
                conn.execute("SELECT source, COUNT(*) FROM jobs GROUP BY source").fetchall()
            )
            remote_count = conn.execute("SELECT COUNT(*) FROM jobs WHERE is_remote = 1").fetchone()[0]

            # Top keywords
            cursor = conn.execute("SELECT matched_keywords FROM jobs WHERE status != 'closed'")
            keyword_counts: dict[str, int] = {}
            for row in cursor.fetchall():
                try:
                    kws = json.loads(row[0])
                    for kw in kws:
                        if not kw.startswith("NEG:"):
                            keyword_counts[kw] = keyword_counts.get(kw, 0) + 1
                except Exception:
                    continue

            top_keywords = sorted(keyword_counts.items(), key=lambda x: x[1], reverse=True)[:10]

            return {
                "total_jobs": total_jobs,
                "status_counts": status_counts,
                "source_counts": source_counts,
                "remote_count": remote_count,
                "top_keywords": top_keywords,
            }

    def export_csv(self, output_file: str | Path) -> int:
        """Export all matched jobs to CSV."""
        jobs = self.list_jobs(limit=10000)
        output_path = Path(output_file)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        fieldnames = [
            "id",
            "score",
            "status",
            "title",
            "company",
            "location",
            "is_remote",
            "url",
            "matched_keywords",
            "source",
            "first_seen_at",
            "last_seen_at",
        ]
        with open(output_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for j in jobs:
                writer.writerow({
                    "id": j.id,
                    "score": j.score,
                    "status": j.status.value,
                    "title": j.title,
                    "company": j.company,
                    "location": j.location,
                    "is_remote": j.is_remote,
                    "url": j.url,
                    "matched_keywords": ", ".join(j.matched_keywords),
                    "source": j.source,
                    "first_seen_at": j.first_seen_at.isoformat(),
                    "last_seen_at": j.last_seen_at.isoformat(),
                })
        return len(jobs)

    def export_json(self, output_file: str | Path) -> int:
        """Export all matched jobs to JSON."""
        jobs = self.list_jobs(limit=10000)
        output_path = Path(output_file)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        data = [j.model_dump(mode="json") for j in jobs]
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        return len(jobs)

    def _row_to_record(self, row: sqlite3.Row) -> JobRecord:
        """Convert a SQLite Row to a JobRecord pydantic model."""
        return JobRecord(
            id=row["id"],
            source=row["source"],
            source_job_id=row["source_job_id"],
            title=row["title"],
            company=row["company"],
            location=row["location"],
            is_remote=bool(row["is_remote"]),
            url=row["url"],
            description=row["description"],
            matched_keywords=json.loads(row["matched_keywords"]) if row["matched_keywords"] else [],
            score=float(row["score"]),
            fuzzy_key=row["fuzzy_key"],
            status=JobStatus(row["status"]),
            posted_at=datetime.fromisoformat(row["posted_at"]) if row["posted_at"] else None,
            first_seen_at=datetime.fromisoformat(row["first_seen_at"]),
            last_seen_at=datetime.fromisoformat(row["last_seen_at"]),
        )
