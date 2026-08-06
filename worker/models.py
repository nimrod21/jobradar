"""Dataclasses passed between pipeline stages.

RawJob is what an adapter returns: the source's values, minimally mapped,
plus the untouched payload. Job is the canonical row ready for the database.
Normalisation is a separate step so adapters never know the canonical schema.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class RawJob:
    source: str                        # adapter name, e.g. 'remoteok' or 'greenhouse:workato'
    title: str
    apply_url: str
    company: str | None = None
    location: str | None = None
    description_html: str | None = None  # HTML or plain text, verbatim from the source
    source_job_id: str | None = None
    source_url: str | None = None
    posted_raw: Any = None             # whatever the source gives; parsed in dates.py
    updated_raw: Any = None
    posted_is_modified: bool = False   # e.g. Himalayas only exposes updatedAt
    salary_raw: str | None = None
    salary_min: float | None = None    # only if the source provides numbers directly
    salary_max: float | None = None
    salary_currency: str | None = None
    salary_period: str | None = None
    employment_type: str | None = None
    remote_hint: bool = False          # the source itself flags it remote
    content_fp_override: str | None = None  # HN: 'hn:{comment_id}'
    raw: dict = field(default_factory=dict)


@dataclass
class Job:
    url_fp: str | None
    content_fp: str
    title: str
    company: str | None
    location_raw: str | None
    remote_flag: bool
    geo_flags: list[str]
    employment_type: str | None
    salary_raw: str | None
    salary_min: float | None
    salary_max: float | None
    salary_currency: str | None
    salary_period: str | None
    description: str | None
    description_html: str | None
    apply_url: str
    posted_at: datetime | None
    posted_at_confident: bool
    updated_at_src: datetime | None
    source: str
    source_job_id: str | None
    source_url: str | None
