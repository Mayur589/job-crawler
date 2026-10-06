"""Crawl engine orchestrating the pipeline: fetch -> normalize -> match -> dedupe -> store."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncGenerator, Callable, Optional
import httpx
import yaml

from crawler.matcher import JobMatcher
from crawler.models import CrawlStats, JobRecord, JobStatus, RawJob
from crawler.normalizer import (
    canonicalize_url,
    clean_html_text,
    generate_job_id,
    is_india_location,
    is_remote_location,
    normalize_fuzzy_key,
)
from crawler.sources.base import BaseSource
from crawler.sources.greenhouse import GreenhouseSource
from crawler.sources.lever import LeverSource
from crawler.sources.remoteok import RemoteOKSource
from crawler.storage import JobStorage

logger = logging.getLogger(__name__)


class CrawlEngine:
    """Coordinates fetching from sources, normalization, keyword scoring, and SQLite persistence."""

    def __init__(
        self,
        keywords_config_path: str | Path | None = None,
        sources_config_path: str | Path | None = None,
        db_path: str | Path | None = None,
    ):
        base_dir = Path(__file__).resolve().parent.parent.parent
        self.keywords_config_path = Path(keywords_config_path or (base_dir / "config" / "keywords.yaml"))
        self.sources_config_path = Path(sources_config_path or (base_dir / "config" / "sources.yaml"))
        self.db_path = Path(db_path or (base_dir / "data" / "jobs.db"))

        self.matcher = JobMatcher(self.keywords_config_path)
        self.storage = JobStorage(self.db_path)
        self.sources: list[BaseSource] = []
        self._load_sources()

    def _load_sources(self) -> None:
        """Instantiate enabled sources from sources.yaml."""
        if not self.sources_config_path.exists():
            raise FileNotFoundError(f"Sources config not found: {self.sources_config_path}")

        with open(self.sources_config_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}

        crawler_cfg = cfg.get("crawler", {})
        ua = crawler_cfg.get("user_agent", "JobCrawler/1.0")
        timeout = float(crawler_cfg.get("request_timeout_seconds", 15.0))
        delay = float(crawler_cfg.get("rate_limit_delay_seconds", 0.5))

        src_cfg = cfg.get("sources", {})

        # 1. Greenhouse
        gh = src_cfg.get("greenhouse", {})
        if gh.get("enabled", True):
            self.sources.append(
                GreenhouseSource(
                    companies=gh.get("companies", []),
                    user_agent=ua,
                    timeout=timeout,
                    delay_seconds=delay,
                )
            )

        # 2. Lever
        lv = src_cfg.get("lever", {})
        if lv.get("enabled", True):
            self.sources.append(
                LeverSource(
                    companies=lv.get("companies", []),
                    user_agent=ua,
                    timeout=timeout,
                    delay_seconds=delay,
                )
            )

        # 3. RemoteOK
        ro = src_cfg.get("remoteok", {})
        if ro.get("enabled", True):
            self.sources.append(
                RemoteOKSource(
                    tags=ro.get("tags", ["backend", "golang", "python"]),
                    user_agent=ua,
                    timeout=timeout,
                    delay_seconds=delay,
                )
            )

    async def run(
        self,
        on_job_matched: Optional[Callable[[JobRecord, bool], None]] = None,
        on_source_start: Optional[Callable[[str], None]] = None,
        on_source_complete: Optional[Callable[[CrawlStats], None]] = None,
        mark_closed: bool = True,
    ) -> list[CrawlStats]:
        """
        Execute full crawl pipeline across all enabled sources.
        Returns statistics for each source.
        """
        stats_list: list[CrawlStats] = []
        headers = {"User-Agent": "JobCrawler/1.0"}

        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True, headers=headers) as client:
            for source in self.sources:
                stats = CrawlStats(source=source.name)
                run_start = datetime.now(timezone.utc)

                if on_source_start:
                    on_source_start(source.name)

                try:
                    async for raw_job in source.fetch_jobs(client):
                        stats.total_fetched += 1
                        job_record, is_match = self.process_raw_job(raw_job)

                        if is_match and job_record:
                            stats.total_matched += 1
                            is_new, saved_record = self.storage.upsert_job(job_record)
                            if is_new:
                                stats.total_new += 1
                            else:
                                stats.total_updated += 1

                            if on_job_matched:
                                on_job_matched(saved_record, is_new)

                    # Mark jobs closed if they were not seen in this run
                    if mark_closed:
                        closed_count = self.storage.mark_closed_jobs(source.name, run_start)
                        if closed_count > 0:
                            logger.info("Marked %d jobs as closed for %s", closed_count, source.name)

                except Exception as err:
                    logger.exception("Error during crawl of source %s: %s", source.name, err)
                    stats.errors.append(str(err))

                stats_list.append(stats)
                if on_source_complete:
                    on_source_complete(stats)

        return stats_list

    def process_raw_job(self, raw: RawJob) -> tuple[Optional[JobRecord], bool]:
        """
        Normalize and evaluate a raw job.
        Returns (JobRecord, is_match).
        """
        clean_title = clean_html_text(raw.title)
        clean_desc = clean_html_text(raw.description)
        canonical_url = canonicalize_url(raw.url)
        clean_loc = clean_html_text(raw.location)

        # Match and score
        match = self.matcher.evaluate(
            title=clean_title,
            description=clean_desc,
            location=clean_loc,
        )

        if not match.is_match:
            return None, False

        job_id = generate_job_id(raw.source, raw.source_job_id, canonical_url)
        fuzzy_key = normalize_fuzzy_key(raw.company, clean_title, clean_loc)
        remote_detected = match.is_remote or is_remote_location(clean_loc, clean_title, clean_desc)
        india_detected = is_india_location(clean_loc, clean_title, clean_desc)

        record = JobRecord(
            id=job_id,
            source=raw.source,
            source_job_id=raw.source_job_id,
            title=clean_title,
            company=raw.company,
            location=clean_loc or ("Remote" if remote_detected else "Unspecified"),
            is_remote=remote_detected,
            is_india=india_detected,
            url=canonical_url or raw.url,
            description=clean_desc,
            matched_keywords=match.matched_keywords,
            score=match.score,
            fuzzy_key=fuzzy_key,
            status=JobStatus.NEW,
            posted_at=raw.posted_at,
        )

        return record, True
