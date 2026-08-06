"""Apply-URL parsing -> (ats, slug) for the ats_registry.

The compounding part of the system: aggregators find companies, the registry
turns them into direct feeds.
"""

from __future__ import annotations

import re
from urllib.parse import unquote, urlsplit

# host or host-suffix -> (ats name, extractor)
# Path extractors take the split path segments.


def _first_segment(segments: list[str]) -> str | None:
    return segments[0] if segments else None


_PATH_ATS = {
    "boards.greenhouse.io": "greenhouse",
    "job-boards.greenhouse.io": "greenhouse",
    "jobs.ashbyhq.com": "ashby",
    "jobs.lever.co": "lever",
    "apply.workable.com": "workable",
    "jobs.smartrecruiters.com": "smartrecruiters",
    "ats.rippling.com": "rippling",
}

_SUBDOMAIN_ATS = [
    (re.compile(r"^([a-z0-9-]+)\.breezy\.hr$"), "breezy"),
    (re.compile(r"^([a-z0-9-]+)\.jobs\.personio\.de$"), "personio"),
    (re.compile(r"^([a-z0-9-]+)\.recruitee\.com$"), "recruitee"),
]

_SKIP_SEGMENTS = {"j", "jobs", "job", "o", "p", "en", "de", "careers"}


def parse_ats_url(url: str) -> tuple[str, str] | None:
    """Returns (ats, slug) or None if the host is not a known ATS."""
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return None
    host = parts.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    segments = [s for s in parts.path.split("/") if s]

    ats = _PATH_ATS.get(host)
    if ats:
        seg = _first_segment(segments)
        if not seg or seg.lower() in _SKIP_SEGMENTS:
            return None
        return ats, unquote(seg)

    for rx, ats in _SUBDOMAIN_ATS:
        m = rx.match(host)
        if m:
            return ats, m.group(1)
    return None
