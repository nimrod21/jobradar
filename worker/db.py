"""All database writes. psycopg over the Supavisor session pooler.

The merge-upsert is raw SQL on purpose: coalesce/least merges and the
either-fingerprint match aren't expressible through PostgREST.
"""

from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import urlsplit

import psycopg

from . import config
from .fingerprint import is_aggregator_host
from .models import Job
from .slugs import parse_ats_url


def connect() -> psycopg.Connection:
    return psycopg.connect(config.DATABASE_URL, autocommit=False)


_MERGE = """
update jobs set
  last_seen_at        = now(),
  description         = coalesce(%(description)s, description),
  description_html    = coalesce(%(description_html)s, description_html),
  url_fp              = coalesce(url_fp, %(url_fp)s),
  apply_url           = %(apply_url)s,
  updated_at_src      = greatest(updated_at_src, %(updated_at_src)s),
  posted_at_confident = case
                          when %(posted_at)s is not null
                               and (posted_at is null or %(posted_at)s < posted_at)
                          then %(posted_at_confident)s
                          else posted_at_confident
                        end,
  posted_at           = least(posted_at, %(posted_at)s),
  salary_raw          = coalesce(salary_raw, %(salary_raw)s),
  salary_min          = coalesce(salary_min, %(salary_min)s),
  salary_max          = coalesce(salary_max, %(salary_max)s),
  salary_currency     = coalesce(salary_currency, %(salary_currency)s),
  salary_period       = coalesce(salary_period, %(salary_period)s),
  geo_flags           = (select array(select distinct unnest(geo_flags || %(geo_flags)s)))
where id = %(id)s
"""

_INSERT = """
insert into jobs (url_fp, content_fp, title, company, location_raw, remote_flag,
                  geo_flags, employment_type, salary_raw, salary_min, salary_max,
                  salary_currency, salary_period, description, description_html,
                  apply_url, posted_at, posted_at_confident, updated_at_src)
values (%(url_fp)s, %(content_fp)s, %(title)s, %(company)s, %(location_raw)s,
        %(remote_flag)s, %(geo_flags)s, %(employment_type)s, %(salary_raw)s,
        %(salary_min)s, %(salary_max)s, %(salary_currency)s, %(salary_period)s,
        %(description)s, %(description_html)s, %(apply_url)s,
        coalesce(%(posted_at)s, now()), %(posted_at_confident)s, %(updated_at_src)s)
on conflict do nothing
returning id
"""


def _host(url: str) -> str:
    try:
        return urlsplit(url).netloc
    except ValueError:
        return ""


def upsert_job(conn: psycopg.Connection, job: Job) -> tuple[int, bool]:
    """Insert or merge one job. Returns (job_id, is_new).

    Match on either fingerprint; unique indexes are the race backstop.
    """
    params = {
        "url_fp": job.url_fp,
        "content_fp": job.content_fp,
        "title": job.title,
        "company": job.company,
        "location_raw": job.location_raw,
        "remote_flag": job.remote_flag,
        "geo_flags": job.geo_flags,
        "employment_type": job.employment_type,
        "salary_raw": job.salary_raw,
        "salary_min": job.salary_min,
        "salary_max": job.salary_max,
        "salary_currency": job.salary_currency,
        "salary_period": job.salary_period,
        "description": job.description,
        "description_html": job.description_html,
        "apply_url": job.apply_url,
        "posted_at": job.posted_at,
        "posted_at_confident": job.posted_at_confident,
        "updated_at_src": job.updated_at_src,
    }

    with conn.cursor() as cur:
        row = _find(cur, job)
        if row is None:
            cur.execute(_INSERT, params)
            inserted = cur.fetchone()
            if inserted:
                return inserted[0], True
            row = _find(cur, job)  # concurrent writer won the race
            if row is None:
                raise RuntimeError(f"upsert race with no visible row: {job.title!r}")

        job_id, old_apply_url = row
        # Upgrade an aggregator redirect to the direct ATS link as soon as any source reveals it
        if job.url_fp is None and is_aggregator_host(_host(job.apply_url)) \
                and not is_aggregator_host(_host(old_apply_url)):
            params["apply_url"] = old_apply_url
        elif is_aggregator_host(_host(old_apply_url)) and job.url_fp is not None:
            params["apply_url"] = job.apply_url
        else:
            params["apply_url"] = old_apply_url
        params["id"] = job_id
        cur.execute(_MERGE, params)
        return job_id, False


