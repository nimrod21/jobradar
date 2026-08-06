"""The Muse — https://www.themuse.com/api/public/jobs
Not remote-only; fetch a few pages, keep the location strings verbatim.
"""

from __future__ import annotations

import httpx

from ..models import RawJob
from .base import get_json


class TheMuse:
    name = "themuse"
    interval_minutes = 60
    provides_description = True
    pages = 3

    async def fetch(self, client: httpx.AsyncClient) -> list[RawJob]:
        jobs = []
        for page in range(1, self.pages + 1):
            data = await get_json(
                client, f"https://www.themuse.com/api/public/jobs?page={page}")
            for item in data.get("results", []):
                title = item.get("name")
                landing = (item.get("refs") or {}).get("landing_page")
                if not title or not landing:
                    continue
                locations = [l.get("name") for l in item.get("locations") or [] if l.get("name")]
                company = (item.get("company") or {}).get("name")
                jobs.append(RawJob(
                    source=self.name,
                    title=title,
                    company=company,
                    location=", ".join(locations) or None,
                    description_html=item.get("contents"),
                    apply_url=landing,
                    source_url=landing,
                    source_job_id=str(item.get("id")),
                    posted_raw=item.get("publication_date"),
                    employment_type=(item.get("levels") or [{}])[0].get("name"),
                    remote_hint=any("flexible" in loc.lower() or "remote" in loc.lower()
                                    for loc in locations),
                    raw=item,
                ))
            if not data.get("results"):
                break
        return jobs
