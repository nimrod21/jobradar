"""Jobicy — https://jobicy.com/api/v2/remote-jobs"""

from __future__ import annotations

import httpx

from ..models import RawJob
from .base import get_json


class Jobicy:
    name = "jobicy"
    interval_minutes = 60
    provides_description = True

    async def fetch(self, client: httpx.AsyncClient) -> list[RawJob]:
        data = await get_json(client, "https://jobicy.com/api/v2/remote-jobs?count=100")
        jobs = []
        for item in data.get("jobs", []):
            if not item.get("jobTitle") or not item.get("url"):
                continue
            geo = item.get("jobGeo")
            jobs.append(RawJob(
                source=self.name,
                title=item["jobTitle"],
                company=item.get("companyName"),
                location=None if geo in (None, "Anywhere") else geo,
                description_html=item.get("jobDescription") or item.get("jobExcerpt"),
                apply_url=item["url"],
                source_url=item["url"],
                source_job_id=str(item.get("id")),
                posted_raw=item.get("pubDate"),
                salary_min=item.get("annualSalaryMin"),
                salary_max=item.get("annualSalaryMax"),
                salary_currency=item.get("salaryCurrency"),
                salary_period="year" if item.get("annualSalaryMin") else None,
                employment_type=", ".join(item.get("jobType") or []) or None,
                remote_hint=True,
                raw=item,
            ))
        return jobs
