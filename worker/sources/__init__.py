"""Source registry: every enabled adapter, one module per source."""

from __future__ import annotations

from .base import Source
from .joblet import Joblet
from .remoteok import RemoteOK
from .remotive import Remotive


def tier1_sources() -> list[Source]:
    return [RemoteOK(), Remotive(), Joblet()]
