"""Environment and worker settings. All intervals live here, not in unit files."""

from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.environ.get("DATABASE_URL", "")
USER_AGENT = os.environ.get("USER_AGENT", "jobradar/1.0 (+https://github.com/nimrod21/jobradar)")
HTTP_CONCURRENCY = int(os.environ.get("HTTP_CONCURRENCY", "8"))
TIER3_ENABLED = os.environ.get("TIER3_ENABLED", "false").lower() == "true"

HTTP_TIMEOUT = 20.0
PER_HOST_CONCURRENCY = 2

# Adaptive registry polling (minutes) by silence duration — see 01-SOURCES.md
REGISTRY_FRESH_MIN = 60        # produced a new job in the last 7 days
REGISTRY_QUIET_MIN = 360       # quiet 7–30 days
REGISTRY_COLD_MIN = 1440       # quiet 30+ days
REGISTRY_MAX_PER_CYCLE = 100   # round-robin cap per run
