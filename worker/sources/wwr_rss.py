"""WeWorkRemotely — per-category RSS feeds (richer than the general one)."""

from __future__ import annotations

import feedparser
import httpx

from ..models import RawJob
from .base import get_text

_FEEDS = [
    "https://weworkremotely.com/categories/remote-programming-jobs.rss",
    "https://weworkremotely.com/categories/remote-devops-sysadmin-jobs.rss",
    "https://weworkremotely.com/categories/remote-product-jobs.rss",
]


class WeWorkRemotely:
    name = "weworkremotely"
    interval_minutes = 360
    provides_description = True

    async def fetch(self, client: httpx.AsyncClient) -> list[RawJob]:
        jobs = []
        seen: set[str] = set()
        for feed_url in _FEEDS:
            text = await get_text(client, feed_url)
            feed = feedparser.parse(text)
            for entry in feed.entries:
                link = entry.get("link")
                if not link or link in seen:
                    continue
                seen.add(link)
                # WWR titles are "Company: Role"
                title = entry.get("title", "")
                company = None
                if ": " in title:
                    company, title = title.split(": ", 1)
                region = entry.get("region") or ""
                jobs.append(RawJob(
                    source=self.name,
                    title=title.strip(),
                    company=(company or "").strip() or None,
                    location=region.strip() or None,
                    description_html=entry.get("summary"),
                    apply_url=link,
                    source_url=link,
                    posted_raw=entry.get("published"),
                    remote_hint=True,
                    raw={"title": entry.get("title"), "link": link},
                ))
        return jobs
