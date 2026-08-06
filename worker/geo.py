"""Location signals.

Three independent signals, never one normalised field:
- remote_flag: source hint, or remote-ish phrases in title/location
- geo_flags:   matched red-flag patterns, shown as badges in the app.
               Detection only — never classify eligibility; the structured
               fields lie, a badge the human reads doesn't.
- region matching: used by the app's tracker queries (region mode).
"""

from __future__ import annotations

import re

_REMOTE = re.compile(
    r"\b(remote|work from anywhere|fully remote|distributed)\b", re.IGNORECASE
)

# Literal red-flag phrases, substring-matched case-insensitively.
_FLAG_PHRASES = [
    "hybrid",
    "onsite",
    "on-site",
    "in-office",
    "must be based in",
    "must already be based",
    "relocation supported: no",
    "visa sponsorship: no",
    "unable to provide visa",
    "right to work in",
    "continental us",
    "us only",
    "us-based only",
    "regular face-to-face",
    "willing to travel",
]

# Templated red flags — these need regexes, a substring can never fire on them.
_FLAG_PATTERNS = [
    ("near <city>", re.compile(r"\bnear\s+[A-Z][a-z]+", re.UNICODE)),
    ("only <nationality> citizens", re.compile(r"\bonly\s+\w+\s+citizens\b", re.IGNORECASE)),
]

# Word-boundary guards for phrases that are substrings of innocent words
# ("onsite" in "consite" is unlikely, but "us only" in "previous only" isn't).
_PHRASE_RES = {
    p: re.compile(r"\b" + re.escape(p).replace(r"\ ", r"\s+") + r"\b", re.IGNORECASE)
    for p in _FLAG_PHRASES
}


def detect_remote(title: str | None, location: str | None, source_hint: bool) -> bool:
    if source_hint:
        return True
    for text in (title, location):
        if text and _REMOTE.search(text):
            return True
    return False


def detect_geo_flags(*texts: str | None) -> list[str]:
    corpus = " \n ".join(t for t in texts if t)
    if not corpus:
        return []
    flags = [p for p, rx in _PHRASE_RES.items() if rx.search(corpus)]
    for label, rx in _FLAG_PATTERNS:
        if rx.search(corpus):
            flags.append(label)
    return flags


# --- Regions (tracker 'region' mode) ---------------------------------------

# Broad industry regions — shortcuts, freely editable. Country- and
# city-level filtering is free text (tracker 'country' / 'place' modes),
# so nothing here limits anyone.
REGION_GROUPS: dict[str, list[str]] = {
    "emea": ["emea", "europe", "european", "cet", "gmt", "united kingdom", " uk"],
    "apac": ["apac", "asia", "australia", "new zealand", "singapore", "japan", "india"],
    "latam": ["latam", "latin america", "south america", "brazil", "mexico",
              "argentina", "colombia", "costa rica"],
    "north-america": ["north america", "united states", "usa", "u.s.", "canada"],
    "africa": ["africa", "nigeria", "kenya", "egypt"],
    "middle-east": ["middle east", "uae", "dubai", "israel", "saudi"],
    "caucasus": ["georgia", "tbilisi", "armenia", "yerevan", "azerbaijan", "baku"],
    "global": ["worldwide", "work from anywhere", "anywhere", "global"],
}

# Georgia the country, not the US state. Any of these in the location string
# vetoes a 'georgia'/'caucasus' match: "Georgia, United States", "Atlanta, GA",
# "GA, USA", a bare ", GA" suffix.
US_GEORGIA = re.compile(
    r"""(
        georgia\s*,\s*(united\ states|usa?\b)
      | ,\s*ga\b
      | \bga\s*,\s*usa?\b
      | \batlanta\b
    )""",
    re.IGNORECASE | re.VERBOSE,
)


def match_region(location_raw: str | None, region: str) -> bool:
    if not location_raw:
        return False
    terms = REGION_GROUPS.get(region)
    if not terms:
        return False
    loc = location_raw.lower()
    if region == "caucasus" and US_GEORGIA.search(loc):
        return False
    return any(t in loc for t in terms)


def match_country(location_raw: str | None, country: str) -> bool:
    """Word-boundary match on the location string. 'Georgia' gets the
    US-state veto so the country never matches Atlanta."""
    if not location_raw or not country:
        return False
    if country.strip().lower() == "georgia" and US_GEORGIA.search(location_raw):
        return False
    return re.search(r"\b" + re.escape(country.strip()) + r"\b",
                     location_raw, re.IGNORECASE) is not None
