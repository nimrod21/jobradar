"""Per-source date parsing -> aware UTC datetimes.

Adapters put whatever the source gives into RawJob.posted_raw / updated_raw;
this module sniffs the type and format. If nothing parses, posted_at stays
None and the writer falls back to first_seen_at with posted_at_confident=false
— never null in the database, it breaks every date filter.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

_MDY = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")


def _aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(value: Any) -> datetime | None:
    if value is None:
        return None

    if isinstance(value, datetime):
        return _aware(value)

    if isinstance(value, (int, float)):
        try:
            # epoch ms vs s by magnitude (ms since 2001 > 1e12)
            ts = value / 1000 if value > 1e12 else value
            return datetime.fromtimestamp(ts, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None

    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None

    # Pure digits: epoch as string
    if s.isdigit():
        return parse_date(int(s))

    # ISO 8601 (handles 'Z', offsets, date-only)
    try:
        return _aware(datetime.fromisoformat(s.replace("Z", "+00:00")))
    except ValueError:
        pass

    # RFC 822 / RSS pubDate
    try:
        return _aware(parsedate_to_datetime(s))
    except (TypeError, ValueError):
        pass

    # 'MM/DD/YYYY' (Zoho 'Date Opened') — assume US order, reject future dates
    m = _MDY.match(s)
    if m:
        mm, dd, yyyy = (int(g) for g in m.groups())
        try:
            dt = datetime(yyyy, mm, dd, tzinfo=timezone.utc)
        except ValueError:
            return None
        if dt > datetime.now(timezone.utc):
            return None
        return dt

    # Last resort: common non-ISO formats
    for fmt in ("%Y-%m-%d %H:%M:%S", "%d %b %Y", "%B %d, %Y"):
        try:
            return _aware(datetime.strptime(s, fmt))
        except ValueError:
            continue
    return None
