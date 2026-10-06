"""Greenhouse ATS public API source."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import AsyncGenerator
import httpx

from crawler.models import RawJob
from crawler.sources.base import BaseSource

logger = logging.getLogger(__name__)


class GreenhouseSource(BaseSource):
    """Fetches jobs from public Greenhouse boards."""

    BASE_URL = "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"

    def __init__(
        self,
        companies: list[dict[str, str]],
        user_agent: str = "JobCrawler/1.0",
        timeout: float = 15.0,
        delay_seconds: float = 0.5,
    ):
        super().__init__(name="greenhouse", user_agent=user_agent, timeout=timeout)
        self.companies = companies
        self.delay_seconds = delay_seconds

    async def fetch_jobs(self, client: httpx.AsyncClient) -> AsyncGenerator[RawJob, None]:
        """Fetch jobs for all configured Greenhouse company boards."""
        headers = self.get_headers()

        for comp in self.companies:
            slug = comp.get("slug")
            company_name = comp.get("name", slug)
            if not slug:
                continue

            url = self.BASE_URL.format(slug=slug)
            try:
                # content=true includes full job description in single API response
                response = await client.get(
                    url,
                    params={"content": "true"},
                    headers=headers,
                    timeout=self.timeout,
                )
                if response.status_code == 404:
                    logger.warning("Greenhouse board not found for %s (%s)", company_name, slug)
                    continue
                response.raise_for_status()

                data = response.json()
                jobs = data.get("jobs", [])
                logger.info("Greenhouse: Fetched %d jobs for %s", len(jobs), company_name)

                for j in jobs:
                    job_id = str(j.get("id", ""))
                    title = j.get("title", "")
                    job_url = j.get("absolute_url", "")
                    content = j.get("content", "")

                    loc_raw = j.get("location")
                    location = ""
                    if isinstance(loc_raw, dict):
                        location = loc_raw.get("name", "")
                    elif isinstance(loc_raw, str):
                        location = loc_raw

                    updated_at_str = j.get("updated_at")
                    posted_at = None
                    if updated_at_str:
                        try:
                            posted_at = datetime.fromisoformat(updated_at_str)
                        except Exception:
                            pass

                    yield RawJob(
                        source=f"greenhouse:{slug}",
                        source_job_id=job_id,
                        title=title,
                        company=company_name,
                        location=location,
                        url=job_url,
                        description=content,
                        posted_at=posted_at,
                        raw_payload=j,
                    )

                if self.delay_seconds > 0:
                    await asyncio.sleep(self.delay_seconds)

            except httpx.HTTPError as err:
                logger.error("HTTP error fetching Greenhouse jobs for %s: %s", slug, err)
            except Exception as err:
                logger.exception("Unexpected error fetching Greenhouse jobs for %s: %s", slug, err)
