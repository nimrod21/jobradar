"""joblet.ai — https://joblet.ai/api/jobs
Response: {success, data: {jobs: [...], pagination}}. Company is a nested
object; description/requirements/responsibilities are separate fields
(sometimes empty on sponsored feed items). applyUrl is a per-listing
tracking redirect (jometer.com), so url_fp is nulled by the aggregator list.
"""

from __future__ import annotations

import httpx

from ..models import RawJob
from .base import get_json


class Joblet:
    name = "joblet"
    interval_minutes = 60
    provides_description = True

    async def fetch(self, client: httpx.AsyncClient) -> list[RawJob]:
        data = await get_json(client, "https://joblet.ai/api/jobs")
        jobs = []
        for item in (data.get("data") or {}).get("jobs", []):
            title = item.get("title")
            apply_url = item.get("applyUrl")
            if not title or not apply_url:
                continue
            company = item.get("company") or {}
            desc_parts = [item.get(k) or "" for k in
                          ("description", "requirements", "responsibilities")]
            description = "\n\n".join(p for p in desc_parts if p.strip()) or None
            etypes = item.get("employmentType") or []
            jobs.append(RawJob(
                source=self.name,
                title=title,
                company=company.get("name") if isinstance(company, dict) else str(company),
                location=item.get("location") or None,
                description_html=description,
                apply_url=apply_url,
                source_job_id=str(item.get("id")),
                posted_raw=item.get("createdAt"),
                employment_type=", ".join(item.get("workSchedule") or []) or None,
                remote_hint="Remote" in etypes,
                raw=item,
            ))
        return jobs
