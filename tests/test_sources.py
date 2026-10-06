"""Unit tests for Greenhouse, Lever, and RemoteOK sources using offline fixtures."""

import json
from pathlib import Path
import pytest
import httpx

from crawler.sources.greenhouse import GreenhouseSource
from crawler.sources.lever import LeverSource
from crawler.sources.remoteok import RemoteOKSource


FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


@pytest.mark.asyncio
async def test_greenhouse_source_offline(monkeypatch):
    fixture_data = json.loads((FIXTURES_DIR / "greenhouse_sample.json").read_text())

    class MockResponse:
        status_code = 200
        def json(self):
            return fixture_data
        def raise_for_status(self):
            pass

    async def mock_get(*args, **kwargs):
        return MockResponse()

    source = GreenhouseSource(
        companies=[{"slug": "gitlab", "name": "GitLab"}],
        delay_seconds=0.0,
    )

    async with httpx.AsyncClient() as client:
        monkeypatch.setattr(client, "get", mock_get)
        jobs = [j async for j in source.fetch_jobs(client)]

    assert len(jobs) == 3
    assert jobs[0].title == "Backend Engineer - Go / Distributed Systems"
    assert jobs[0].source == "greenhouse:gitlab"
    assert jobs[0].company == "GitLab"


@pytest.mark.asyncio
async def test_lever_source_offline(monkeypatch):
    fixture_data = json.loads((FIXTURES_DIR / "lever_sample.json").read_text())

    class MockResponse:
        status_code = 200
        def json(self):
            return fixture_data
        def raise_for_status(self):
            pass

    async def mock_get(*args, **kwargs):
        return MockResponse()

    source = LeverSource(
        companies=[{"slug": "spotify", "name": "Spotify"}],
        delay_seconds=0.0,
    )

    async with httpx.AsyncClient() as client:
        monkeypatch.setattr(client, "get", mock_get)
        jobs = [j async for j in source.fetch_jobs(client)]

    assert len(jobs) == 2
    assert jobs[0].title == "Senior Backend Developer - Golang"
    assert "Stockholm" in jobs[0].location
    assert "scalable cloud services" in jobs[0].description


@pytest.mark.asyncio
async def test_remoteok_source_offline(monkeypatch):
    fixture_data = json.loads((FIXTURES_DIR / "remoteok_sample.json").read_text())

    class MockResponse:
        status_code = 200
        def json(self):
            return fixture_data

    async def mock_get(*args, **kwargs):
        return MockResponse()

    source = RemoteOKSource(tags=["backend"], delay_seconds=0.0)

    async with httpx.AsyncClient() as client:
        monkeypatch.setattr(client, "get", mock_get)
        jobs = [j async for j in source.fetch_jobs(client)]

    # Legal disclaimer is skipped, so 1 valid job
    assert len(jobs) == 1
    assert jobs[0].title == "Backend Python Developer"
    assert jobs[0].company == "FastScale"
    assert jobs[0].source == "remoteok"
