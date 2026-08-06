"""Source registry: every enabled adapter, one module per source."""

from __future__ import annotations

from .arbeitnow import Arbeitnow
from .base import Source
from .himalayas import Himalayas
from .hn_hiring import HNHiring
from .joblet import Joblet
from .jobicy import Jobicy
from .remoteok import RemoteOK
from .remotive import Remotive
from .themuse import TheMuse
from .workingnomads import WorkingNomads
from .wwr_rss import WeWorkRemotely


def tier1_sources() -> list[Source]:
    return [RemoteOK(), Remotive(), Joblet(), Arbeitnow(), Himalayas(),
            Jobicy(), WorkingNomads(), TheMuse(), WeWorkRemotely(), HNHiring()]
