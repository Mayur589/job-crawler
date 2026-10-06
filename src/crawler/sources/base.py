"""Base class for all job source fetchers."""

from __future__ import annotations

import abc
import logging
from typing import AsyncGenerator
import httpx

from crawler.models import RawJob

logger = logging.getLogger(__name__)


class BaseSource(abc.ABC):
    """Abstract interface that each job board / ATS source implements."""

    def __init__(self, name: str, user_agent: str = "JobCrawler/1.0", timeout: float = 15.0):
        self.name = name
        self.user_agent = user_agent
        self.timeout = timeout

    @abc.abstractmethod
    async def fetch_jobs(self, client: httpx.AsyncClient) -> AsyncGenerator[RawJob, None]:
        """Yield raw unnormalized jobs from the source asynchronously."""
        ...

    def get_headers(self) -> dict[str, str]:
        """Standard polite headers."""
        return {
            "User-Agent": self.user_agent,
            "Accept": "application/json, text/plain, */*",
        }
