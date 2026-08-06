"""Working Nomads — https://www.workingnomads.com/api/exposed_jobs/"""

from __future__ import annotations

import httpx

from ..models import RawJob
from .base import get_json


class WorkingNomads:
    name = "workingnomads"
    interval_minutes = 60
    provides_description = True

    async def fetch(self, client: httpx.AsyncClient) -> list[RawJob]:
        data = await get_json(client, "https://www.workingnomads.com/api/exposed_jobs/")
        jobs = []
        for item in data:
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
                posted_raw=item.get("pub_date"),
                salary_raw=item.get("salary_range") or None,
                remote_hint=True,
                raw=item,
            ))
        return jobs
