"""Remotive — https://remotive.com/api/remote-jobs"""

from __future__ import annotations

import httpx

from ..models import RawJob
from .base import get_json


class Remotive:
    name = "remotive"
    interval_minutes = 60
    provides_description = True

    async def fetch(self, client: httpx.AsyncClient) -> list[RawJob]:
        data = await get_json(client, "https://remotive.com/api/remote-jobs")
        jobs = []
        for item in data.get("jobs", []):
            if not item.get("title") or not item.get("url"):
                continue
            jobs.append(RawJob(
                source=self.name,
                title=item["title"],
                company=item.get("company_name"),
                location=item.get("candidate_required_location") or None,
                description_html=item.get("description"),
                apply_url=item["url"],
                source_url=item["url"],
                source_job_id=str(item.get("id")),
                posted_raw=item.get("publication_date"),
                salary_raw=item.get("salary") or None,
                employment_type=item.get("job_type") or None,
                remote_hint=True,
                raw=item,
            ))
        return jobs
