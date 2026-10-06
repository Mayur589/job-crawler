"""Lever ATS public API source."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import AsyncGenerator
import httpx

from crawler.models import RawJob
from crawler.sources.base import BaseSource

logger = logging.getLogger(__name__)


class LeverSource(BaseSource):
    """Fetches jobs from public Lever postings endpoints."""

    BASE_URL = "https://api.lever.co/v0/postings/{slug}"

    def __init__(
        self,
        companies: list[dict[str, str]],
        user_agent: str = "JobCrawler/1.0",
        timeout: float = 15.0,
        delay_seconds: float = 0.5,
    ):
        super().__init__(name="lever", user_agent=user_agent, timeout=timeout)
        self.companies = companies
        self.delay_seconds = delay_seconds

    async def fetch_jobs(self, client: httpx.AsyncClient) -> AsyncGenerator[RawJob, None]:
        """Fetch jobs for all configured Lever company postings."""
        headers = self.get_headers()

        for comp in self.companies:
            slug = comp.get("slug")
            company_name = comp.get("name", slug)
            if not slug:
                continue

            url = self.BASE_URL.format(slug=slug)
            try:
                response = await client.get(
                    url,
                    params={"mode": "json"},
                    headers=headers,
                    timeout=self.timeout,
                )
                if response.status_code == 404:
                    logger.warning("Lever board not found for %s (%s)", company_name, slug)
                    continue
                response.raise_for_status()

                postings = response.json()
                if not isinstance(postings, list):
                    logger.warning("Unexpected response format from Lever for %s", slug)
                    continue

                logger.info("Lever: Fetched %d jobs for %s", len(postings), company_name)

                for item in postings:
                    job_id = str(item.get("id", ""))
                    title = item.get("text", "")
                    job_url = item.get("hostedUrl", "")

                    # Combine descriptions
                    desc_plain = item.get("descriptionPlain", "")
                    addl_plain = item.get("additionalPlain", "")
                    raw_desc = item.get("description", "")
                    full_desc = "\n\n".join(
                        part for part in [desc_plain or raw_desc, addl_plain] if part
                    )

                    # Categories extraction
                    categories = item.get("categories", {})
                    location = ""
                    if isinstance(categories, dict):
                        location = categories.get("location", "")
                        all_locs = categories.get("allLocations", [])
                        if all_locs and location not in all_locs:
                            location = f"{location}, {', '.join(all_locs)}".strip(", ")

                    # Date posted
                    created_at_ms = item.get("createdAt")
                    posted_at = None
                    if created_at_ms and isinstance(created_at_ms, (int, float)):
                        try:
                            posted_at = datetime.fromtimestamp(created_at_ms / 1000.0, tz=timezone.utc)
                        except Exception:
                            pass

                    yield RawJob(
                        source=f"lever:{slug}",
                        source_job_id=job_id,
                        title=title,
                        company=company_name,
                        location=location,
                        url=job_url,
                        description=full_desc,
                        posted_at=posted_at,
                        raw_payload=item,
                    )

                if self.delay_seconds > 0:
                    await asyncio.sleep(self.delay_seconds)

            except httpx.HTTPError as err:
                logger.error("HTTP error fetching Lever jobs for %s: %s", slug, err)
            except Exception as err:
                logger.exception("Unexpected error fetching Lever jobs for %s: %s", slug, err)
