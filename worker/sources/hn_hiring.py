"""HN "Who is hiring" — Algolia API. One thread per month, so this polls daily.

A comment has no structured title/company/apply URL, so everything is
special-cased: content_fp is 'hn:{comment_id}', the first line is parsed
against the thread convention "Company | Role | Location | ...", and the
apply URL falls back to the comment permalink. Never drop a posting for
being unparseable.
"""

from __future__ import annotations

import html as html_mod
import re

import httpx

from ..models import RawJob
from ..normalise import strip_html
from .base import get_json

_SEARCH = ("http://hn.algolia.com/api/v1/search_by_date"
           "?tags=story&query=%22Ask%20HN%3A%20Who%20is%20hiring%22&hitsPerPage=10")
_COMMENTS = ("http://hn.algolia.com/api/v1/search_by_date"
             "?tags=comment,story_{id}&hitsPerPage=1000")
_TITLE_RX = re.compile(r"^Ask HN: Who is hiring\?", re.IGNORECASE)
_HREF = re.compile(r'href="(https?://[^"]+)"')
_REMOTE = re.compile(r"\bremote\b", re.IGNORECASE)


class HNHiring:
    name = "hn_hiring"
    interval_minutes = 1440
    provides_description = True

    async def fetch(self, client: httpx.AsyncClient) -> list[RawJob]:
        search = await get_json(client, _SEARCH)
        stories = [h for h in search.get("hits", [])
                   if _TITLE_RX.match(h.get("title") or "")]
        if not stories:
            return []
        story_id = stories[0]["objectID"]  # search_by_date -> newest first

        data = await get_json(client, _COMMENTS.format(id=story_id))
        jobs = []
        for hit in data.get("hits", []):
            html = hit.get("comment_text") or ""
            comment_id = hit.get("objectID")
            if not html or not comment_id:
                continue
            plain = strip_html(html)
            first_line = plain.split("\n", 1)[0].strip()
            if not first_line:
                continue

            company = title = location = None
            parts = [p.strip() for p in first_line.split("|")]
            if len(parts) >= 2:
                company = parts[0][:120] or None
                title = parts[1][:200] or None
                if len(parts) >= 3:
                    location = parts[2][:120] or None
            if not title:  # doesn't follow the convention — keep it anyway
                title = first_line[:200]

            # Algolia entity-escapes URLs (&#x2F;) — unescape before extracting links
            links = _HREF.findall(html_mod.unescape(html))
            permalink = f"https://news.ycombinator.com/item?id={comment_id}"
            jobs.append(RawJob(
                source=self.name,
                title=title,
                company=company,
                location=location,
                description_html=html,
                apply_url=links[0] if links else permalink,
                source_url=permalink,
                source_job_id=str(comment_id),
                posted_raw=hit.get("created_at_i"),
                remote_hint=bool(_REMOTE.search(first_line)),
                content_fp_override=f"hn:{comment_id}",
                raw={"story_id": story_id, "author": hit.get("author")},
            ))
        return jobs
