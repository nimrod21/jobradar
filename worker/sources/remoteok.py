"""RemoteOK — https://remoteok.com/api
First array element is API metadata, not a job. Their terms ask for a
link back and attribution; the app shows the source badge and the README
credits every source.
"""

from __future__ import annotations

import httpx

from ..models import RawJob
from .base import get_json


def _f(v) -> float | None:
    try:
        return float(v) or None  # "0" means unset
    except (TypeError, ValueError):
        return None


class RemoteOK:
    name = "remoteok"
    interval_minutes = 60
    provides_description = True

    async def fetch(self, client: httpx.AsyncClient) -> list[RawJob]:
        data = await get_json(client, "https://remoteok.com/api")
        jobs = []
        for item in data[1:]:  # [0] is metadata
            if not item.get("position") or not (item.get("apply_url") or item.get("url")):
                continue
            jobs.append(RawJob(
                source=self.name,
                title=item["position"],
                company=item.get("company"),
                location=(item.get("location") or "").strip(", ") or None,
                description_html=item.get("description"),
                apply_url=item.get("apply_url") or item["url"],
                source_url=item.get("url"),
                source_job_id=str(item.get("id")),
                posted_raw=item.get("date") or item.get("epoch"),
                salary_min=_f(item.get("salary_min")),
                salary_max=_f(item.get("salary_max")),
                salary_currency="USD" if _f(item.get("salary_min")) else None,
                salary_period="year" if _f(item.get("salary_min")) else None,
                remote_hint=True,
                raw=item,
            ))
        return jobs
