"""Data models for Job Crawler."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, Field


class JobStatus(str, Enum):
    NEW = "new"
    SEEN = "seen"
    APPLIED = "applied"
    SAVED = "saved"
    IGNORED = "ignored"
    CLOSED = "closed"


class RawJob(BaseModel):
    """Raw unnormalized job record directly from source."""
    source: str
    source_job_id: str
    title: str
    company: str
    location: str = ""
    url: str
    description: str = ""
    posted_at: Optional[datetime] = None
    raw_payload: dict[str, Any] = Field(default_factory=dict)


class MatchDetail(BaseModel):
    """Details about a single matched keyword or rule."""
    keyword: str
    matched_in: str  # 'title' or 'description'
    weight: float
    snippet: str = ""


class MatchResult(BaseModel):
    """Result of scoring a job against keyword rules."""
    is_match: bool
    score: float
    matched_keywords: list[str] = Field(default_factory=list)
    match_details: list[MatchDetail] = Field(default_factory=list)
    is_rejected: bool = False
    rejection_reason: Optional[str] = None
    is_remote: bool = False


class JobRecord(BaseModel):
    """Normalized and matched job record stored in database."""
    id: str  # Deterministic hash of source + source_job_id or canonical URL
    source: str
    source_job_id: str
    title: str
    company: str
    location: str
    is_remote: bool = False
    is_india: bool = False
    url: str
    description: str
    matched_keywords: list[str] = Field(default_factory=list)
    score: float = 0.0
    fuzzy_key: str  # Normalized "company|title|location" for cross-source deduplication
    status: JobStatus = JobStatus.NEW
    posted_at: Optional[datetime] = None
    first_seen_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_seen_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class CrawlStats(BaseModel):
    """Statistics for a crawling session."""
    source: str
    total_fetched: int = 0
    total_matched: int = 0
    total_new: int = 0
    total_updated: int = 0
    errors: list[str] = Field(default_factory=list)
