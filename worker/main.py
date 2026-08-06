"""Entry point. Internal scheduling loop; per-source failures never abort a run.

  python -m worker.main            run forever (systemd service mode)
  python -m worker.main --once     one cycle of everything due, then exit
  python -m worker.main --dry-run  fetch + normalise only, print stats, no database
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
import traceback
from collections import Counter

import httpx

from . import config, db
from .models import Job
from .normalise import normalise
from .sources import tier1_sources
from .sources.ats import SUPPORTED_ATS, AtsBoard
from .sources.base import Source


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=config.HTTP_TIMEOUT,
        headers={"User-Agent": config.USER_AGENT},
        follow_redirects=True,
        limits=httpx.Limits(max_connections=config.HTTP_CONCURRENCY),
    )


async def run_source(source: Source, client: httpx.AsyncClient,
                     sem: asyncio.Semaphore) -> list[Job]:
    async with sem:
        raw = await source.fetch(client)
    return [normalise(r) for r in raw]


def write_jobs(conn, source_name: str, jobs: list[Job]) -> tuple[int, int]:
    """Returns (total, new). One transaction per source."""
    new = 0
    for job in jobs:
        job_id, is_new = db.upsert_job(conn, job)
        db.write_job_source(conn, job_id, job)
        db.harvest_slug(conn, job)
        new += is_new
    conn.commit()
    return len(jobs), new


async def run_cycle(sources: list[Source], conn) -> None:
    sem = asyncio.Semaphore(config.HTTP_CONCURRENCY)
    async with _client() as client:
        tasks = {s.name: asyncio.create_task(run_source(s, client, sem)) for s in sources}
        for source in sources:
            try:
                jobs = await tasks[source.name]
                total, new = write_jobs(conn, source.name, jobs)
                if isinstance(source, AtsBoard):
                    db.touch_registry(conn, *source.registry_key, status=200, new_jobs=new)
                db.record_success(conn, source.name, total)
                print(f"  {source.name}: {total} jobs, {new} new")
            except Exception as e:  # noqa: BLE001 — a broken source must not abort the run
                db.record_failure(conn, source.name, f"{type(e).__name__}: {e}")
                if isinstance(source, AtsBoard):
                    status = e.response.status_code \
                        if isinstance(e, httpx.HTTPStatusError) else 0
                    db.touch_registry(conn, *source.registry_key, status=status, new_jobs=0)
                    conn.commit()
                print(f"  {source.name}: FAILED {type(e).__name__}: {e}", file=sys.stderr)


def registry_boards(conn) -> list[AtsBoard]:
    rows = db.due_registry_boards(conn, list(SUPPORTED_ATS))
    return [SUPPORTED_ATS[ats](slug, company) for ats, slug, company in rows]


async def dry_run(sources: list[Source]) -> None:
    sem = asyncio.Semaphore(config.HTTP_CONCURRENCY)
    async with _client() as client:
        for source in sources:
            try:
                jobs = await run_source(source, client, sem)
            except Exception as e:  # noqa: BLE001
                print(f"  {source.name}: FAILED {type(e).__name__}: {e}", file=sys.stderr)
                traceback.print_exc()
                continue
            stats = Counter(
                url_fp=sum(1 for j in jobs if j.url_fp),
                described=sum(1 for j in jobs if j.description),
                dated=sum(1 for j in jobs if j.posted_at),
                remote=sum(1 for j in jobs if j.remote_flag),
                flagged=sum(1 for j in jobs if j.geo_flags),
            )
            print(f"  {source.name}: {len(jobs)} jobs — {dict(stats)}")
            if jobs:
                j = jobs[0]
                print(f"    e.g. {j.title!r} @ {j.company!r} [{j.location_raw}] "
                      f"posted={j.posted_at} fp=({(j.url_fp or 'none')[:8]},{j.content_fp[:8]})")


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    sources = tier1_sources()

    if args.dry_run:
        await dry_run(sources)
        return

    if not config.DATABASE_URL:
        sys.exit("DATABASE_URL is not set (see .env.example)")

    last_run: dict[str, float] = {}
    while True:
        due: list[Source] = [
            s for s in sources
            if time.time() - last_run.get(s.name, 0) >= s.interval_minutes * 60]
        conn = db.connect()
        try:
            boards = registry_boards(conn)  # adaptive cadence lives in the query
            if due or boards:
                print(f"cycle: {len(due)} source(s) + {len(boards)} registry board(s) due")
                await run_cycle(due + boards, conn)
        finally:
            conn.close()
        for s in due:
            last_run[s.name] = time.time()
        if args.once:
            return
        await asyncio.sleep(60)


if __name__ == "__main__":
    asyncio.run(main())