def _find(cur: psycopg.Cursor, job: Job) -> tuple[int, str] | None:
    cur.execute(
        "select id, apply_url from jobs"
        " where content_fp = %s or (url_fp is not null and url_fp = %s)"
        " limit 1",
        (job.content_fp, job.url_fp),
    )
    return cur.fetchone()


def write_job_source(conn: psycopg.Connection, job_id: int, job: Job) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """insert into job_sources (job_id, source, source_job_id, source_url)
               values (%s, %s, %s, %s)
               on conflict (job_id, source) do update set seen_at = now()""",
            (job_id, job.source, job.source_job_id, job.source_url),
        )


def harvest_slug(conn: psycopg.Connection, job: Job) -> None:
    for url in (job.apply_url, job.source_url):
        if not url:
            continue
        parsed = parse_ats_url(url)
        if parsed:
            ats, slug = parsed
            with conn.cursor() as cur:
                cur.execute(
                    """insert into ats_registry (ats, slug, company)
                       values (%s, %s, %s) on conflict (ats, slug) do nothing""",
                    (ats, slug, job.company),
                )
            return


def record_success(conn: psycopg.Connection, source: str, jobs_count: int) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """insert into source_health (source, last_success, consecutive_failures, jobs_last_run)
               values (%s, now(), 0, %s)
               on conflict (source) do update
                 set last_success = now(), consecutive_failures = 0, jobs_last_run = %s""",
            (source, jobs_count, jobs_count),
        )
    conn.commit()


def record_failure(conn: psycopg.Connection, source: str, error: str) -> None:
    conn.rollback()  # drop whatever the failed source half-wrote
    with conn.cursor() as cur:
        cur.execute(
            """insert into source_health (source, last_error, last_error_at, consecutive_failures)
               values (%s, %s, now(), 1)
               on conflict (source) do update
                 set last_error = %s, last_error_at = now(),
                     consecutive_failures = source_health.consecutive_failures + 1""",
            (source, error[:500], error[:500]),
        )
    conn.commit()


def due_registry_boards(conn: psycopg.Connection,
                        supported: list[str]) -> list[tuple[str, str, str | None]]:
    """(ats, slug, company) rows due for polling under the adaptive policy:
    hourly while fresh (new job in the last 7 days, or never polled),
    6-hourly when quiet 7-30 days, daily beyond that. Round-robin capped
    so a big harvest can't blow the cycle budget."""
    with conn.cursor() as cur:
        cur.execute(
            """select ats, slug, company from ats_registry
               where active and ats = any(%(supported)s)
                 and (last_polled is null or last_polled < now() - make_interval(mins =>
                       case when last_new_job_at is null
                                 or last_new_job_at > now() - interval '7 days'
                            then %(fresh)s
                            when last_new_job_at > now() - interval '30 days'
                            then %(quiet)s
                            else %(cold)s end))
               order by last_polled asc nulls first
               limit %(cap)s""",
            {"supported": supported,
             "fresh": config.REGISTRY_FRESH_MIN,
             "quiet": config.REGISTRY_QUIET_MIN,
             "cold": config.REGISTRY_COLD_MIN,
             "cap": config.REGISTRY_MAX_PER_CYCLE},
        )
        return cur.fetchall()


def touch_registry(conn: psycopg.Connection, ats: str, slug: str,
                   status: int, new_jobs: int) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """update ats_registry set
                 last_polled = now(), last_status = %s,
                 last_new_job_at = case when %s > 0 then now() else last_new_job_at end,
                 active = case when %s in (404, 410) then false else active end
               where ats = %s and slug = %s""",
            (status, new_jobs, status, ats, slug),
        )
