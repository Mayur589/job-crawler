"""RemoteOK public feed API source."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import AsyncGenerator
import httpx

from crawler.models import RawJob
from crawler.sources.base import BaseSource

logger = logging.getLogger(__name__)


class RemoteOKSource(BaseSource):
    """Fetches remote tech jobs from RemoteOK public API feed."""

    BASE_URL = "https://remoteok.com/api"

    def __init__(
        self,
        tags: list[str] | None = None,
        user_agent: str = "JobCrawler/1.0 (+https://github.com/mayur/job-crawler)",
        timeout: float = 15.0,
        delay_seconds: float = 1.0,
    ):
        super().__init__(name="remoteok", user_agent=user_agent, timeout=timeout)
        self.tags = tags or ["backend", "golang", "python"]
        self.delay_seconds = delay_seconds

    async def fetch_jobs(self, client: httpx.AsyncClient) -> AsyncGenerator[RawJob, None]:
        """Fetch jobs from RemoteOK."""
        headers = self.get_headers()
        # RemoteOK recommends a descriptive User-Agent
        seen_job_ids: set[str] = set()

        # Query main feed or tag feeds
        endpoints = [self.BASE_URL] + [f"{self.BASE_URL}?tag={tag}" for tag in self.tags]

        for url in endpoints:
            try:
                response = await client.get(url, headers=headers, timeout=self.timeout)
                if response.status_code != 200:
                    logger.warning("RemoteOK returned status %d for %s", response.status_code, url)
                    continue

                items = response.json()
                if not isinstance(items, list):
                    continue

                logger.info("RemoteOK: Fetched %d items from %s", len(items), url)

                for item in items:
                    if not isinstance(item, dict):
                        continue
                    # Skip legal disclaimer object
                    if "legal" in item or not item.get("id"):
                        continue

                    job_id = str(item.get("id"))
                    if job_id in seen_job_ids:
                        continue
                    seen_job_ids.add(job_id)

                    title = item.get("position", "")
                    company = item.get("company", "RemoteOK")
                    job_url = item.get("url", f"https://remoteok.com/remote-jobs/{job_id}")
                    description = item.get("description", "")
                    location = item.get("location", "Remote")

                    # Use raw description directly without injecting aggregator tags
                    description = item.get("description", "")

                    posted_at = None
                    date_str = item.get("date")
                    if date_str:
                        try:
                            posted_at = datetime.fromisoformat(date_str)
                        except Exception:
                            pass

                    yield RawJob(
                        source="remoteok",
                        source_job_id=job_id,
                        title=title,
                        company=company,
                        location=location or "Remote",
                        url=job_url,
                        description=description,
                        posted_at=posted_at,
                        raw_payload=item,
                    )

                if self.delay_seconds > 0:
                    await asyncio.sleep(self.delay_seconds)

            except httpx.HTTPError as err:
                logger.error("HTTP error fetching RemoteOK jobs from %s: %s", url, err)
            except Exception as err:
                logger.exception("Unexpected error fetching RemoteOK jobs: %s", err)
