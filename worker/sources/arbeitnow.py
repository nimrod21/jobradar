"""Arbeitnow — https://www.arbeitnow.com/api/job-board-api"""

from __future__ import annotations

import httpx

from ..models import RawJob
from .base import get_json


class Arbeitnow:
    name = "arbeitnow"
    interval_minutes = 60
    provides_description = True

    async def fetch(self, client: httpx.AsyncClient) -> list[RawJob]:
        data = await get_json(client, "https://www.arbeitnow.com/api/job-board-api")
        jobs = []
        for item in data.get("data", []):
            if not item.get("title") or not item.get("url"):
                continue
            jobs.append(RawJob(
                source=self.name,
                title=item["title"],
                company=item.get("company_name"),
                location=item.get("location") or None,
                description_html=item.get("description"),
                apply_url=item["url"],
                source_url=item["url"],
                source_job_id=item.get("slug"),
                posted_raw=item.get("created_at"),
                employment_type=", ".join(item.get("job_types") or []) or None,
                remote_hint=bool(item.get("remote")),
                raw=item,
            ))
        return jobs
