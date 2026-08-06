"""The interface every source implements, plus shared fetch helpers."""

from __future__ import annotations

import asyncio
from typing import Any, Protocol, runtime_checkable

import httpx

from ..models import RawJob

RETRYABLE = {429, 503}


@runtime_checkable
class Source(Protocol):
    name: str
    interval_minutes: int
    provides_description: bool

    async def fetch(self, client: httpx.AsyncClient) -> list[RawJob]: ...


async def get_json(client: httpx.AsyncClient, url: str, *, retries: int = 2) -> Any:
    """GET with exponential backoff on 429/503. Raises on anything else non-2xx."""
    delay = 5.0
    for attempt in range(retries + 1):
        resp = await client.get(url)
        if resp.status_code in RETRYABLE and attempt < retries:
            await asyncio.sleep(delay)
            delay *= 4
            continue
        resp.raise_for_status()
        return resp.json()
    raise RuntimeError("unreachable")


async def get_text(client: httpx.AsyncClient, url: str, *, retries: int = 2) -> str:
    delay = 5.0
    for attempt in range(retries + 1):
        resp = await client.get(url)
        if resp.status_code in RETRYABLE and attempt < retries:
            await asyncio.sleep(delay)
            delay *= 4
            continue
        resp.raise_for_status()
        return resp.text
    raise RuntimeError("unreachable")
