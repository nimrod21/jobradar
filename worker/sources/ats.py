"""Per-company ATS board adapters, driven by ats_registry.

These are the real feed: authoritative data, exact publish dates, direct
apply URLs. One instance per (ats, slug) registry row; a class-level
semaphore keeps per-host concurrency at 2.
"""

from __future__ import annotations

import asyncio

import httpx

from ..models import RawJob
from .base import get_json

_REMOTE_TYPES = {"remote", "fully remote"}


class AtsBoard:
    """Base for registry-driven boards. name is 'ats:slug'."""

    ats: str = ""
    interval_minutes = 60  # actual cadence is decided by the registry query
    provides_description = True
    _sem: asyncio.Semaphore  # per-ATS host cap, set on each subclass

    def __init__(self, slug: str, company: str | None = None):
        self.slug = slug
        self.company = company
        self.name = f"{self.ats}:{slug}"

    @property
    def registry_key(self) -> tuple[str, str]:
        return (self.ats, self.slug)


class Greenhouse(AtsBoard):
    ats = "greenhouse"
    _sem = asyncio.Semaphore(2)

    async def fetch(self, client: httpx.AsyncClient) -> list[RawJob]:
        async with self._sem:
            data = await get_json(
                client,
                f"https://boards-api.greenhouse.io/v1/boards/{self.slug}/jobs?content=true")
        jobs = []
        for item in data.get("jobs", []):
            url = item.get("absolute_url")
            if not item.get("title") or not url:
                continue
            jobs.append(RawJob(
                source=self.name,
                title=item["title"],
                company=self.company or self.slug,
                location=(item.get("location") or {}).get("name"),
                description_html=item.get("content"),  # escaped HTML; normalise unescapes
                apply_url=url,
                source_url=url,
                source_job_id=str(item.get("id")),
                posted_raw=item.get("first_published"),
                updated_raw=item.get("updated_at"),
                raw={"metadata": item.get("metadata")},
            ))
        return jobs


class Ashby(AtsBoard):
    ats = "ashby"
    _sem = asyncio.Semaphore(2)

    async def fetch(self, client: httpx.AsyncClient) -> list[RawJob]:
        async with self._sem:
            data = await get_json(
                client, f"https://api.ashbyhq.com/posting-api/job-board/{self.slug}")
        jobs = []
        for item in data.get("jobs", []):
            url = item.get("jobUrl") or item.get("applyUrl")
            if not item.get("title") or not url or item.get("isListed") is False:
                continue
            jobs.append(RawJob(
                source=self.name,
                title=item["title"],
                company=self.company or self.slug,
                location=item.get("location"),
                description_html=item.get("descriptionHtml") or item.get("descriptionPlain"),
                apply_url=url,
                source_url=item.get("jobUrl"),
                source_job_id=str(item.get("id")),
                posted_raw=item.get("publishedAt"),
                employment_type=item.get("employmentType"),
                remote_hint=bool(item.get("isRemote")),
                raw={},
            ))
        return jobs


class Lever(AtsBoard):
    ats = "lever"
    _sem = asyncio.Semaphore(2)

    async def fetch(self, client: httpx.AsyncClient) -> list[RawJob]:
        async with self._sem:
            data = await get_json(
                client, f"https://api.lever.co/v0/postings/{self.slug}?mode=json")
        jobs = []
        for item in data if isinstance(data, list) else []:
            url = item.get("hostedUrl") or item.get("applyUrl")
            if not item.get("text") or not url:
                continue
            cats = item.get("categories") or {}
            jobs.append(RawJob(
                source=self.name,
                title=item["text"],
                company=self.company or self.slug,
                location=cats.get("location"),
                description_html=item.get("description") or item.get("descriptionPlain"),
                apply_url=url,
                source_url=item.get("hostedUrl"),
                source_job_id=str(item.get("id")),
                posted_raw=item.get("createdAt"),  # epoch ms
                employment_type=cats.get("commitment"),
                remote_hint=(item.get("workplaceType") or "").lower() in _REMOTE_TYPES,
                raw={},
            ))
        return jobs


class Workable(AtsBoard):
    ats = "workable"
    _sem = asyncio.Semaphore(2)

    async def fetch(self, client: httpx.AsyncClient) -> list[RawJob]:
        async with self._sem:
            data = await get_json(
                client,
                f"https://apply.workable.com/api/v1/widget/accounts/{self.slug}?details=true")
        company = data.get("name") or self.company or self.slug
        jobs = []
        for item in data.get("jobs", []):
            url = item.get("url") or item.get("application_url")
            if not item.get("title") or not url:
                continue
            loc = ", ".join(p for p in (item.get("city"), item.get("state"),
                                        item.get("country")) if p) or None
            jobs.append(RawJob(
                source=self.name,
                title=item["title"],
                company=company,
                location=loc,
                description_html=item.get("description"),
                apply_url=url,
                source_url=url,
                source_job_id=item.get("shortcode"),
                posted_raw=item.get("published_on"),
                employment_type=item.get("employment_type"),
                remote_hint=bool(item.get("telecommuting")),
                raw={},
            ))
        return jobs


SUPPORTED_ATS: dict[str, type[AtsBoard]] = {
    "greenhouse": Greenhouse,
    "ashby": Ashby,
    "lever": Lever,
    "workable": Workable,
}
