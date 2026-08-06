"""Himalayas — https://himalayas.app/jobs/api
Only exposes updatedAt (modified, not created) -> posted_is_modified,
so its dates are stored low-confidence.
"""

from __future__ import annotations

import httpx

from ..models import RawJob
from .base import get_json


class Himalayas:
    name = "himalayas"
    interval_minutes = 60
    provides_description = True

    async def fetch(self, client: httpx.AsyncClient) -> list[RawJob]:
        data = await get_json(client, "https://himalayas.app/jobs/api?limit=100")
        jobs = []
        for item in data.get("jobs", []):
            title = item.get("title")
            url = item.get("applicationLink") or item.get("guid")
            if not title or not url:
                continue
            locs = item.get("locationRestrictions") or []
            jobs.append(RawJob(
                source=self.name,
                title=title,
                company=item.get("companyName"),
                location=", ".join(locs) if locs else None,
                description_html=item.get("description"),
                apply_url=url,
                source_url=item.get("guid"),
                posted_raw=item.get("pubDate") or item.get("updatedAt"),
                posted_is_modified="pubDate" not in item,
                salary_min=item.get("minSalary"),
                salary_max=item.get("maxSalary"),
                salary_currency=item.get("currency") or None,
                salary_period={"annual": "year", "monthly": "month", "hourly": "hour"}.get(
                    item.get("salaryPeriod"), item.get("salaryPeriod")),
                employment_type=", ".join(item.get("employmentType") or [])
                                if isinstance(item.get("employmentType"), list)
                                else item.get("employmentType"),
                remote_hint=True,
                raw=item,
            ))
        return jobs
